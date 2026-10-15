"""Quaternioni, trasformazioni rigide, ancora e scala. Python puro, nessun Maya.

CONVENZIONI (docs/CONVENZIONI.md): quaternione (x, y, z, w) unitario; la rotazione R(q) e' colonna-vettore
(v' = R v, colonne = assi locali nel mondo); Transform(pos, quat) porta coordinate locali nel mondo.
La lista per `cmds.xform(matrix=...)` e' riga-vettore (righe = assi, traslazione in 12-14): la produce SOLO
`to_maya_matrix`, e la sua convenzione e' DICHIARATA, da misurare in Maya (F1.1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]

QUAT_IDENTITY: Quat = (0.0, 0.0, 0.0, 1.0)
VEC3_ZERO: Vec3 = (0.0, 0.0, 0.0)


# --- quaternioni -----------------------------------------------------------------------------------------------


def quat_normalize(q: Quat) -> Quat:
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0.0:
        raise ValueError("quaternione nullo")
    return (x / n, y / n, z / n, w / n)


def quat_conj(q: Quat) -> Quat:
    x, y, z, w = q
    return (-x, -y, -z, w)


def quat_mul(a: Quat, b: Quat) -> Quat:
    """a*b: prima b poi a (come le matrici)."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    """v' = q v q*."""
    x, y, z, w = q
    vx, vy, vz = v
    # t = 2 * cross(q.xyz, v)
    tx = 2.0 * (y * vz - z * vy)
    ty = 2.0 * (z * vx - x * vz)
    tz = 2.0 * (x * vy - y * vx)
    # v' = v + w*t + cross(q.xyz, t)
    return (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )


def quat_from_axis_angle(axis: Vec3, angle_rad: float) -> Quat:
    ax, ay, az = axis
    n = math.sqrt(ax * ax + ay * ay + az * az)
    if n == 0.0:
        raise ValueError("asse nullo")
    s = math.sin(angle_rad / 2.0) / n
    return (ax * s, ay * s, az * s, math.cos(angle_rad / 2.0))


def quat_to_mat3(q: Quat) -> Mat3:
    """R(q) colonna-vettore: R[i][j], colonne = assi."""
    x, y, z, w = q
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)),
        (2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)),
        (2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)),
    )


