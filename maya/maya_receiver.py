"""
Maya 2024+ (Python 3.x) UDP receiver for ARKit 4x4 matrix (row-major JSON)
Usage:
    import maya_receiver
    maya_receiver.start_server(port=9000, camera='camera1')
    # calibrate current phone pose to current Maya camera
    maya_receiver.calibrate()
    # stop:
    maya_receiver.stop_server()

Notes:
- Expects JSON payload: {"matrix": [16 floats], "t": timestamp}
- Applies simple exponential smoothing (alpha)
- Use evalDeferred to update in main thread
"""

import socket
import threading
import json
import time
import math
import struct
import os

# Optional OSC support (python-osc). If not installed, OSC mode will be unavailable.
try:
    from pythonosc import dispatcher, osc_server  # type: ignore
    _HAS_PYTHONOSC = True
except Exception:
    _HAS_PYTHONOSC = False

import maya.cmds as cmds
import maya.api.OpenMaya as om

# Logging and OSC globals
LOG_FILE = None
LOG_ENABLED = False
OSC_SERVER = None
OSC_THREAD = None

# Advanced smoothing / interpolation globals
SMOOTH_MODE = 'none'  # 'matrix_exp' | 'matrix_interp' | 'none' | 'alpha_beta' | 'kalman'
SMOOTH_ALPHA = 0.25
TARGET_FPS = 60  # Higher FPS for smoother tracking

# Separate smoothing for position and rotation (used when SMOOTH_MODE='matrix_interp')
POS_ALPHA = 0.8  # 0..1 (higher = more immediate) - increased for more responsive position
ROT_ALPHA = 0.8  # quaternion slerp factor - increased for more responsive rotation
# Rotation safety
VERBOSE_DEBUG = False
MAX_ROTATION_DELTA_DEG = 180.0  # Allow full rotation range for faithful tracking
# Sender/receiver tuning (NOTE: These are the authoritative values - do NOT redeclare below)

INTERP_THREAD = None
INTERP_RUNNING = False
TARGET_MATRIX = None
TARGET_LOCK = threading.Lock()

# Simple alpha-beta predictive filter (fast approximation to Kalman for position)
class AlphaBetaFilter:
    def __init__(self, alpha=0.85, beta=0.005):
        self.alpha = alpha
        self.beta = beta
        self.x = 0.0
        self.v = 0.0
        self.last_t = None

    def reset(self, value=None):
        self.x = value if value is not None else 0.0
        self.v = 0.0
        self.last_t = None

    def update(self, meas, t=None):
        now = t or time.time()
        if self.last_t is None:
            self.x = meas
            self.v = 0.0
            self.last_t = now
            return self.x
        dt = max(1e-6, now - self.last_t)
        self.last_t = now
        # predict
        self.x += self.v * dt
        # residual
        r = meas - self.x
        self.x += self.alpha * r
        self.v += (self.beta * r) / dt
        return self.x

# Quaternion helpers

def _mat_to_quat(m):
    # m is row-major list of 16
    m00, m01, m02 = m[0], m[1], m[2]
    m10, m11, m12 = m[4], m[5], m[6]
    m20, m21, m22 = m[8], m[9], m[10]
    tr = m00 + m11 + m22
    if tr > 0:
        S = math.sqrt(tr + 1.0) * 2
        qw = 0.25 * S
        qx = (m21 - m12) / S
        qy = (m02 - m20) / S
        qz = (m10 - m01) / S
    elif (m00 > m11) and (m00 > m22):
        S = math.sqrt(1.0 + m00 - m11 - m22) * 2
        qw = (m21 - m12) / S
        qx = 0.25 * S
        qy = (m01 + m10) / S
        qz = (m02 + m20) / S
    elif m11 > m22:
        S = math.sqrt(1.0 + m11 - m00 - m22) * 2
        qw = (m02 - m20) / S
        qx = (m01 + m10) / S
        qy = 0.25 * S
        qz = (m12 + m21) / S
    else:
        S = math.sqrt(1.0 + m22 - m00 - m11) * 2
        qw = (m10 - m01) / S
        qx = (m02 + m20) / S
        qy = (m12 + m21) / S
        qz = 0.25 * S
    return (qw, qx, qy, qz)


def _quat_to_mat(q):
    qw, qx, qy, qz = q
    # compute a 3x3 rotation
    xx = qx * qx
    yy = qy * qy
    zz = qz * qz
    xy = qx * qy
    xz = qx * qz
    yz = qy * qz
    wx = qw * qx
    wy = qw * qy
    wz = qw * qz
    m00 = 1 - 2 * (yy + zz)
    m01 = 2 * (xy - wz)
    m02 = 2 * (xz + wy)
    m10 = 2 * (xy + wz)
    m11 = 1 - 2 * (xx + zz)
    m12 = 2 * (yz - wx)
    m20 = 2 * (xz - wy)
    m21 = 2 * (yz + wx)
    m22 = 1 - 2 * (xx + yy)
    # Build row-major 4x4
    return [m00, m01, m02, 0.0,
            m10, m11, m12, 0.0,
            m20, m21, m22, 0.0,
            0.0, 0.0, 0.0, 1.0]


def _quat_slerp(a, b, t):
    # a,b are (qw,qx,qy,qz)
    qw1,qx1,qy1,qz1 = a
    qw2,qx2,qy2,qz2 = b
    dotp = qw1*qw2 + qx1*qx2 + qy1*qy2 + qz1*qz2
    if dotp < 0.0:
        qw2,qx2,qy2,qz2 = -qw2, -qx2, -qy2, -qz2
        dotp = -dotp
    DOT_THRESHOLD = 0.9995
    if dotp > DOT_THRESHOLD:
        # linear
        res = (qw1 + t*(qw2 - qw1), qx1 + t*(qx2 - qx1), qy1 + t*(qy2 - qy1), qz1 + t*(qz2 - qz1))
        # normalize
        norm = math.sqrt(sum([c*c for c in res]))
        return tuple([c / norm for c in res])
    theta_0 = math.acos(dotp)
    theta = theta_0 * t
    sin_theta = math.sin(theta)
    sin_theta_0 = math.sin(theta_0)
    s0 = math.cos(theta) - dotp * sin_theta / sin_theta_0
    s1 = sin_theta / sin_theta_0
    return (qw1*s0 + qw2*s1, qx1*s0 + qx2*s1, qy1*s0 + qy2*s1, qz1*s0 + qz2*s1)

