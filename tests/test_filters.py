"""filters: ingresso costante, gradino, rumore noto, dt irregolare, emisfero del quaternione."""

import math
import random
import statistics
from itertools import pairwise

import pytest

from magicam.filters import OneEuro, OneEuroQuat, OneEuroVec3
from magicam.math3d import quat_angle, quat_from_axis_angle

Y = (0.0, 1.0, 0.0)
DT = 1.0 / 60.0


def test_constant_input_is_passed_unchanged():
    f = OneEuro()
    for i in range(100):
        assert f.filter(3.0, i * DT) == 3.0


def test_step_converges_monotonically_and_rise_time_is_declared():
    f = OneEuro(min_cutoff=1.0, beta=0.0)
    out = [f.filter(0.0, 0.0)]
    for i in range(1, 300):
        out.append(f.filter(1.0, i * DT))
    assert all(b >= a for a, b in pairwise(out))
    assert out[-1] > 0.99
    # con cutoff 1 Hz (tau = 1/(2*pi) ~ 0.159 s) il 63% si raggiunge entro ~0.16 s: atteso scritto prima
    t63 = next(i * DT for i, v in enumerate(out) if v >= 0.63)
    assert 0.12 < t63 < 0.22, t63


def test_noise_is_attenuated_while_mean_is_kept():
    rng = random.Random(0)
    f = OneEuro(min_cutoff=1.0, beta=0.0)
    xs = [5.0 + rng.gauss(0, 0.01) for _ in range(1200)]
    ys = [f.filter(x, i * DT) for i, x in enumerate(xs)]
    ys = ys[300:]
    xs = xs[300:]
    assert statistics.pstdev(ys) < statistics.pstdev(xs) * 0.4
    assert abs(statistics.mean(ys) - 5.0) < 0.002


def test_beta_makes_it_follow_fast_motion():
    """Contrasto: con beta la rampa veloce viene seguita con meno ritardo che senza."""
    slow, fast = OneEuro(1.0, beta=0.0), OneEuro(1.0, beta=1.0)
    lag_slow = lag_fast = 0.0
    for i in range(300):
        t = i * DT
        x = 2.0 * t  # 2 m/s
        lag_slow = x - slow.filter(x, t)
        lag_fast = x - fast.filter(x, t)
    assert lag_fast < lag_slow * 0.5


def test_irregular_dt_and_duplicates_never_nan():
    f = OneEuro()
    t = 0.0
    rng = random.Random(1)
    for _ in range(500):
        t += rng.choice([DT, DT, DT, 0.0, 5 * DT])  # duplicati e buchi
        y = f.filter(math.sin(t), t)
        assert math.isfinite(y)


def test_vec3_filters_each_channel():
    f = OneEuroVec3()
    out = f.filter((1.0, 2.0, 3.0), 0.0)
    assert out == (1.0, 2.0, 3.0)


def test_quat_constant_and_hemisphere():
    q = quat_from_axis_angle(Y, math.radians(30))
    neg = (-q[0], -q[1], -q[2], -q[3])
    f = OneEuroQuat()
    f.filter(q, 0.0)
    for i in range(1, 50):
        out = f.filter(neg if i % 2 else q, i * DT)  # stessa rotazione, segno alterno
        assert quat_angle(out, q) < 1e-9


def test_quat_step_converges():
    a = quat_from_axis_angle(Y, 0.0)
    b = quat_from_axis_angle(Y, math.radians(40))
    f = OneEuroQuat(min_cutoff=1.0, beta=0.0)
    f.filter(a, 0.0)
    angles = [math.degrees(quat_angle(f.filter(b, i * DT), b)) for i in range(1, 300)]
    assert all(y <= x + 1e-6 for x, y in pairwise(angles))
    assert angles[-1] < 0.5


def test_bad_parameters_rejected():
    with pytest.raises(ValueError):
        OneEuro(min_cutoff=0.0)
    with pytest.raises(ValueError):
        OneEuroQuat(beta=-1.0)
