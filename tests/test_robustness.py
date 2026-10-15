"""F4.3/F4.4: tracking perso e buchi nel flusso -> camera ferma, poi riparte da dov'e', senza salto."""

import math

import numpy as np

from magicam.math3d import Transform, apply_anchor, quat_from_axis_angle
from magicam.protocol import PoseMessage, TrackingReason, TrackingState
from magicam.session import Hold, Session

Y = (0.0, 1.0, 0.0)
ANCHOR = Transform(pos=(5.0, 1.5, 0.0), quat=quat_from_axis_angle(Y, math.radians(90)))


def pose(x=0.0, z=0.0, t=0.0, seq=0, state=TrackingState.NORMAL) -> PoseMessage:
    return PoseMessage(seq, t, state, TrackingReason.NONE, (x, 0.0, z), (0.0, 0.0, 0.0, 1.0))


def calibrated() -> Session:
    s = Session(filter_enabled=False)
    s.calibrate(Transform(), ANCHOR)
    return s


def dist(a, b) -> float:
    return float(np.linalg.norm(np.subtract(a, b)))


def test_tracking_limited_for_2s_with_jumping_poses_keeps_camera_still_then_no_jump():
    s = calibrated()
    cam0 = s.update(pose(x=0.1, t=0.0))
    assert cam0 is not None
    # 2 s di tracking limited con pose che saltano ovunque: la camera non si muove
    rng = np.random.default_rng(1)
    for i in range(1, 121):
        p = pose(
            x=float(rng.uniform(-5, 5)), z=float(rng.uniform(-5, 5)), t=i / 60.0, seq=i, state=TrackingState.LIMITED
        )
        assert s.update(p) is None
        assert s.hold() is Hold.TRACKING
    assert s.last_camera == cam0
    # il tracking torna con il telefono in un posto QUALUNQUE (il mondo ARKit si e' spostato): nessun salto
    back = s.update(pose(x=3.7, z=-2.2, t=121 / 60.0, seq=121))
    assert back is not None
    assert dist(back.pos, cam0.pos) < 1e-9
    assert s.state().reanchors == 1
    # CONTRASTO: con la vecchia calib la camera sarebbe saltata di metri
    jumped = apply_anchor(ANCHOR, 1.0, Transform(), Transform(pos=(3.7, 0.0, -2.2)))
    assert dist(jumped.pos, cam0.pos) > 3.0
    # e il passo successivo di 10 cm vale 10 cm
    step = s.update(pose(x=3.8, z=-2.2, t=122 / 60.0, seq=122))
    assert step is not None
    assert abs(dist(step.pos, back.pos) - 0.1) < 1e-9


def test_wifi_gap_longer_than_threshold_reanchors_without_jump():
    s = calibrated()
    a = s.update(pose(x=0.0, t=0.0))
    b = s.update(pose(x=0.2, t=1 / 60.0, seq=1))
    assert a is not None and b is not None and abs(dist(b.pos, a.pos) - 0.2) < 1e-9
    # 0.8 s senza pacchetti (Wi-Fi caduto); l'operatore nel frattempo ha camminato 1 m
    c = s.update(pose(x=1.2, t=1 / 60.0 + 0.8, seq=50))
    assert c is not None
    assert dist(c.pos, b.pos) < 1e-9  # riparte da dov'era
    assert s.state().reanchors == 1
    d = s.update(pose(x=1.3, t=1 / 60.0 + 0.8 + 1 / 60.0, seq=51))
    assert d is not None and abs(dist(d.pos, c.pos) - 0.1) < 1e-9


def test_gap_below_threshold_is_not_a_reanchor():
    s = calibrated()
    s.update(pose(x=0.0, t=0.0))
    c = s.update(pose(x=0.3, t=0.4, seq=24))  # 0.4 s < 0.5 s: una semplice perdita di pacchetti
    assert c is not None
    assert s.state().reanchors == 0
    assert abs(dist(c.pos, ANCHOR.pos) - 0.3) < 1e-9  # il moto accumulato resta


def test_gap_threshold_is_configurable():
    s = Session(filter_enabled=False, gap_threshold_s=2.0)
    s.calibrate(Transform(), ANCHOR)
    s.update(pose(x=0.0, t=0.0))
    c = s.update(pose(x=1.0, t=1.5, seq=90))
    assert c is not None and s.state().reanchors == 0 and abs(dist(c.pos, ANCHOR.pos) - 1.0) < 1e-9


def test_tracking_loss_before_calibration_does_not_crash_and_holds():
    s = Session(filter_enabled=False)
    assert s.update(pose(state=TrackingState.NOT_AVAILABLE)) is None
    assert s.update(pose(t=0.1, seq=1)) is None
    assert s.hold() is Hold.NOT_CALIBRATED and s.state().reanchors == 0