# Filters state
POS_FILTERS = [AlphaBetaFilter(), AlphaBetaFilter(), AlphaBetaFilter()]
LAST_QUAT = None
LAST_POS = None

# UI globals
_UI_WINDOW_NAME = 'MagiCAM_UI'
_UI_ELEMENTS = {}

# Preferences
_PREFS_PATH = os.path.join(os.path.expanduser('~'), '.magicam_prefs.json')

# Coordinate flip options (control yaw/pitch inversion)
FLIP_YAW = True   # inverts Z axis reflection to match ARKit->Maya yaw direction
FLIP_PITCH = True # inverts Y axis reflection to match ARKit->Maya pitch direction


def save_prefs(prefs):
    try:
        # include flip settings
        prefs = dict(prefs)
        prefs['flip_yaw'] = FLIP_YAW
        prefs['flip_pitch'] = FLIP_PITCH
        with open(_PREFS_PATH, 'w') as f:
            json.dump(prefs, f)
        print('Preferences saved')
    except Exception as e:
        print('Failed to save prefs:', e)


def load_prefs():
    try:
        if os.path.exists(_PREFS_PATH):
            with open(_PREFS_PATH, 'r') as f:
                p = json.load(f)
                # load flip settings if present
                global FLIP_YAW, FLIP_PITCH
                FLIP_YAW = p.get('flip_yaw', FLIP_YAW)
                FLIP_PITCH = p.get('flip_pitch', FLIP_PITCH)
                print(f"Prefs loaded: flip_yaw={FLIP_YAW}, flip_pitch={FLIP_PITCH}")
                return p
    except Exception as e:
        print('Failed to load prefs:', e)
    return {}

SERVER_THREAD = None
SERVER_SOCKET = None
SERVER_RUNNING = False
CAMERA_NAME = 'camera1'
PORT = 9000
ALPHA = 0.6  # smoothing (0..1) higher -> more immediate

# Safety & rate limiting
MIN_UPDATE_INTERVAL = 1.0 / 60.0  # seconds (max 60 updates/sec for smooth tracking)
LAST_RECEIVE_TIME = 0.0
RECEIVED_FRAMES = 0
DROPPED_FRAMES = 0
MAX_TRANSLATION = 10000.0  # cm - increased for cm units (100m in cm)

# Receive batching / stats
MAX_BATCH_READ = 1  # Process each packet immediately for faithful tracking
STATS_INTERVAL = 5.0  # seconds to print stats
_LAST_STATS_TIME = 0.0

CALIB_MATRIX = None  # 4x4 list
LAST_MATRIX = None


def _rowlist_to_mmatrix(lst):
    # Maya/OpenMaya expects matrix in row-major as list of 16 floats
    return om.MMatrix(lst)


def _orthonormalize_rotation(mat_list):
    """Simple Gram-Schmidt orthonormalization on the 3x3 rotation part of a 4x4 row-major matrix list.
    DISABLED: This was corrupting scale. Return matrix unchanged."""
    # Orthonormalization disabled - it was causing scale corruption
    # Just return the matrix as-is to preserve original transform
    return mat_list


def _validate_matrix(m):
    """Validate incoming 4x4 row-major matrix: finite numbers, reasonable translation magnitude."""
    try:
        if not m or len(m) != 16:
            return False
        for v in m:
            if not isinstance(v, (int, float)):
                return False
            if math.isinf(v) or math.isnan(v):
                return False
        tx, ty, tz = m[3], m[7], m[11]
        if math.sqrt(tx*tx + ty*ty + tz*tz) > MAX_TRANSLATION:
            print(f"[MagiCAM] Dropping matrix with huge translation: {tx:.3f},{ty:.3f},{tz:.3f}")
            return False
        return True
    except Exception as e:
        print('Matrix validation error:', e)
        return False


def _arkit_to_maya_matrix(mat_list):
    """Convert ARKit row-major matrix to Maya coordinate system.
    ARKit: Right-handed, Y-up, -Z forward
    Maya: Right-handed, Y-up, Z forward

    Applies optional axis reflections based on FLIP_YAW and FLIP_PITCH flags.
    Reflection matrix R = diag(1, r11, r22, 1) where r11 = -1 if FLIP_PITCH else 1
    and r22 = -1 if FLIP_YAW else 1. The output is R * M * R.
    """
    try:
        mm_in = _rowlist_to_mmatrix(mat_list)
        r00 = 1.0
        r11 = -1.0 if FLIP_PITCH else 1.0
        r22 = -1.0 if FLIP_YAW else 1.0
        R = om.MMatrix([r00, 0.0, 0.0, 0.0,
                        0.0, r11, 0.0, 0.0,
                        0.0, 0.0, r22, 0.0,
                        0.0, 0.0, 0.0, 1.0])
        mm_out = R * mm_in * R
        return list(mm_out)
    except Exception as e:
        print('Matrix conversion error:', e)
        return mat_list


def _start_interp_thread():
    global INTERP_THREAD, INTERP_RUNNING
    if INTERP_RUNNING:
        return
    INTERP_RUNNING = True
    INTERP_THREAD = threading.Thread(target=_interp_loop, daemon=True)
    INTERP_THREAD.start()


def _stop_interp_thread():
    global INTERP_RUNNING, INTERP_THREAD
    INTERP_RUNNING = False
    if INTERP_THREAD is not None:
        try:
            INTERP_THREAD.join(timeout=0.5)
        except Exception:
            pass
        INTERP_THREAD = None


