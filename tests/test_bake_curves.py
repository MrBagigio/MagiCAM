"""Curve per canale dalla take (Python puro): Euler continui, unita' interne, focale; contro risposte note."""

import math
from itertools import pairwise

import numpy as np

from magicam.math3d import Transform, quat_from_axis_angle, quat_to_mat3
from magicam.takes import Keyframe, channel_curves, euler_unwrap_deg

Y = (0.0, 1.0, 0.0)


def test_unwrap_makes_a_full_turn_continuous():
    raw = [170.0, 178.0, -178.0, -170.0, -100.0, 10.0, 100.0, 178.0, -175.0]
    out = euler_unwrap_deg(raw)
    assert out[0] == 170.0
    assert all(abs(b - a) <= 180.0 for a, b in pairwise(out))
    # sale oltre 180 invece di saltare; l'ultimo: −175 e' a un giro intero (+720) da 538 → 545
    assert out[2] == 182.0 and out[-1] == 545.0
    # CONTRASTO: i gradi grezzi hanno due salti > 180
    assert sum(1 for a, b in pairwise(raw) if abs(b - a) > 180.0) == 2


def test_unwrap_leaves_small_motion_alone_and_empty_ok():
    assert euler_unwrap_deg([]) == []
    assert euler_unwrap_deg([1.0, 2.0, -3.0]) == [1.0, 2.0, -3.0]


def test_channel_curves_known_yaw_ramp_and_units():
    keys = [
        Keyframe(
            i,
            i / 24.0,
            Transform(pos=(0.01 * i, 1.5, -0.1), quat=quat_from_axis_angle(Y, math.radians(5.0 * i))),
            1000.0,
        )
        for i in range(80)  # yaw da 0 a 395 deg: attraversa 180
    ]
    c = channel_curves(keys, 100.0, focal_scale_mm_per_px=0.036)
    assert set(c) == {"translateX", "translateY", "translateZ", "rotateX", "rotateY", "rotateZ", "focalLength"}
    assert np.allclose(c["translateX"], [1.0 * i for i in range(80)])  # 0.01 m -> 1 cm
    assert np.allclose(c["translateY"], 150.0) and np.allclose(c["translateZ"], -10.0)
    assert np.allclose(c["rotateY"], [5.0 * i for i in range(80)], atol=1e-9)  # continuo, oltre 180
    assert np.allclose(c["rotateX"], 0.0, atol=1e-9) and np.allclose(c["rotateZ"], 0.0, atol=1e-9)
    assert np.allclose(c["focalLength"], 36.0)


def test_channel_curves_euler_matches_rotation_matrix():
    """Rz*Ry*Rx dagli Euler XYZ (gradi) deve ridare la matrice del quaternione: l'ordine e' quello di Maya."""
    rng = np.random.default_rng(3)
    for _ in range(50):
        q = rng.normal(size=4)
        q = tuple(q / np.linalg.norm(q))
        c = channel_curves([Keyframe(1, 0.0, Transform(quat=q), 0.0)], 1.0)
        x, y, z = (math.radians(c[k][0]) for k in ("rotateX", "rotateY", "rotateZ"))
        rx = np.array([[1, 0, 0], [0, math.cos(x), -math.sin(x)], [0, math.sin(x), math.cos(x)]])
        ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
        rz = np.array([[math.cos(z), -math.sin(z), 0], [math.sin(z), math.cos(z), 0], [0, 0, 1]])
        assert np.allclose(rz @ ry @ rx, np.array(quat_to_mat3(q)), atol=1e-9)


def test_no_focal_curve_without_scale_or_without_data():
    k = [Keyframe(1, 0.0, Transform(), 0.0)]
    assert "focalLength" not in channel_curves(k, 100.0)
    assert "focalLength" not in channel_curves(k, 100.0, focal_scale_mm_per_px=0.03)  # focal_px = 0
