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
SMOOTH_MODE = 'matrix_exp'  # 'matrix_exp' | 'matrix_interp' | 'none' | 'alpha_beta' | 'kalman'
SMOOTH_ALPHA = 0.6
TARGET_FPS = 60
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

def save_prefs(prefs):
    try:
        with open(_PREFS_PATH, 'w') as f:
            json.dump(prefs, f)
        print('Preferences saved')
    except Exception as e:
        print('Failed to save prefs:', e)


def load_prefs():
    try:
        if os.path.exists(_PREFS_PATH):
            with open(_PREFS_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print('Failed to load prefs:', e)
    return {}

SERVER_THREAD = None
SERVER_SOCKET = None
SERVER_RUNNING = False
CAMERA_NAME = 'camera1'
PORT = 9000
ALPHA = 0.6  # smoothing (0..1) higher -> more immediate
CALIB_MATRIX = None  # 4x4 list
LAST_MATRIX = None


def _rowlist_to_mmatrix(lst):
    # Maya/OpenMaya expects matrix in row-major as list of 16 floats
    return om.MMatrix(lst)


def _orthonormalize_rotation(mat_list):
    """Simple Gram-Schmidt orthonormalization on the 3x3 rotation part of a 4x4 row-major matrix list."""
    # Extract 3x3 columns
    # mat_list is row-major: m[row*4 + col]
    col0 = [mat_list[0], mat_list[4], mat_list[8]]
    col1 = [mat_list[1], mat_list[5], mat_list[9]]
    col2 = [mat_list[2], mat_list[6], mat_list[10]]

    def norm(v):
        return math.sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
    def normalize(v):
        n = norm(v)
        if n == 0: return [0,0,0]
        return [v[0]/n, v[1]/n, v[2]/n]
    def dot(a,b):
        return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
    def sub(a,b,scale=1.0):
        return [a[0]-b[0]*scale, a[1]-b[1]*scale, a[2]-b[2]*scale]

    u0 = normalize(col0)
    proj1 = [u0[i]*dot(u0,col1) for i in range(3)]
    u1 = normalize(sub(col1, proj1))
    proj2 = [u0[i]*dot(u0,col2) + u1[i]*dot(u1,col2) for i in range(3)]
    u2 = normalize(sub(col2, proj2))

    # Rebuild into a new matrix list (row-major)
    new = list(mat_list)
    # set rotation entries
    new[0], new[4], new[8]  = u0[0], u0[1], u0[2]
    new[1], new[5], new[9]  = u1[0], u1[1], u1[2]
    new[2], new[6], new[10] = u2[0], u2[1], u2[2]
    return new


def _start_interp_thread():
    global INTERP_THREAD, INTERP_RUNNING
    if INTERP_RUNNING:
        return
    INTERP_RUNNING = True
    INTERP_THREAD = threading.Thread(target=_interp_loop, daemon=True)
    INTERP_THREAD.start()


def _stop_interp_thread():
    global INTERP_RUNNING
    INTERP_RUNNING = False


def _interp_loop():
    """Run at TARGET_FPS and interpolate LAST_MATRIX towards TARGET_MATRIX using alpha per frame derived from SMOOTH_ALPHA."""
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
            a = SMOOTH_ALPHA
            LAST_MATRIX = [LAST_MATRIX[i] * (1 - a) + tgt[i] * a for i in range(16)]
            # orthonormalize rotation portion to avoid drift
            LAST_MATRIX = _orthonormalize_rotation(LAST_MATRIX)
            # apply calibration
            if CALIB_MATRIX is not None:
                mm_calib = _rowlist_to_mmatrix(CALIB_MATRIX)
                mm_sm = _rowlist_to_mmatrix(LAST_MATRIX)
                mm_final = mm_calib * mm_sm
                final_list = list(mm_final)
            else:
                final_list = LAST_MATRIX

            def _set():
                try:
                    if not cmds.objExists(CAMERA_NAME):
                        cmds.warning(f"Camera '{CAMERA_NAME}' not found")
                        return
                    cmds.xform(CAMERA_NAME, ws=True, matrix=final_list)
                except Exception as e:
                    print('Error applying interpolated matrix:', e)
            cmds.evalDeferred(_set)
        elapsed = time.time() - start
        to_sleep = max(0.0, interval - elapsed)
        time.sleep(to_sleep)


def _apply_matrix_to_camera(mat_list):
    """Apply matrix with configurable smoothing modes."""
    global LAST_MATRIX, TARGET_MATRIX, LAST_POS, LAST_QUAT, POS_FILTERS
    # Helper to set matrix in Maya (deferred)
    def _set_matrix(final_matrix):
        try:
            if not cmds.objExists(CAMERA_NAME):
                cmds.warning(f"Camera '{CAMERA_NAME}' not found")
                return
            cmds.xform(CAMERA_NAME, ws=True, matrix=final_matrix)
        except Exception as e:
            print('Error applying matrix:', e)

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

def _process_packet(data):
    try:
        payload = json.loads(data.decode('utf8'))
        msg_type = payload.get('type', 'pose')
        if msg_type == 'pose':
            m = payload.get('matrix')
            if not m or len(m) != 16:
                print('Invalid matrix payload')
                return
            _apply_matrix_to_camera(m)
            if LOG_ENABLED:
                _log(f"pose,{time.time()},{m[:4]}")
        elif msg_type == 'calib':
            m = payload.get('matrix')
            if not m or len(m) != 16:
                print('Invalid calib payload')
                return
            _calibrate_from_incoming(m)
            if LOG_ENABLED:
                _log(f"calib,{time.time()}")
        elif msg_type == 'cmd':
            cmd = payload.get('cmd')
            if cmd == 'reset_calib':
                reset_calibration()
            else:
                print('Unknown cmd:', cmd)
        else:
            print('Unknown message type:', msg_type)
    except Exception as e:
        print('Packet processing error:', e)


def _server_loop(sock):
    print(f'[MagiCAM] UDP server listening on 0.0.0.0:{PORT}')
    while SERVER_RUNNING:
        try:
            data, addr = sock.recvfrom(8192)
            if not data:
                continue
            _process_packet(data)
        except socket.timeout:
            continue
        except Exception as e:
            print('Server loop error:', e)
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
    SERVER_SOCKET.bind(('0.0.0.0', PORT))
    SERVER_SOCKET.settimeout(0.5)
    SERVER_RUNNING = True

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
    if not SERVER_RUNNING:
        return
    SERVER_RUNNING = False
    try:
        # send empty packet to wake recvfrom
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

    if SERVER_SOCKET:
        SERVER_SOCKET.close()
    # disable logging
    LOG_ENABLED = False
    LOG_FILE = None
    print('Server stopping...')


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
    win = cmds.window(_UI_WINDOW_NAME, title='MagiCAM Receiver', widthHeight=(420,300))
    cmds.columnLayout(adjustableColumn=True)

    cmds.text(label='Server settings')
    _UI_ELEMENTS['portField'] = cmds.intFieldGrp(numberOfFields=1, label='Port', value1=prefs.get('port', PORT))
    _UI_ELEMENTS['cameraField'] = cmds.textFieldGrp(label='Camera', text=prefs.get('camera', CAMERA_NAME))
    _UI_ELEMENTS['oscCheck'] = cmds.checkBox(label='Use OSC', value=prefs.get('use_osc', False))

    cmds.separator(height=10)
    cmds.text(label='Smoothing')
    _UI_ELEMENTS['modeMenu'] = cmds.optionMenuGrp(label='Mode')
    cmds.menuItem(label='matrix_exp')
    cmds.menuItem(label='matrix_interp')
    cmds.menuItem(label='none')
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

    global SMOOTH_MODE, SMOOTH_ALPHA, TARGET_FPS, CAMERA_NAME
    SMOOTH_MODE = mode
    SMOOTH_ALPHA = alpha
    TARGET_FPS = fps
    CAMERA_NAME = cam

    # reset filters if using predictive mode
    if SMOOTH_MODE in ('alpha_beta', 'kalman'):
        for f in POS_FILTERS:
            f.reset()
        global LAST_QUAT, LAST_POS
        LAST_QUAT = None
        LAST_POS = None

    start_server(port=port, camera=cam, alpha=alpha, use_osc=use_osc)
    # save prefs
    prefs = {'port': port, 'camera': cam, 'use_osc': use_osc, 'smooth_mode': SMOOTH_MODE, 'smooth_alpha': SMOOTH_ALPHA, 'target_fps': TARGET_FPS}
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


if __name__ == '__main__':
    print('This module is intended to be imported into Maya, not run as standalone.')