def _interp_loop():
    """Run at TARGET_FPS and interpolate LAST_MATRIX towards TARGET_MATRIX using separate pos/rot smoothing.
    Uses POS_ALPHA for translation (lerp) and ROT_ALPHA for rotation (slerp), at a fixed target FPS."""
    global TARGET_MATRIX, LAST_MATRIX
    interval = 1.0 / max(1, TARGET_FPS)
    while INTERP_RUNNING:
        start = time.time()
        with TARGET_LOCK:
            tgt = TARGET_MATRIX
        if tgt is None:
            time.sleep(0.02)
            continue
        if LAST_MATRIX is None:
            LAST_MATRIX = tgt
        else:
            # extract pos and quat
            tgt_pos = [tgt[3], tgt[7], tgt[11]]
            tgt_quat = _mat_to_quat(tgt)
            last_pos = [LAST_MATRIX[3], LAST_MATRIX[7], LAST_MATRIX[11]]
            last_quat = _mat_to_quat(LAST_MATRIX)

            # lerp position
            a_pos = POS_ALPHA
            new_pos = [last_pos[i] * (1 - a_pos) + tgt_pos[i] * a_pos for i in range(3)]
            # slerp rotation with max delta clamping
            a_rot = ROT_ALPHA
            # compute angle between quaternions
            dotpq = last_quat[0]*tgt_quat[0] + last_quat[1]*tgt_quat[1] + last_quat[2]*tgt_quat[2] + last_quat[3]*tgt_quat[3]
            dotpq = max(-1.0, min(1.0, dotpq))
            angle = 2.0 * math.acos(abs(dotpq))  # angle in radians
            max_rad = math.radians(MAX_ROTATION_DELTA_DEG)
            if angle > 1e-6 and angle > max_rad:
                # limit the effective interpolation fraction so rotation change per frame is <= max_rad
                frac = max_rad / angle
                eff_t = min(a_rot, frac)
                new_quat = _quat_slerp(last_quat, tgt_quat, eff_t)
                if VERBOSE_DEBUG:
                    print(f"[MagiCAM DEBUG] Rotation jump {math.degrees(angle):.1f}deg > max {MAX_ROTATION_DELTA_DEG}deg, applying partial slerp t={eff_t:.3f}")
            else:
                new_quat = _quat_slerp(last_quat, tgt_quat, a_rot)
            
            # clamp small numerical drift
            nq_len = math.sqrt(sum([c*c for c in new_quat]))
            if nq_len == 0:
                new_quat = (1.0, 0.0, 0.0, 0.0)
            else:
                new_quat = tuple([c / nq_len for c in new_quat])

            # rebuild matrix from quat and pos
            rot_mat = _quat_to_mat(new_quat)
            final = list(rot_mat)
            final[3], final[7], final[11] = new_pos

            # apply calibration
            if CALIB_MATRIX is not None:
                mm_calib = _rowlist_to_mmatrix(CALIB_MATRIX)
                mm_sm = _rowlist_to_mmatrix(final)
                mm_final = mm_calib * mm_sm
                final_list = list(mm_final)
            else:
                final_list = final

            LAST_MATRIX = final_list

            # Use default argument to capture the current value (avoid late binding closure issue)
            def _set(mat=final_list):
                try:
                    if not cmds.objExists(CAMERA_NAME):
                        cmds.warning(f"Camera '{CAMERA_NAME}' not found")
                        return
                    cmds.xform(CAMERA_NAME, ws=True, matrix=mat)
                except Exception as e:
                    print('Error applying interpolated matrix:', e)
            cmds.evalDeferred(_set)
        elapsed = time.time() - start
        to_sleep = max(0.0, interval - elapsed)
        time.sleep(to_sleep)


def _apply_matrix_to_camera(mat_list):
    """Apply matrix with configurable smoothing modes."""
    global LAST_MATRIX, TARGET_MATRIX, LAST_POS, LAST_QUAT, POS_FILTERS
    
    # Debug: print incoming translation to verify format
    # print(f"DEBUG incoming mat: tx={mat_list[3]:.3f} ty={mat_list[7]:.3f} tz={mat_list[11]:.3f} | alt: {mat_list[12]:.3f},{mat_list[13]:.3f},{mat_list[14]:.3f}")
    
    # Helper to set matrix in Maya (deferred)
    def _set_matrix(final_matrix):
        try:
            if not cmds.objExists(CAMERA_NAME):
                cmds.warning(f"Camera '{CAMERA_NAME}' not found")
                return
            # Apply rotation via matrix and set translation explicitly (row-major indices 3,7,11)
            tx, ty, tz = final_matrix[3], final_matrix[7], final_matrix[11]
            try:
                # Apply full matrix to set rotation and other components
                cmds.xform(CAMERA_NAME, ws=True, matrix=final_matrix)
                # Then explicitly set translation (avoids matrix->translation mismatch)
                cmds.xform(CAMERA_NAME, ws=True, translation=(tx, ty, tz))
                _log(f"apply_success,tx={tx:.6f},ty={ty:.6f},tz={tz:.6f}")
            except Exception as e:
                print('Error applying matrix/translation:', e)
                try:
                    _log(f"apply_error,{e}")
                except Exception:
                    pass
        except Exception as e:
            print('Error applying matrix:', e)
            try:
                _log(f"apply_error,{e}")
            except Exception:
                pass
        except Exception as e:
            print('Error applying matrix:', e)
            try:
                _log(f"apply_error,{e}")
            except Exception:
                pass

    if SMOOTH_MODE == 'none':
        final = mat_list
        if CALIB_MATRIX is not None:
            mm_calib = _rowlist_to_mmatrix(CALIB_MATRIX)
            mm_sm = _rowlist_to_mmatrix(final)
            mm_final = mm_calib * mm_sm
            final = list(mm_final)
        cmds.evalDeferred(lambda *_: _set_matrix(final))
        return

    if SMOOTH_MODE == 'matrix_interp':
        with TARGET_LOCK:
            TARGET_MATRIX = mat_list
        _start_interp_thread()
        return

    # Alpha-beta / Kalman-like filter for translation + quaternion slerp for rotation
    if SMOOTH_MODE in ('alpha_beta', 'kalman'):
        # extract translation (row-major: indices 3,7,11)
        px, py, pz = mat_list[3], mat_list[7], mat_list[11]
        now = time.time()
        nx = POS_FILTERS[0].update(px, now)
        ny = POS_FILTERS[1].update(py, now)
        nz = POS_FILTERS[2].update(pz, now)

        # rotation
        q_meas = _mat_to_quat(mat_list)
        if LAST_QUAT is None:
            q_f = q_meas
        else:
            t = SMOOTH_ALPHA
            q_f = _quat_slerp(LAST_QUAT, q_meas, t)
        LAST_QUAT = q_f

        # build matrix from quaternion and smoothed pos
        rot_mat = _quat_to_mat(q_f)
        final = list(rot_mat)
        final[3] = nx
        final[7] = ny
        final[11] = nz

        if CALIB_MATRIX is not None:
            mm_calib = _rowlist_to_mmatrix(CALIB_MATRIX)
            mm_sm = _rowlist_to_mmatrix(final)
            mm_final = mm_calib * mm_sm
            final_list = list(mm_final)
        else:
            final_list = final
        cmds.evalDeferred(lambda *_: _set_matrix(final_list))
        return

    # Default matrix_exp elementwise smoothing
    a = SMOOTH_ALPHA if 'SMOOTH_ALPHA' in globals() else ALPHA
    if LAST_MATRIX is None:
        smoothed = mat_list
    else:
        smoothed = [LAST_MATRIX[i] * (1 - a) + mat_list[i] * a for i in range(16)]
        smoothed = _orthonormalize_rotation(smoothed)
    LAST_MATRIX = smoothed
    if CALIB_MATRIX is not None:
        mm_calib = _rowlist_to_mmatrix(CALIB_MATRIX)
        mm_sm = _rowlist_to_mmatrix(smoothed)
        mm_final = mm_calib * mm_sm
        final_list = list(mm_final)
    else:
        final_list = smoothed
    cmds.evalDeferred(lambda *_: _set_matrix(final_list))

