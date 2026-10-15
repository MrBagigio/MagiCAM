"""math3d: numpy come oracolo indipendente, risposte note scritte prima, killer rosso sulla convenzione del v1."""

import math
import random

import numpy as np
import pytest

from magicam import math3d as m3
from magicam.math3d import Transform, apply_anchor, quat_from_axis_angle

X, Y, Z = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
TOL = 1e-9


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def random_quat(rng: random.Random) -> m3.Quat:
    q = (rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))
    return m3.quat_normalize(q)


def angle_axis_deg(q: m3.Quat):
    x, y, z, w = q if q[3] >= 0 else (-q[0], -q[1], -q[2], -q[3])
    ang = 2 * math.degrees(math.acos(min(1.0, w)))
    n = math.sqrt(x * x + y * y + z * z)
    axis = (x / n, y / n, z / n) if n > 1e-12 else (0.0, 0.0, 0.0)
    return ang, axis


# --- oracolo numpy -----------------------------------------------------------------------------------------------


def test_quat_to_mat3_against_known_rotations():
    assert np.allclose(np.array(m3.quat_to_mat3(quat_from_axis_angle(Y, math.radians(20)))), rot_y(20), atol=TOL)
    assert np.allclose(np.array(m3.quat_to_mat3(quat_from_axis_angle(X, math.radians(20)))), rot_x(20), atol=TOL)


def test_quat_mul_matches_matrix_product():
    rng = random.Random(1)
    for _ in range(200):
        a, b = random_quat(rng), random_quat(rng)
        ra, rb = np.array(m3.quat_to_mat3(a)), np.array(m3.quat_to_mat3(b))
        assert np.allclose(np.array(m3.quat_to_mat3(m3.quat_mul(a, b))), ra @ rb, atol=1e-9)


def test_quat_rotate_matches_matrix():
    rng = random.Random(2)
    for _ in range(200):
        q = random_quat(rng)
        v = (rng.uniform(-5, 5), rng.uniform(-5, 5), rng.uniform(-5, 5))
        assert np.allclose(m3.quat_rotate(q, v), np.array(m3.quat_to_mat3(q)) @ np.array(v), atol=1e-9)


def test_mat3_quat_roundtrip_all_branches():
    rng = random.Random(3)
    for _ in range(500):
        q = random_quat(rng)
        back = m3.mat3_to_quat(m3.quat_to_mat3(q))
        assert abs(abs(m3.quat_dot(q, back)) - 1.0) < 1e-9


def test_compose_and_inverse_against_numpy_4x4():
    rng = random.Random(4)

    def to44(t: Transform) -> np.ndarray:
        m = np.eye(4)
        m[:3, :3] = np.array(m3.quat_to_mat3(t.quat))
        m[:3, 3] = t.pos
        return m

    for _ in range(100):
        a = Transform((rng.uniform(-3, 3),) * 3, random_quat(rng))
        b = Transform((rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3)), random_quat(rng))
        assert np.allclose(to44(a.compose(b)), to44(a) @ to44(b), atol=1e-9)
        assert np.allclose(to44(a.inverse()), np.linalg.inv(to44(a)), atol=1e-9)


def test_slerp_endpoints_and_midpoint():
    a = quat_from_axis_angle(Y, 0.0)
    b = quat_from_axis_angle(Y, math.radians(90))
    assert m3.quat_angle(m3.quat_slerp(a, b, 0.0), a) < TOL
    assert m3.quat_angle(m3.quat_slerp(a, b, 1.0), b) < TOL
    mid = m3.quat_slerp(a, b, 0.5)
    assert abs(math.degrees(m3.quat_angle(a, mid)) - 45.0) < 1e-9


def test_euler_xyz_known():
    rx, ry, rz = m3.quat_to_euler_xyz_deg(quat_from_axis_angle(Y, math.radians(20)))
    assert (abs(rx), abs(ry - 20), abs(rz)) < (1e-9, 1e-9, 1e-9)


# --- ancora e scala: risposte note scritte PRIMA (docs/CONVENZIONI.md) ---------------------------------------------

IDENT = Transform()
Y20 = Transform(quat=quat_from_axis_angle(Y, math.radians(20)))
X20 = Transform(quat=quat_from_axis_angle(X, math.radians(20)))
ANCHOR_F = Transform(pos=(5.0, 1.5, 0.0), quat=quat_from_axis_angle(Y, math.radians(90)))

CASI_NOTI = [
    # (nome, calib, anchor, scale, phone, camera attesa)
    ("fermo", IDENT, IDENT, 1.0, IDENT, IDENT),
    ("yaw +20 = camera yaw +20", IDENT, IDENT, 1.0, Y20, Y20),
    ("pitch +20 = camera pitch +20", IDENT, IDENT, 1.0, X20, X20),
    ("10 cm a destra", IDENT, IDENT, 1.0, Transform(pos=(0.1, 0, 0)), Transform(pos=(0.1, 0, 0))),
    ("10 cm avanti (-Z)", IDENT, IDENT, 1.0, Transform(pos=(0, 0, -0.1)), Transform(pos=(0, 0, -0.1))),
    (
        "ancora fuori origine, girata 90: avanti 10 cm",
        IDENT,
        ANCHOR_F,
        1.0,
        Transform(pos=(0, 0, -0.1)),
        Transform(pos=(4.9, 1.5, 0.0), quat=ANCHOR_F.quat),
    ),
    ("scala 0.1: 10 cm -> 1 cm", IDENT, IDENT, 0.1, Transform(pos=(0.1, 0, 0)), Transform(pos=(0.01, 0, 0))),
    (
        "calib non identita': il moto e' relativo",
        Transform(pos=(2.0, 0.0, 3.0), quat=quat_from_axis_angle(Y, math.radians(45))),
        IDENT,
        1.0,
        Transform(pos=(2.0, 0.0, 3.0), quat=quat_from_axis_angle(Y, math.radians(65))),
        Y20,
    ),
]


