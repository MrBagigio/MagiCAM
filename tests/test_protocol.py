"""protocol: roundtrip, vettori noti condivisi con Swift (F2.2), rifiuti tipizzati."""

import contextlib
import math
import struct

import pytest

from magicam import protocol
from magicam.protocol import (
    COMMAND_SIZE,
    POSE_SIZE,
    STATS_SIZE,
    Command,
    CommandMessage,
    PoseMessage,
    ProtocolError,
    StatsMessage,
    TrackingReason,
    TrackingState,
)

# Vettore noto, scritto a mano dalla specifica (docs/PROTOCOL.md): l'encoder Swift deve produrre questi byte.
# header: 'MGC2', version 2, type 1, seq 7, t_sensor 1.5
# pose:   normal/none, pos (0.1, 0.2, 0.3), quat (0,0,0,1), focal 1000, 1920x1080, ev 0
VETTORI_NOTI = {
    "pose": bytes.fromhex(
        "4d474332"
        "0200"
        "0100"
        "07000000"
        "000000000000f83f"
        "00"
        "00"
        "cdcccc3d"
        "cdcc4c3e"
        "9a99993e"
        "00000000"
        "00000000"
        "00000000"
        "0000803f"
        "00007a44"
        "8007"
        "3804"
        "00000000"
    ),
    # seq 3, t 2.0; cmd scale_set(7); token 0xDEADBEEF; value 0.1
    "command": bytes.fromhex("4d474332020002000300000000000000000000400700efbeaddecdcccc3d"),
    # seq 1, t 3.0; received 600; lost 12; latency 18.5; flags 0b1011
    "stats": bytes.fromhex("4d47433202000300010000000000000000000840580200000c000000000094410b"),
}


def pose(seq: int = 7) -> PoseMessage:
    return PoseMessage(
        seq,
        1.5,
        TrackingState.NORMAL,
        TrackingReason.NONE,
        (0.1, 0.2, 0.3),
        (0.0, 0.0, 0.0, 1.0),
        1000.0,
        1920,
        1080,
    )


def test_sizes():
    assert POSE_SIZE == 62
    assert COMMAND_SIZE == 30
    assert STATS_SIZE == 33


def test_pose_matches_known_vector():
    assert protocol.pack(pose()) == VETTORI_NOTI["pose"]


def test_pose_roundtrip_f32_precision():
    m = pose()
    back = protocol.unpack(protocol.pack(m))
    assert isinstance(back, PoseMessage)
    assert back.seq == 7 and back.t_sensor == 1.5
    assert back.tracking_state is TrackingState.NORMAL
    for a, b in zip(back.pos, m.pos, strict=True):
        assert abs(a - b) < 1e-7  # f32
    assert back.quat == (0.0, 0.0, 0.0, 1.0)
    assert back.image_w == 1920 and back.image_h == 1080
    assert back.focal_px == 1000.0


def test_command_roundtrip():
    m = CommandMessage(3, 2.0, Command.SCALE_SET, token=0xDEADBEEF, value=0.1)
    assert protocol.pack(m) == VETTORI_NOTI["command"]
    back = protocol.unpack(protocol.pack(m))
    assert isinstance(back, CommandMessage)
    assert back.cmd is Command.SCALE_SET and back.token == 0xDEADBEEF
    assert abs(back.value - 0.1) < 1e-7


def test_stats_roundtrip():
    m = StatsMessage(1, 3.0, received=600, lost=12, latency_ms=18.5, flags=0b1011)
    assert protocol.pack(m) == VETTORI_NOTI["stats"]
    back = protocol.unpack(protocol.pack(m))
    assert isinstance(back, StatsMessage)
    assert (back.received, back.lost, back.flags) == (600, 12, 0b1011)
    assert abs(back.latency_ms - 18.5) < 1e-5


@pytest.mark.parametrize(
    "mutate, campo",
    [
        (lambda b: b"XXXX" + b[4:], "magic"),
        (lambda b: b[:4] + struct.pack("<H", 1) + b[6:], "version"),
        (lambda b: b[:6] + struct.pack("<H", 9) + b[8:], "type"),
        (lambda b: b[:-1], "byte"),
        (lambda b: b + b"\0", "byte"),
        (lambda b: b[:10], "header"),
    ],
)
def test_rejects_malformed(mutate, campo):
    with pytest.raises(ProtocolError, match=campo):
        protocol.unpack(mutate(protocol.pack(pose())))


def test_rejects_nan_and_non_unit_quat():
    nan = PoseMessage(1, 0.0, TrackingState.NORMAL, TrackingReason.NONE, (math.nan, 0, 0), (0, 0, 0, 1))
    with pytest.raises(ProtocolError, match="pos"):
        protocol.unpack(protocol.pack(nan))
    bad_q = PoseMessage(1, 0.0, TrackingState.NORMAL, TrackingReason.NONE, (0, 0, 0), (0, 0, 0, 0.5))
    with pytest.raises(ProtocolError, match="quat"):
        protocol.unpack(protocol.pack(bad_q))


def test_rejects_unknown_tracking_state():
    raw = bytearray(protocol.pack(pose()))
    raw[20] = 7
    with pytest.raises(ProtocolError, match="tracking"):
        protocol.unpack(bytes(raw))


def test_every_corrupted_byte_is_an_error_or_a_valid_message_never_a_crash():
    """Ogni singolo byte azzerato: o decodifica (campo legittimo) o ProtocolError; mai altra eccezione."""
    good = protocol.pack(pose())
    for i in range(len(good)):
        raw = bytearray(good)
        raw[i] = 0
        with contextlib.suppress(ProtocolError):
            protocol.unpack(bytes(raw))