def _process_packet(data, from_batch=False):
    """Process a single packet. Set from_batch=True when called with already-batched data to skip rate limiting."""
    global LAST_RECEIVE_TIME, RECEIVED_FRAMES, DROPPED_FRAMES
    try:
        payload = json.loads(data.decode('utf8'))
        msg_type = payload.get('type', 'pose')
        if msg_type == 'pose':
            m = payload.get('matrix')
            if not m or len(m) != 16:
                print('[MagiCAM] Invalid matrix payload')
                return
            # Validate numeric content
            if not _validate_matrix(m):
                DROPPED_FRAMES += 1
                return
            now = time.time()
            # Rate limit ONLY if not from batch (batch already did the aggregation)
            if not from_batch and now - LAST_RECEIVE_TIME < MIN_UPDATE_INTERVAL:
                DROPPED_FRAMES += 1
                return
            LAST_RECEIVE_TIME = now
            RECEIVED_FRAMES += 1
            _apply_matrix_to_camera(m)
            if LOG_ENABLED:
                _log(f"pose,{time.time()},{m[:4]}")
            # occasional stats
            if RECEIVED_FRAMES % 100 == 0:
                print(f"[MagiCAM] Received frames: {RECEIVED_FRAMES}, dropped: {DROPPED_FRAMES}")
        elif msg_type == 'calib':
            m = payload.get('matrix')
            if not m or len(m) != 16:
                print('[MagiCAM] Invalid calib payload')
                return
            if not _validate_matrix(m):
                print('[MagiCAM] Invalid calib matrix, ignoring')
                return
            _calibrate_from_incoming(m)
            if LOG_ENABLED:
                _log(f"calib,{time.time()}")
        elif msg_type == 'cmd':
            cmd = payload.get('cmd')
            if cmd == 'reset_calib':
                reset_calibration()
            else:
                print('[MagiCAM] Unknown cmd:', cmd)
        else:
            print('[MagiCAM] Unknown message type:', msg_type)
    except Exception as e:
        print('[MagiCAM] Packet processing error:', e)


def _server_loop(sock):
    print(f'[MagiCAM] UDP server listening on 0.0.0.0:{PORT}')
    import select
    global _LAST_STATS_TIME
    while SERVER_RUNNING:
        try:
            # Wait briefly for readability
            r, _, _ = select.select([sock], [], [], 0.05)
            if not r:
                # occasional stats print
                now = time.time()
                if now - _LAST_STATS_TIME > STATS_INTERVAL:
                    print(f"[MagiCAM] Stats: received={RECEIVED_FRAMES}, dropped={DROPPED_FRAMES}")
                    _LAST_STATS_TIME = now
                continue
            # Drain up to MAX_BATCH_READ packets; average the batch to reduce jitter
            batch = 0
            mats = []
            while batch < MAX_BATCH_READ:
                try:
                    data, addr = sock.recvfrom(8192)
                    if not data:
                        break
                    try:
                        payload = json.loads(data.decode('utf8'))
                        m = payload.get('matrix')
                        if m and len(m) == 16 and _validate_matrix(m):
                            mats.append(m)
                    except Exception:
                        pass
                    batch += 1
                except BlockingIOError:
                    break
                except socket.timeout:
                    break
                except Exception as e:
                    print('[MagiCAM] Server recv error:', e)
                    break
            if mats:
                # compute batch average: mean translation + averaged quaternion
                pos_sum = [0.0, 0.0, 0.0]
                quat_sum = [0.0, 0.0, 0.0, 0.0]
                for i, m in enumerate(mats):
                    tx, ty, tz = m[3], m[7], m[11]
                    pos_sum[0] += tx; pos_sum[1] += ty; pos_sum[2] += tz
                    q = _mat_to_quat(m)
                    if i == 0:
                        ref_q = q
                    else:
                        # ensure same hemisphere to avoid quaternion cancellation
                        dotp = q[0]*ref_q[0] + q[1]*ref_q[1] + q[2]*ref_q[2] + q[3]*ref_q[3]
                        if dotp < 0:
                            q = (-q[0], -q[1], -q[2], -q[3])
                    quat_sum[0] += q[0]; quat_sum[1] += q[1]; quat_sum[2] += q[2]; quat_sum[3] += q[3]
                n = len(mats)
                avg_pos = [p / n for p in pos_sum]
                # normalize quaternion sum
                qlen = math.sqrt(sum([c*c for c in quat_sum]))
                if qlen == 0:
                    avg_quat = (1.0, 0.0, 0.0, 0.0)
                else:
                    avg_quat = tuple([c / qlen for c in quat_sum])
                # build matrix from avg_quat and avg_pos
                rot_mat = _quat_to_mat(avg_quat)
                avg_mat = list(rot_mat)
                avg_mat[3], avg_mat[7], avg_mat[11] = avg_pos
                # Use from_batch=True to bypass rate limiting since we already aggregated
                _process_packet(json.dumps({'type':'pose','matrix':avg_mat,'t':time.time()}).encode('utf8'), from_batch=True)
        except Exception as e:
            # if socket was closed from another thread, break cleanly
            print('[MagiCAM] Server loop error:', e)
            break
    print('[MagiCAM] Server stopped')