@pytest.mark.parametrize("nome, calib, anchor, scale, phone, atteso", CASI_NOTI, ids=[c[0] for c in CASI_NOTI])
def test_apply_anchor_known_answers(nome, calib, anchor, scale, phone, atteso):
    cam = apply_anchor(anchor, scale, calib, phone)
    assert np.allclose(cam.pos, atteso.pos, atol=TOL), (nome, cam.pos)
    assert m3.quat_angle(cam.quat, atteso.quat) < 1e-9, (nome, angle_axis_deg(cam.quat))


def test_scale_keeps_anchor_when_phone_still():
    cam = apply_anchor(ANCHOR_F, 0.1, IDENT, IDENT)
    assert np.allclose(cam.pos, ANCHOR_F.pos, atol=TOL)


def test_apply_anchor_rejects_bad_scale():
    for s in (0.0, -1.0, math.nan, math.inf):
        with pytest.raises(ValueError):
            apply_anchor(IDENT, s, IDENT, IDENT)


# --- la lista per Maya ---------------------------------------------------------------------------------------------


def test_to_maya_matrix_layout_declared():
    """Righe = assi, traslazione in 12-14, cm. DICHIARATO (F1.1 lo misura in Maya)."""
    t = Transform(pos=(1.0, 2.0, 3.0), quat=quat_from_axis_angle(Y, math.radians(20)))
    m = m3.to_maya_matrix(t, 100.0)
    assert m[12:15] == pytest.approx([100.0, 200.0, 300.0])
    assert m[3] == 0.0 and m[7] == 0.0 and m[11] == 0.0 and m[15] == 1.0
    r = rot_y(20)
    assert np.allclose(m[0:3], r[:, 0])  # riga 0 = asse X locale = colonna 0 di R
    assert np.allclose(m[8:11], r[:, 2])


def test_maya_matrix_roundtrip():
    rng = random.Random(5)
    for _ in range(100):
        t = Transform((rng.uniform(-3, 3), rng.uniform(-3, 3), rng.uniform(-3, 3)), random_quat(rng))
        back = m3.from_maya_matrix(m3.to_maya_matrix(t, 100.0), 100.0)
        assert np.allclose(back.pos, t.pos, atol=1e-9)
        assert m3.quat_angle(back.quat, t.quat) < 1e-9


def test_from_maya_matrix_rejects_bad_length():
    with pytest.raises(ValueError):
        m3.from_maya_matrix([0.0] * 15)


# --- killer rosso: la pipeline del v1 fallisce la risposta nota «yaw +20 -> yaw +20» ---------------------------------


def v1_pipeline(phone_r: np.ndarray, phone_t_m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Riproduce legacy: Swift riga-maggiore con traslazione in 3,7,11, flip Z e X, calib a identita',
    Maya che legge la lista come riga-vettore (R = blocco trasposto, t dagli indici 3,7,11)."""
    L = np.eye(4)  # noqa: N806
    L[:3, :3] = phone_r
    L[:3, 3] = phone_t_m * 100.0
    D = np.diag([-1.0, 1.0, -1.0, 1.0])  # noqa: N806 - reflect_z * reflect_x
    # calibrazione del v1 a telefono fermo: CALIB = desired * inv(D) = D (desired = IDENT); poi final = CALIB * L * D
    final = D @ L @ D
    return final[:3, :3].T, np.array([final[0, 3], final[1, 3], final[2, 3]])


def test_killer_v1_inverts_yaw_and_translation():
    """Il test della risposta nota DEVE fallire sul v1: altrimenti non distingue (C1)."""
    r_cam, _ = v1_pipeline(rot_y(20), np.zeros(3))
    assert not np.allclose(r_cam, rot_y(20), atol=1e-6)
    assert np.allclose(r_cam, rot_y(-20), atol=1e-6)  # yaw invertito, come misurato in sim_magicam.py
    _, t_cam = v1_pipeline(np.eye(3), np.array([0.1, 0, 0]))
    assert np.allclose(t_cam, [-10.0, 0, 0], atol=1e-6)  # destra -> sinistra
    _, t_cam = v1_pipeline(np.eye(3), np.array([0, 0, -0.1]))
    assert np.allclose(t_cam, [0, 0, 10.0], atol=1e-6)  # avanti -> indietro


def test_v2_passes_where_v1_fails():
    cam = apply_anchor(IDENT, 1.0, IDENT, Y20)
    assert np.allclose(np.array(m3.quat_to_mat3(cam.quat)), rot_y(20), atol=TOL)
