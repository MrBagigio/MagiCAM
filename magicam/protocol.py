"""Datagrammi MagiCAM v2: pack/unpack binario, little-endian. Specifica in docs/PROTOCOL.md.

Ogni cosa che non torna (magic, versione, lunghezza, NaN, quaternione non unitario) e' un `ProtocolError`
tipizzato: chi riceve lo conta, mai lo ingoia.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from enum import IntEnum

from magicam import PROTOCOL_VERSION

MAGIC = b"MGC2"

_HEADER = struct.Struct("<4sHHId")  # magic, version, type, seq, t_sensor
_POSE = struct.Struct("<BB3f4ffHHf")  # state, reason, pos, quat, focal_px, w, h, exposure
_COMMAND = struct.Struct("<HIf")  # cmd, token, value
_STATS = struct.Struct("<IIfB")  # received, lost, latency_ms, flags

HEADER_SIZE = _HEADER.size  # 20
POSE_SIZE = HEADER_SIZE + _POSE.size  # 62
COMMAND_SIZE = HEADER_SIZE + _COMMAND.size  # 30
STATS_SIZE = HEADER_SIZE + _STATS.size  # 33

QUAT_NORM_TOLERANCE = 0.01


class ProtocolError(ValueError):
    """Datagramma che non rispetta docs/PROTOCOL.md. Il messaggio dice quale campo."""


class MessageType(IntEnum):
    POSE = 1
    COMMAND = 2
    STATS = 3


class TrackingState(IntEnum):
    NORMAL = 0
    LIMITED = 1
    NOT_AVAILABLE = 2


class TrackingReason(IntEnum):
    NONE = 0
    INITIALIZING = 1
    RELOCALIZING = 2
    EXCESSIVE_MOTION = 3
    INSUFFICIENT_FEATURES = 4


class Command(IntEnum):
    CALIBRATE = 1
    RECENTER = 2
    FREEZE = 3
    UNFREEZE = 4
    REC_START = 5
    REC_STOP = 6
    SCALE_SET = 7
    PING = 8


class StatsFlag(IntEnum):
    CALIBRATED = 1
    FROZEN = 2
    RECORDING = 4
    TRACKING_BAD = 8


@dataclass(frozen=True, slots=True)
class PoseMessage:
    seq: int
    t_sensor: float
    tracking_state: TrackingState
    tracking_reason: TrackingReason
    pos: tuple[float, float, float]
    quat: tuple[float, float, float, float]  # x, y, z, w
    focal_px: float = 0.0
    image_w: int = 0
    image_h: int = 0
    exposure_offset: float = 0.0

    @property
    def tracking_ok(self) -> bool:
        return self.tracking_state is TrackingState.NORMAL


@dataclass(frozen=True, slots=True)
class CommandMessage:
    seq: int
    t_sensor: float
    cmd: Command
    token: int = 0
    value: float = 0.0


@dataclass(frozen=True, slots=True)
class StatsMessage:
    seq: int
    t_sensor: float
    received: int
    lost: int
    latency_ms: float
    flags: int = 0


Message = PoseMessage | CommandMessage | StatsMessage


def _header(msg_type: MessageType, seq: int, t_sensor: float) -> bytes:
    return _HEADER.pack(MAGIC, PROTOCOL_VERSION, int(msg_type), seq & 0xFFFFFFFF, t_sensor)


def pack_pose(m: PoseMessage) -> bytes:
    return _header(MessageType.POSE, m.seq, m.t_sensor) + _POSE.pack(
        int(m.tracking_state),
        int(m.tracking_reason),
        *m.pos,
        *m.quat,
        m.focal_px,
        m.image_w,
        m.image_h,
        m.exposure_offset,
    )


def pack_command(m: CommandMessage) -> bytes:
    return _header(MessageType.COMMAND, m.seq, m.t_sensor) + _COMMAND.pack(int(m.cmd), m.token, m.value)


def pack_stats(m: StatsMessage) -> bytes:
    return _header(MessageType.STATS, m.seq, m.t_sensor) + _STATS.pack(m.received, m.lost, m.latency_ms, m.flags & 0xFF)


def pack(m: Message) -> bytes:
    if isinstance(m, PoseMessage):
        return pack_pose(m)
    if isinstance(m, CommandMessage):
        return pack_command(m)
    return pack_stats(m)


def _finite(name: str, *values: float) -> None:
    for v in values:
        if math.isnan(v) or math.isinf(v):
            raise ProtocolError(f"{name}: valore non finito {v!r}")


def unpack(data: bytes) -> Message:
    """Decodifica un datagramma. Solleva ProtocolError su qualunque scostamento dalla specifica."""
    if len(data) < HEADER_SIZE:
        raise ProtocolError(f"header: {len(data)} byte, servono {HEADER_SIZE}")
    magic, version, mtype, seq, t_sensor = _HEADER.unpack_from(data)
    if magic != MAGIC:
        raise ProtocolError(f"magic: {magic!r}")
    if version != PROTOCOL_VERSION:
        raise ProtocolError(f"version: {version}, attesa {PROTOCOL_VERSION}")
    _finite("t_sensor", t_sensor)

    if mtype == MessageType.POSE:
        if len(data) != POSE_SIZE:
            raise ProtocolError(f"pose: {len(data)} byte, attesi {POSE_SIZE}")
        state, reason, px, py, pz, qx, qy, qz, qw, focal, w, h, ev = _POSE.unpack_from(data, HEADER_SIZE)
        _finite("pos", px, py, pz)
        _finite("quat", qx, qy, qz, qw)
        _finite("focal_px", focal)
        _finite("exposure_offset", ev)
        norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
        if abs(norm - 1.0) > QUAT_NORM_TOLERANCE:
            raise ProtocolError(f"quat: norma {norm:.4f} fuori da 1±{QUAT_NORM_TOLERANCE}")
        try:
            tstate = TrackingState(state)
            treason = TrackingReason(reason)
        except ValueError as e:
            raise ProtocolError(f"tracking: {e}") from e
        return PoseMessage(seq, t_sensor, tstate, treason, (px, py, pz), (qx, qy, qz, qw), focal, w, h, ev)

    if mtype == MessageType.COMMAND:
        if len(data) != COMMAND_SIZE:
            raise ProtocolError(f"command: {len(data)} byte, attesi {COMMAND_SIZE}")
        cmd, token, value = _COMMAND.unpack_from(data, HEADER_SIZE)
        _finite("value", value)
        try:
            return CommandMessage(seq, t_sensor, Command(cmd), token, value)
        except ValueError as e:
            raise ProtocolError(f"cmd: {e}") from e

    if mtype == MessageType.STATS:
        if len(data) != STATS_SIZE:
            raise ProtocolError(f"stats: {len(data)} byte, attesi {STATS_SIZE}")
        received, lost, latency_ms, flags = _STATS.unpack_from(data, HEADER_SIZE)
        _finite("latency_ms", latency_ms)
        return StatsMessage(seq, t_sensor, received, lost, latency_ms, flags)

    raise ProtocolError(f"type: {mtype}")