def start_server(port=9000, camera='camera1', alpha=0.6, use_osc=False, log_path=None):
    """Start UDP server inside Maya.
    If `use_osc=True` and `python-osc` is installed, an OSC server will be started on the same port
    and will handle `/pose` and `/calib` messages. If `log_path` is provided, incoming messages will be logged to file.
    """
    global SERVER_THREAD, SERVER_SOCKET, SERVER_RUNNING, CAMERA_NAME, PORT, ALPHA, LOG_FILE, LOG_ENABLED, OSC_SERVER, OSC_THREAD
    if SERVER_RUNNING:
        print('Server already running')
        return
    PORT = port
    CAMERA_NAME = camera
    ALPHA = alpha
    SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    SERVER_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # increase receive buffer to handle bursts
    try:
        SERVER_SOCKET.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256 * 1024)
    except Exception:
        pass
    SERVER_SOCKET.bind(('0.0.0.0', PORT))
    # use non-blocking socket + select-based loop
    SERVER_SOCKET.setblocking(False)
    SERVER_RUNNING = True

    # Initialize LAST_MATRIX from the current Maya camera transform to avoid an initial jump
    try:
        if cmds.objExists(CAMERA_NAME):
            global LAST_MATRIX
            LAST_MATRIX = cmds.xform(CAMERA_NAME, q=True, ws=True, matrix=True)
    except Exception:
        pass

    # If interpolation mode is enabled, ensure the interpolation thread is started
    if SMOOTH_MODE == 'matrix_interp':
        _start_interp_thread()

    if log_path:
        LOG_FILE = log_path
        LOG_ENABLED = True
        _log(f"Logging enabled to {log_path}")

    if use_osc:
        if not _HAS_PYTHONOSC:
            print('[MagiCAM] python-osc not available; OSC mode disabled')
        else:
            disp = dispatcher.Dispatcher()

            def _osc_pose_handler(*args):
                vals = []
                if len(args) == 1 and isinstance(args[0], (list, tuple)):
                    vals = list(args[0])
                else:
                    vals = list(args)
                if len(vals) >= 16:
                    _apply_matrix_to_camera(vals[:16])
                    _log(f"OSC pose received: {vals[:4]} ...")

            def _osc_calib_handler(*args):
                vals = []
                if len(args) == 1 and isinstance(args[0], (list, tuple)):
                    vals = list(args[0])
                else:
                    vals = list(args)
                if len(vals) >= 16:
                    _calibrate_from_incoming(vals[:16])
                    _log('OSC calib received')

            # binary handlers: expect a single blob (bytes) containing 16 big-endian float32 values
            def _osc_pose_bin(address, blob):
                try:
                    if not isinstance(blob, (bytes, bytearray)):
                        return
                    vals = struct.unpack('!16f', blob)
                    _apply_matrix_to_camera(list(vals))
                    _log('OSC pose_bin received')
                except Exception as e:
                    print('OSC pose_bin error:', e)

            def _osc_calib_bin(address, blob):
                try:
                    if not isinstance(blob, (bytes, bytearray)):
                        return
                    vals = struct.unpack('!16f', blob)
                    _calibrate_from_incoming(list(vals))
                    _log('OSC calib_bin received')
                except Exception as e:
                    print('OSC calib_bin error:', e)

            disp.map('/pose', _osc_pose_handler)
            disp.map('/calib', _osc_calib_handler)
            disp.map('/pose_bin', _osc_pose_bin)
            disp.map('/calib_bin', _osc_calib_bin)
            OSC_SERVER = osc_server.ThreadingOSCUDPServer(('0.0.0.0', PORT), disp)
            OSC_THREAD = threading.Thread(target=OSC_SERVER.serve_forever, daemon=True)
            OSC_THREAD.start()
            print(f"[MagiCAM] OSC server listening on 0.0.0.0:{PORT}")

    # start UDP receive thread in all cases (UDP JSON remains supported)
    SERVER_THREAD = threading.Thread(target=_server_loop, args=(SERVER_SOCKET,), daemon=True)
    SERVER_THREAD.start()
    print(f'[MagiCAM] UDP server listening on 0.0.0.0:{PORT}')


def stop_server():
    global SERVER_RUNNING, SERVER_SOCKET, OSC_SERVER, OSC_THREAD, LOG_ENABLED, LOG_FILE
    global TARGET_MATRIX, LAST_MATRIX, LAST_RECEIVE_TIME, RECEIVED_FRAMES, DROPPED_FRAMES
    global INTERP_RUNNING, INTERP_THREAD, LAST_QUAT, LAST_POS
    if not SERVER_RUNNING:
        return
    SERVER_RUNNING = False
    print('Server stopping...')
    
    # Stop interpolation thread first
    INTERP_RUNNING = False
    if INTERP_THREAD is not None:
        try:
            INTERP_THREAD.join(timeout=0.5)
        except Exception:
            pass
        INTERP_THREAD = None
    
    # send empty packet to wake the select/recv loop
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(b'', ('127.0.0.1', PORT))
        s.close()
    except Exception:
        pass
    # stop OSC server if running
    try:
        if OSC_SERVER:
            OSC_SERVER.shutdown()
            OSC_SERVER.server_close()
            OSC_SERVER = None
            OSC_THREAD = None
    except Exception:
        pass

    # close server socket safely
    try:
        if SERVER_SOCKET:
            try:
                SERVER_SOCKET.close()
            except Exception as e:
                print('[MagiCAM] Error closing server socket:', e)
            finally:
                SERVER_SOCKET = None
    except Exception:
        pass

    # disable logging
    LOG_ENABLED = False
    LOG_FILE = None
    
    # Reset state for clean restart
    TARGET_MATRIX = None
    LAST_RECEIVE_TIME = 0.0
    LAST_QUAT = None
    LAST_POS = None
    # Note: Keep LAST_MATRIX so camera position persists, reset counters
    RECEIVED_FRAMES = 0
    DROPPED_FRAMES = 0
    print('[MagiCAM] Server stopped and state reset')


def calibrate():
    """Set the current Maya camera as the desired target for calibration.
    After calling this in Maya, press the "Calibrate" button on the phone app (or send a message with type 'calib') while the phone is in the reference pose. The receiver will compute CALIB so that: CALIB * incoming = desired_camera.
    """
    try:
        mat = cmds.xform(CAMERA_NAME, q=True, ws=True, matrix=True)
        # store desired target (not immediately applied). Incoming 'calib' message will compute CALIB.
        global _PENDING_CALIB_DESIRED
        _PENDING_CALIB_DESIRED = mat
        print('Calibration target saved in Maya. Now press Calibrate on the phone while in reference pose.')
    except Exception as e:
        print('Calibration failed:', e)