def mat3_to_quat(m: Mat3) -> Quat:
    """Inversa di quat_to_mat3 (Shepperd), per matrici di rotazione proprie."""
    (m00, m01, m02), (m10, m11, m12), (m20, m21, m22) = m
    tr = m00 + m11 + m22
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        return quat_normalize(((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s))
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return quat_normalize((0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s))
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return quat_normalize(((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s))
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return quat_normalize(((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s))


def quat_dot(a: Quat, b: Quat) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def quat_angle(a: Quat, b: Quat) -> float:
    """Angolo (rad) della rotazione che porta a in b, in [0, pi]. Ben condizionato anche vicino a zero
    (atan2 sulla differenza, non acos del prodotto scalare: acos perde 8 cifre vicino a 1)."""
    x, y, z, w = quat_mul(quat_conj(a), b)
    return 2.0 * math.atan2(math.sqrt(x * x + y * y + z * z), abs(w))


def quat_slerp(a: Quat, b: Quat, t: float) -> Quat:
    d = quat_dot(a, b)
    if d < 0.0:
        b = (-b[0], -b[1], -b[2], -b[3])
        d = -d
    if d > 0.9995:
        return quat_normalize(
            (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2]), a[3] + t * (b[3] - a[3]))
        )
    theta0 = math.acos(d)
    theta = theta0 * t
    s0 = math.cos(theta) - d * math.sin(theta) / math.sin(theta0)
    s1 = math.sin(theta) / math.sin(theta0)
    return (s0 * a[0] + s1 * b[0], s0 * a[1] + s1 * b[1], s0 * a[2] + s1 * b[2], s0 * a[3] + s1 * b[3])


def quat_to_euler_xyz_deg(q: Quat) -> Vec3:
    """Euler XYZ (ordine di rotazione di Maya, `rotateOrder = xyz`), in gradi. Solo per la UI e i test."""
    (m00, _, _), (m10, m11, m12), (m20, m21, m22) = quat_to_mat3(q)
    # R = Rz * Ry * Rx (rotateOrder xyz di Maya: prima X, poi Y, poi Z, estrinseche)
    sy = -m20
    if abs(sy) < 1.0 - 1e-12:
        ry = math.asin(sy)
        rx = math.atan2(m21, m22)
        rz = math.atan2(m10, m00)
    else:  # gimbal: ry = ±90
        ry = math.copysign(math.pi / 2, sy)
        rx = math.atan2(-m12, m11)
        rz = 0.0
    return (math.degrees(rx), math.degrees(ry), math.degrees(rz))


# --- trasformazioni --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Transform:
    """Posa di un telaio nel mondo: x_world = R(quat) x_local + pos. Unita' di pos: metri."""

    pos: Vec3 = VEC3_ZERO
    quat: Quat = QUAT_IDENTITY

    def compose(self, other: Transform) -> Transform:
        """self ∘ other: prima other, poi self."""
        return Transform(
            pos=vec_add(quat_rotate(self.quat, other.pos), self.pos),
            quat=quat_normalize(quat_mul(self.quat, other.quat)),
        )

    def inverse(self) -> Transform:
        qi = quat_conj(self.quat)
        p = quat_rotate(qi, self.pos)
        return Transform(pos=(-p[0], -p[1], -p[2]), quat=qi)

    def scaled_pos(self, k: float) -> Transform:
        return replace(self, pos=vec_scale(self.pos, k))

    def with_pos(self, pos: Vec3) -> Transform:
        return replace(self, pos=pos)

    def with_quat(self, quat: Quat) -> Transform:
        return replace(self, quat=quat_normalize(quat))


def vec_add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vec_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vec_scale(a: Vec3, k: float) -> Vec3:
    return (a[0] * k, a[1] * k, a[2] * k)


def vec_norm(a: Vec3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def vec_lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


# --- ancora e scala: il cuore --------------------------------------------------------------------------------------


def relative_motion(calib: Transform, phone: Transform) -> Transform:
    """Moto del telefono rispetto alla posa in cui ha calibrato: calib⁻¹ ∘ phone (nel telaio del telefono calibrato)."""
    return calib.inverse().compose(phone)


def apply_anchor(anchor: Transform, scale: float, calib: Transform, phone: Transform) -> Transform:
    """Posa della camera: anchor ∘ (scale · (calib⁻¹ ∘ phone)).

    anchor = camera di Maya al momento della calibrazione (metri); scale agisce sul moto RELATIVO, attorno
    all'ancora (scala 0.1 = il telefono si muove 10 cm, la camera 1 cm; a telefono fermo la camera e' sull'ancora).
    Risposte note in docs/CONVENZIONI.md e tests/test_math3d.py.
    """
    if scale <= 0.0 or math.isnan(scale) or math.isinf(scale):
        raise ValueError(f"scale deve essere > 0, finito: {scale!r}")
    return anchor.compose(relative_motion(calib, phone).scaled_pos(scale))


# --- Maya ------------------------------------------------------------------------------------------------------------


def to_maya_matrix(t: Transform, unit_per_meter: float = 100.0) -> list[float]:
    """Lista di 16 per `cmds.xform(ws=True, matrix=...)`: riga-vettore, righe = assi, traslazione in 12-14.

    DICHIARATA, NON MISURATA (F1.1): se la misura in Maya dovesse smentirla, si cambia qui e in nessun altro posto.
    """
    r = quat_to_mat3(t.quat)
    px, py, pz = vec_scale(t.pos, unit_per_meter)
    return [
        r[0][0], r[1][0], r[2][0], 0.0,  # asse X locale (colonna 0 di R) -> riga 0
        r[0][1], r[1][1], r[2][1], 0.0,  # asse Y
        r[0][2], r[1][2], r[2][2], 0.0,  # asse Z
        px, py, pz, 1.0,
    ]  # fmt: skip


def from_maya_matrix(m: list[float], unit_per_meter: float = 100.0) -> Transform:
    """Inversa di to_maya_matrix (ignora scala/taglio: prende gli assi normalizzati)."""
    if len(m) != 16:
        raise ValueError(f"servono 16 valori, trovati {len(m)}")
    ax = _normalized((m[0], m[1], m[2]))
    ay = _normalized((m[4], m[5], m[6]))
    az = _normalized((m[8], m[9], m[10]))
    # colonne di R = assi
    rot: Mat3 = ((ax[0], ay[0], az[0]), (ax[1], ay[1], az[1]), (ax[2], ay[2], az[2]))
    pos = (m[12] / unit_per_meter, m[13] / unit_per_meter, m[14] / unit_per_meter)
    return Transform(pos=pos, quat=mat3_to_quat(rot))


def _normalized(v: Vec3) -> Vec3:
    n = vec_norm(v)
    if n == 0.0:
        raise ValueError("asse nullo nella matrice")
    return (v[0] / n, v[1] / n, v[2] / n)
