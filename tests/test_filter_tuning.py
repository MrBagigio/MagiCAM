"""F1.9 — taratura del One Euro sul simulatore. Atteso scritto PRIMA (docs/PIANO_DI_LAVORO.md F1.9):

- ritardo in posizione a 0,8 m/s (passo d'uomo con la camera in mano) <= 2 cm;
- ritardo in rotazione a 90 deg/s (panoramica decisa) <= 2 deg;
- rumore gaussiano di 2 mm a telefono fermo attenuato almeno 3x (rapporto fra deviazioni standard);
- rumore di 0,2 deg attenuato almeno 3x.
Coi default del paper (min_cutoff 1, beta 0.05) il ritardo a 0,8 m/s era ~12 cm (banco F1.8 del 2026-10-15).
"""

import math
import random
import statistics

from magicam.filters import DEFAULT_BETA, DEFAULT_MIN_CUTOFF, OneEuroQuat, OneEuroVec3
from magicam.math3d import quat_angle, quat_from_axis_angle

Y = (0.0, 1.0, 0.0)
HZ = 60.0


def test_position_lag_at_walking_speed_under_2cm():
    f = OneEuroVec3(DEFAULT_MIN_CUTOFF, DEFAULT_BETA)
    lag = 0.0
    for i in range(int(3 * HZ)):
        t = i / HZ
        x = 0.8 * t
        y = f.filter((x, 0.0, 0.0), t)
        lag = x - y[0]
    assert lag <= 0.02, lag


def test_rotation_lag_at_90deg_s_under_2deg():
    f = OneEuroQuat(DEFAULT_MIN_CUTOFF, DEFAULT_BETA)
    lag_deg = 0.0
    for i in range(int(2 * HZ)):
        t = i / HZ
        q = quat_from_axis_angle(Y, math.radians(90.0 * t))
        out = f.filter(q, t)
        lag_deg = math.degrees(quat_angle(out, q))
    assert lag_deg <= 2.0, lag_deg


def test_position_noise_2mm_attenuated_3x_at_rest():
    rng = random.Random(0)
    f = OneEuroVec3(DEFAULT_MIN_CUTOFF, DEFAULT_BETA)
    xs, ys = [], []
    for i in range(int(10 * HZ)):
        x = 1.0 + rng.gauss(0.0, 0.002)
        y = f.filter((x, 0.0, 0.0), i / HZ)[0]
        if i > 2 * HZ:
            xs.append(x)
            ys.append(y)
    ratio = statistics.pstdev(xs) / statistics.pstdev(ys)
    assert ratio >= 3.0, ratio


def test_rotation_noise_attenuated_3x_at_rest():
    rng = random.Random(1)
    f = OneEuroQuat(DEFAULT_MIN_CUTOFF, DEFAULT_BETA)
    base = quat_from_axis_angle(Y, math.radians(30.0))
    ins, outs = [], []
    for i in range(int(10 * HZ)):
        q = quat_from_axis_angle(Y, math.radians(30.0 + rng.gauss(0.0, 0.2)))
        out = f.filter(q, i / HZ)
        if i > 2 * HZ:
            ins.append(math.degrees(quat_angle(q, base)))
            outs.append(math.degrees(quat_angle(out, base)))
    ratio = statistics.pstdev(ins) / statistics.pstdev(outs)
    assert ratio >= 3.0, ratio