def _calibrate_from_incoming(incoming_list):
    """Compute CALIB = desired * inverse(incoming)
    If a desired target was previously saved with calibrate(), use it. Otherwise use the current Maya camera transform.
    """
    global CALIB_MATRIX
    try:
        # Choose desired matrix
        desired = None
        if '_PENDING_CALIB_DESIRED' in globals() and globals().get('_PENDING_CALIB_DESIRED') is not None:
            desired = globals().get('_PENDING_CALIB_DESIRED')
            # clear pending
            globals()['_PENDING_CALIB_DESIRED'] = None
        else:
            desired = cmds.xform(CAMERA_NAME, q=True, ws=True, matrix=True)

        mm_des = _rowlist_to_mmatrix(desired)
        mm_in = _rowlist_to_mmatrix(incoming_list)
        # compute inverse of incoming
        try:
            mm_inv = mm_in.inverse()
        except Exception:
            # fallback: use MTransformationMatrix to invert
            mm_inv = om.MTransformationMatrix(mm_in).asMatrix().inverse()
        mm_calib = mm_des * mm_inv
        CALIB_MATRIX = list(mm_calib)
        print('Calibration computed and saved')
        if LOG_ENABLED:
            _log('calibration_computed')
    except Exception as e:
        print('Calibration from incoming failed:', e)


def reset_calibration():
    global CALIB_MATRIX
    CALIB_MATRIX = None
    print('Calibration reset')


# Optional helper: apply identity to camera to test
def _log(msg):
    """Append a timestamped message to the log file if enabled."""
    try:
        if not LOG_ENABLED or not LOG_FILE:
            return
        with open(LOG_FILE, 'a') as f:
            f.write(f"{time.time()},{msg}\n")
    except Exception:
        pass

# Runtime setters for flips
def set_flip_yaw(v: bool):
    global FLIP_YAW
    FLIP_YAW = bool(v)
    print(f"FLIP_YAW set to {FLIP_YAW}")

def set_flip_pitch(v: bool):
    global FLIP_PITCH
    FLIP_PITCH = bool(v)
    print(f"FLIP_PITCH set to {FLIP_PITCH}")

def get_flip_status():
    return {'flip_yaw': FLIP_YAW, 'flip_pitch': FLIP_PITCH}


def enable_logging(path):
    global LOG_FILE, LOG_ENABLED
    LOG_FILE = path
    LOG_ENABLED = True
    _log('logging_enabled')
    print(f"Logging enabled to {path}")


def disable_logging():
    global LOG_FILE, LOG_ENABLED
    LOG_ENABLED = False
    LOG_FILE = None
    print('Logging disabled')


def _apply_preset_faithful():
    """Apply 1:1 faithful tracking preset - no smoothing, direct matrix application."""
    try:
        cmds.optionMenuGrp(_UI_ELEMENTS['modeMenu'], e=True, value='none')
        cmds.floatSliderGrp(_UI_ELEMENTS['alphaField'], e=True, value=1.0)
        cmds.intFieldGrp(_UI_ELEMENTS['fpsField'], e=True, value1=60)
        cmds.floatFieldGrp(_UI_ELEMENTS['posAlpha'], e=True, value1=1.0)
        cmds.floatFieldGrp(_UI_ELEMENTS['rotAlpha'], e=True, value1=1.0)
        cmds.floatFieldGrp(_UI_ELEMENTS['minInterval'], e=True, value1=0.0)
        cmds.intFieldGrp(_UI_ELEMENTS['maxBatch'], e=True, value1=1)
        cmds.floatFieldGrp(_UI_ELEMENTS['maxRotDeg'], e=True, value1=180.0)
        print('[MagiCAM] Preset FAITHFUL applied - direct 1:1 tracking')
    except Exception as e:
        print('[MagiCAM] Preset error:', e)


def _apply_preset_smooth():
    """Apply smooth tracking preset - interpolated for cinematic feel."""
    try:
        cmds.optionMenuGrp(_UI_ELEMENTS['modeMenu'], e=True, value='matrix_interp')
        cmds.floatSliderGrp(_UI_ELEMENTS['alphaField'], e=True, value=0.25)
        cmds.intFieldGrp(_UI_ELEMENTS['fpsField'], e=True, value1=30)
        cmds.floatFieldGrp(_UI_ELEMENTS['posAlpha'], e=True, value1=0.4)
        cmds.floatFieldGrp(_UI_ELEMENTS['rotAlpha'], e=True, value1=0.5)
        cmds.floatFieldGrp(_UI_ELEMENTS['minInterval'], e=True, value1=0.033)
        cmds.intFieldGrp(_UI_ELEMENTS['maxBatch'], e=True, value1=8)
        cmds.floatFieldGrp(_UI_ELEMENTS['maxRotDeg'], e=True, value1=45.0)
        print('[MagiCAM] Preset SMOOTH applied - interpolated cinematic tracking')
    except Exception as e:
        print('[MagiCAM] Preset error:', e)


def _apply_preset_predictive():
    """Apply predictive tracking preset - alpha-beta filter for natural motion."""
    try:
        cmds.optionMenuGrp(_UI_ELEMENTS['modeMenu'], e=True, value='alpha_beta')
        cmds.floatSliderGrp(_UI_ELEMENTS['alphaField'], e=True, value=0.5)
        cmds.intFieldGrp(_UI_ELEMENTS['fpsField'], e=True, value1=60)
        cmds.floatFieldGrp(_UI_ELEMENTS['posAlpha'], e=True, value1=0.6)
        cmds.floatFieldGrp(_UI_ELEMENTS['rotAlpha'], e=True, value1=0.6)
        cmds.floatFieldGrp(_UI_ELEMENTS['minInterval'], e=True, value1=0.016)
        cmds.intFieldGrp(_UI_ELEMENTS['maxBatch'], e=True, value1=4)
        cmds.floatFieldGrp(_UI_ELEMENTS['maxRotDeg'], e=True, value1=90.0)
        print('[MagiCAM] Preset PREDICTIVE applied - alpha-beta filtered tracking')
    except Exception as e:
        print('[MagiCAM] Preset error:', e)


def apply_test_identity():
    idm = [1.0,0.0,0.0,0.0,
           0.0,1.0,0.0,0.0,
           0.0,0.0,1.0,0.0,
           0.0,0.0,0.0,1.0]
    _apply_matrix_to_camera(idm)


