"""session: calibra, freeze senza salto (col contrasto), ricentra, scala senza salto, tracking, blocchi."""

import math

import numpy as np

from magicam.math3d import Transform, apply_anchor, quat_angle, quat_from_axis_angle
from magicam.protocol import PoseMessage, TrackingReason, TrackingState
from magicam.session import Hold, Session

Y = (0.0, 1.0, 0.0)
ANCHOR = Transform(pos=(5.0, 1.5, 0.0), quat=quat_from_axis_angle(Y, math.radians(90)))


def pose(x=0.0, y=0.0, z=0.0, yaw_deg=0.0, seq=0, t=0.0, state=TrackingState.NORMAL) -> PoseMessage:
    return PoseMessage(seq, t, state, TrackingReason.NONE, (x, y, z), quat_from_axis_angle(Y, math.radians(yaw_deg)))


def session_calibrated(filter_enabled=False) -> Session:
    s = Session(filter_enabled=filter_enabled)
    s.calibrate(Transform(), ANCHOR)
    return s


def test_not_calibrated_holds():
    s = Session()
    assert s.update(pose()) is None
    assert s.hold() is Hold.NOT_CALIBRATED


def test_calibrated_anchor_case_f():
    s = session_calibrated()
    cam = s.update(pose(z=-0.1))
    assert cam is not None
    assert np.allclose(cam.pos, (4.9, 1.5, 0.0), atol=1e-9)
    assert quat_angle(cam.quat, ANCHOR.quat) < 1e-9


def test_tracking_limited_holds_and_resumes():
    s = session_calibrated()
    assert s.update(pose(x=0.1, state=TrackingState.LIMITED)) is None
    assert s.hold() is Hold.TRACKING
    cam = s.update(pose(x=0.1))
    assert cam is not None and s.hold() is Hold.NONE


def test_freeze_then_unfreeze_has_no_jump_with_contrast():
    s = session_calibrated()
    s.update(pose(x=0.0))
    s.freeze()
    assert s.update(pose(x=1.0)) is None  # l'operatore si sposta di 1 m col freeze
    assert s.hold() is Hold.FROZEN
    s.unfreeze()
    cam = s.update(pose(x=1.0))
    assert cam is not None
    assert np.allclose(cam.pos, ANCHOR.pos, atol=1e-9)  # nessun salto
    # e il passo successivo di 10 cm vale 10 cm, nel telaio dell'ancora (X del telefono -> X dell'ancora girata 90 = -Z)
    cam2 = s.update(pose(x=1.1))
    assert cam2 is not None
    assert abs(np.linalg.norm(np.subtract(cam2.pos, cam.pos)) - 0.1) < 1e-9
    # CONTRASTO: senza il ri-ancoraggio la camera sarebbe saltata di 1 m
    jumped = apply_anchor(ANCHOR, 1.0, Transform(), Transform(pos=(1.0, 0, 0)))
    assert abs(np.linalg.norm(np.subtract(jumped.pos, ANCHOR.pos)) - 1.0) < 1e-9


def test_recenter_brings_camera_back_to_anchor():
    s = session_calibrated()
    far = s.update(pose(x=0.7))
    assert far is not None and not np.allclose(far.pos, ANCHOR.pos)
    assert s.recenter()
    cam = s.update(pose(x=0.7))
    assert cam is not None and np.allclose(cam.pos, ANCHOR.pos, atol=1e-9)


def test_scale_change_has_no_jump_and_applies_to_relative_motion():
    s = session_calibrated()
    s.update(pose(x=0.5))
    before = s.last_camera
    s.set_scale(0.1)
    after = s.update(pose(x=0.5))
    assert before is not None and after is not None
    assert np.allclose(after.pos, before.pos, atol=1e-9)
    step = s.update(pose(x=0.6))
    assert step is not None
    assert abs(np.linalg.norm(np.subtract(step.pos, after.pos)) - 0.01) < 1e-9


def test_axis_locks():
    s = session_calibrated()
    s.locks.height = True
    cam = s.update(pose(y=0.3))
    assert cam is not None and cam.pos[1] == ANCHOR.pos[1]
    s.locks.dolly = True
    cam = s.update(pose(x=0.3, z=0.3, yaw_deg=10))
    assert cam is not None
    assert np.allclose(cam.pos, ANCHOR.pos, atol=1e-9)
    assert abs(math.degrees(quat_angle(cam.quat, ANCHOR.quat)) - 10.0) < 1e-9  # ruota, non trasla


def test_filter_on_converges_to_the_same_answer():
    s = session_calibrated(filter_enabled=True)
    cam = None
    for i in range(600):
        cam = s.update(pose(z=-0.1, seq=i, t=i / 60.0))
    assert cam is not None
    assert np.allclose(cam.pos, (4.9, 1.5, 0.0), atol=1e-4)


def test_reset():
    s = session_calibrated()
    s.reset()
    assert s.hold() is Hold.NOT_CALIBRATED and s.last_camera is None