def show_ui():
    """Create a simple Maya window to control the MagiCAM receiver."""
    global _UI_ELEMENTS
    prefs = load_prefs()
    if cmds.window(_UI_WINDOW_NAME, exists=True):
        cmds.deleteUI(_UI_WINDOW_NAME)
    win = cmds.window(_UI_WINDOW_NAME, title='MagiCAM Receiver', widthHeight=(520,420))
    cmds.columnLayout(adjustableColumn=True)

    cmds.text(label='Server settings')
    _UI_ELEMENTS['portField'] = cmds.intFieldGrp(numberOfFields=1, label='Port', value1=prefs.get('port', PORT))
    _UI_ELEMENTS['cameraField'] = cmds.textFieldGrp(label='Camera', text=prefs.get('camera', CAMERA_NAME))
    _UI_ELEMENTS['oscCheck'] = cmds.checkBox(label='Use OSC', value=prefs.get('use_osc', False))

    cmds.separator(height=10)
    cmds.text(label='Presets', font='boldLabelFont')
    cmds.rowLayout(numberOfColumns=3)
    cmds.button(label='Faithful (1:1)', command=lambda *_: _apply_preset_faithful(), bgc=(0.2, 0.6, 0.2))
    cmds.button(label='Smooth', command=lambda *_: _apply_preset_smooth(), bgc=(0.2, 0.4, 0.6))
    cmds.button(label='Predictive', command=lambda *_: _apply_preset_predictive(), bgc=(0.5, 0.3, 0.5))
    cmds.setParent('..')

    cmds.separator(height=10)
    cmds.text(label='Smoothing')
    _UI_ELEMENTS['modeMenu'] = cmds.optionMenuGrp(label='Mode')
    cmds.menuItem(label='none')
    cmds.menuItem(label='matrix_interp')
    cmds.menuItem(label='matrix_exp')
    cmds.menuItem(label='alpha_beta')
    cmds.menuItem(label='kalman')
    # set menu to saved mode
    try:
        cmds.optionMenuGrp(_UI_ELEMENTS['modeMenu'], e=True, value=prefs.get('smooth_mode', SMOOTH_MODE))
    except Exception:
        pass
    _UI_ELEMENTS['alphaField'] = cmds.floatSliderGrp(field=True, label='Alpha', value=prefs.get('smooth_alpha', SMOOTH_ALPHA), minValue=0.0, maxValue=1.0)
    _UI_ELEMENTS['fpsField'] = cmds.intFieldGrp(numberOfFields=1, label='Target FPS', value1=prefs.get('target_fps', TARGET_FPS))

    cmds.separator(height=10)
    cmds.text(label='Advanced')
    _UI_ELEMENTS['posAlpha'] = cmds.floatFieldGrp(numberOfFields=1, label='Pos Alpha', value1=prefs.get('pos_alpha', POS_ALPHA))
    _UI_ELEMENTS['rotAlpha'] = cmds.floatFieldGrp(numberOfFields=1, label='Rot Alpha', value1=prefs.get('rot_alpha', ROT_ALPHA))
    _UI_ELEMENTS['minInterval'] = cmds.floatFieldGrp(numberOfFields=1, label='Min Interval (s)', value1=prefs.get('min_interval', MIN_UPDATE_INTERVAL))
    _UI_ELEMENTS['maxBatch'] = cmds.intFieldGrp(numberOfFields=1, label='Max Batch Read', value1=prefs.get('max_batch', MAX_BATCH_READ))
    _UI_ELEMENTS['verboseDebug'] = cmds.checkBox(label='Verbose Debug', value=prefs.get('verbose_debug', VERBOSE_DEBUG))
    _UI_ELEMENTS['maxRotDeg'] = cmds.floatFieldGrp(numberOfFields=1, label='Max Rot Delta (deg)', value1=prefs.get('max_rot_deg', MAX_ROTATION_DELTA_DEG))

    cmds.separator(height=10)
    cmds.rowLayout(numberOfColumns=5)
    cmds.button(label='Start', command=lambda *_: _ui_start())
    cmds.button(label='Stop', command=lambda *_: _ui_stop())
    cmds.button(label='Calibrate', command=lambda *_: maya_receiver_calibrate())
    cmds.button(label='Reset Calib', command=lambda *_: reset_calibration())
    cmds.button(label='Create Shelf', command=lambda *_: create_shelf_button())
    cmds.setParent('..')

    cmds.separator(height=10)
    cmds.rowLayout(numberOfColumns=4)
    _UI_ELEMENTS['statusText'] = cmds.text(label='Status: stopped')
    cmds.button(label='Enable Log', command=lambda *_: _ui_enable_log())
    cmds.button(label='Disable Log', command=lambda *_: disable_logging())
    cmds.button(label='Close', command=lambda *_: close_ui())
    cmds.setParent('..')

    cmds.showWindow(win)


def close_ui():
    if cmds.window(_UI_WINDOW_NAME, exists=True):
        cmds.deleteUI(_UI_WINDOW_NAME)


def _ui_start():
    port = cmds.intFieldGrp(_UI_ELEMENTS['portField'], q=True, value1=True)
    cam = cmds.textFieldGrp(_UI_ELEMENTS['cameraField'], q=True, text=True)
    mode = cmds.optionMenuGrp(_UI_ELEMENTS['modeMenu'], q=True, value=True)
    alpha = cmds.floatSliderGrp(_UI_ELEMENTS['alphaField'], q=True, value=True)
    fps = cmds.intFieldGrp(_UI_ELEMENTS['fpsField'], q=True, value1=True)
    use_osc = cmds.checkBox(_UI_ELEMENTS['oscCheck'], q=True, value=True)

    pos_alpha = cmds.floatFieldGrp(_UI_ELEMENTS['posAlpha'], q=True, value1=True)
    rot_alpha = cmds.floatFieldGrp(_UI_ELEMENTS['rotAlpha'], q=True, value1=True)
    min_interval = cmds.floatFieldGrp(_UI_ELEMENTS['minInterval'], q=True, value1=True)
    max_batch = cmds.intFieldGrp(_UI_ELEMENTS['maxBatch'], q=True, value1=True)
    verbose = cmds.checkBox(_UI_ELEMENTS['verboseDebug'], q=True, value=True)
    max_rot_deg = cmds.floatFieldGrp(_UI_ELEMENTS['maxRotDeg'], q=True, value1=True)

    global SMOOTH_MODE, SMOOTH_ALPHA, TARGET_FPS, CAMERA_NAME, POS_ALPHA, ROT_ALPHA, MIN_UPDATE_INTERVAL, MAX_BATCH_READ, VERBOSE_DEBUG, MAX_ROTATION_DELTA_DEG
    SMOOTH_MODE = mode
    SMOOTH_ALPHA = alpha
    TARGET_FPS = fps
    CAMERA_NAME = cam
    POS_ALPHA = pos_alpha
    ROT_ALPHA = rot_alpha
    MIN_UPDATE_INTERVAL = max(1e-4, min_interval)
    MAX_BATCH_READ = max(1, max_batch)
    VERBOSE_DEBUG = bool(verbose)
    MAX_ROTATION_DELTA_DEG = float(max_rot_deg)

    # reset filters if using predictive mode
    if SMOOTH_MODE in ('alpha_beta', 'kalman'):
        for f in POS_FILTERS:
            f.reset()
        global LAST_QUAT, LAST_POS
        LAST_QUAT = None
        LAST_POS = None

    start_server(port=port, camera=cam, alpha=alpha, use_osc=use_osc)
    # save prefs
    prefs = {'port': port, 'camera': cam, 'use_osc': use_osc, 'smooth_mode': SMOOTH_MODE, 'smooth_alpha': SMOOTH_ALPHA, 'target_fps': TARGET_FPS, 'pos_alpha': POS_ALPHA, 'rot_alpha': ROT_ALPHA, 'min_interval': MIN_UPDATE_INTERVAL, 'max_batch': MAX_BATCH_READ}
    save_prefs(prefs)
    try:
        cmds.text(_UI_ELEMENTS['statusText'], e=True, label='Status: running')
    except Exception:
        pass


def _ui_stop():
    stop_server()
    _stop_interp_thread()
    try:
        cmds.text(_UI_ELEMENTS['statusText'], e=True, label='Status: stopped')
    except Exception:
        pass


def _ui_enable_log():
    import os
    p = 'C:/temp/magicam_log.csv'
    os.makedirs(os.path.dirname(p), exist_ok=True)
    enable_logging(p)


# Backwards compatibility shim for the earlier calibrate() button binding
def maya_receiver_calibrate():
    calibrate()


def create_shelf_button(shelf_name='MagiCAM'):
    """Create a shelf and a button that opens the MagiCAM UI."""
    try:
        # ensure shelf exists
        if not cmds.shelfLayout(shelf_name, ex=True):
            cmds.shelfLayout(shelf_name, parent='ShelfLayout')
        # create shelf button
        icon = 'commandButton.png'
        cmds.shelfButton(parent=shelf_name, image=icon, label='MagiCAM', annotation='Open MagiCAM Receiver', command="python(\'import maya_receiver; maya_receiver.show_ui()\')")
        print(f'Shelf button created in shelf {shelf_name}')
    except Exception as e:
        print('Failed to create shelf button:', e)


# Debug helpers for interactive troubleshooting in Maya
def force_apply_matrix(matrix):
    """Immediately apply a 4x4 row-major matrix to the configured camera (synchronous)."""
    try:
        if not cmds.objExists(CAMERA_NAME):
            print(f"[MagiCAM DEBUG] Camera '{CAMERA_NAME}' not found")
            return False
        # Apply immediately (synchronous)
        cmds.xform(CAMERA_NAME, ws=True, matrix=matrix)
        print(f"[MagiCAM DEBUG] force_applied matrix to {CAMERA_NAME}")
        return True
    except Exception as e:
        print('[MagiCAM DEBUG] force_apply_matrix error:', e)
        return False


def force_apply_last():
    """Force-apply the last received matrix (bypasses smoothing/interp)."""
    try:
        if LAST_MATRIX is None:
            print('[MagiCAM DEBUG] No LAST_MATRIX available to apply')
            return False
        return force_apply_matrix(LAST_MATRIX)
    except Exception as e:
        print('[MagiCAM DEBUG] force_apply_last error:', e)
        return False


def diagnose():
    """Print comprehensive diagnostic info about current MagiCAM state."""
    print("=" * 60)
    print("MagiCAM DIAGNOSTIC REPORT")
    print("=" * 60)
    print(f"SERVER_RUNNING: {SERVER_RUNNING}")
    print(f"CAMERA_NAME: {CAMERA_NAME}")
    print(f"PORT: {PORT}")
    print(f"SMOOTH_MODE: {SMOOTH_MODE}")
    print(f"RECEIVED_FRAMES: {RECEIVED_FRAMES}")
    print(f"DROPPED_FRAMES: {DROPPED_FRAMES}")
    print(f"MIN_UPDATE_INTERVAL: {MIN_UPDATE_INTERVAL}")
    print(f"MAX_BATCH_READ: {MAX_BATCH_READ}")
    print(f"POS_ALPHA: {POS_ALPHA}")
    print(f"ROT_ALPHA: {ROT_ALPHA}")
    print(f"VERBOSE_DEBUG: {VERBOSE_DEBUG}")
    print(f"INTERP_RUNNING: {INTERP_RUNNING}")
    print(f"TARGET_MATRIX: {TARGET_MATRIX is not None}")
    print(f"LAST_MATRIX: {LAST_MATRIX is not None}")
    print(f"CALIB_MATRIX: {CALIB_MATRIX is not None}")
    
    # Check camera
    try:
        if cmds.objExists(CAMERA_NAME):
            cam_mat = cmds.xform(CAMERA_NAME, q=True, ws=True, matrix=True)
            print(f"Camera '{CAMERA_NAME}' exists")
            print(f"  Current matrix[3,7,11] (pos): {cam_mat[3]:.4f}, {cam_mat[7]:.4f}, {cam_mat[11]:.4f}")
        else:
            print(f"Camera '{CAMERA_NAME}' DOES NOT EXIST!")
    except Exception as e:
        print(f"Error checking camera: {e}")
    
    if LAST_MATRIX:
        print(f"LAST_MATRIX[3,7,11] (pos): {LAST_MATRIX[3]:.4f}, {LAST_MATRIX[7]:.4f}, {LAST_MATRIX[11]:.4f}")
    if TARGET_MATRIX:
        print(f"TARGET_MATRIX[3,7,11] (pos): {TARGET_MATRIX[3]:.4f}, {TARGET_MATRIX[7]:.4f}, {TARGET_MATRIX[11]:.4f}")
    
    print("=" * 60)
    print("To test camera movement, run:")
    print("  maya_receiver.force_apply_matrix([1,0,0,1, 0,1,0,2, 0,0,1,3, 0,0,0,1])")
    print("=" * 60)
    return True


if __name__ == '__main__':
    print('This module is intended to be imported into Maya, not run as standalone.')
