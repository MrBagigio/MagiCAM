"""F4.1: senza PING col token giusto le pose non muovono niente e si contano; l'abbinamento scade."""

import socket
import time

from magicam import protocol, simulator
from magicam.protocol import Command, CommandMessage, pack_command
from magicam.receiver import PAIR_TTL_S, Receiver
from magicam.simulator import SimulatorConfig


def wait_until(pred, timeout=3.0):
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


def poses(n: int):
    cfg = SimulatorConfig(rate_hz=60.0, duration_s=n / 60.0)
    return [d for _r, d in simulator.generate(simulator.still(), cfg)]


def test_unpaired_poses_are_dropped_and_counted_then_accepted_after_ping():
    r = Receiver(port=0, host="127.0.0.1", expected_token=123456)
    r.start()
    try:
        phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for d in poses(5):
            phone.sendto(d, ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.unpaired == 5)
        assert r.stats.received == 0 and r.latest() is None
        # PING col token sbagliato: rifiutato, ancora non abbinato
        phone.sendto(pack_command(CommandMessage(1, 0.0, Command.PING, token=1)), ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.rejected == 1)
        phone.sendto(poses(1)[0], ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.unpaired == 6)
        # PING col token giusto: abbinato, le pose passano
        phone.sendto(pack_command(CommandMessage(2, 0.0, Command.PING, token=123456)), ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.commands == 1)
        assert r.paired_senders() == [phone.getsockname()] or len(r.paired_senders()) == 1
        for d in poses(3):
            phone.sendto(d, ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.received == 3)
        assert r.latest() is not None
        phone.close()
    finally:
        r.stop()


def test_second_device_without_token_has_no_effect():
    r = Receiver(port=0, host="127.0.0.1", expected_token=42)
    r.start()
    try:
        good = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        bad = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        good.sendto(pack_command(CommandMessage(1, 0.0, Command.PING, token=42)), ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.commands == 1)
        cfg = SimulatorConfig(rate_hz=60.0, duration_s=0.5)
        far = [d for _r, d in simulator.generate(simulator.translate(5.0, 5.0, 5.0), cfg)]
        near = [d for _r, d in simulator.generate(simulator.still(), cfg)]
        for a, b in zip(near, far, strict=True):
            good.sendto(a, ("127.0.0.1", r.port))
            bad.sendto(b, ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.received == 30 and r.stats.unpaired == 30)
        latest = r.latest()
        assert latest is not None and latest[0].pos == (0.0, 0.0, 0.0)  # mai una posa dell'intruso
        assert r.last_sender() == good.getsockname() or r.last_sender()[1] == good.getsockname()[1]
        good.close()
        bad.close()
    finally:
        r.stop()


def test_pairing_expires_after_ttl_without_pings():
    r = Receiver(port=0, host="127.0.0.1", expected_token=7)
    r.start()
    try:
        phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        phone.sendto(pack_command(CommandMessage(1, 0.0, Command.PING, token=7)), ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.commands == 1)
        addr = phone.getsockname()
        now = time.perf_counter()
        assert r._is_paired(("127.0.0.1", addr[1]), now)
        assert not r._is_paired(("127.0.0.1", addr[1]), now + PAIR_TTL_S + 0.01)
        assert r.paired_senders(now + PAIR_TTL_S + 0.01) == []
        phone.close()
    finally:
        r.stop()


def test_without_expected_token_everything_is_accepted_as_before():
    r = Receiver(port=0, host="127.0.0.1")
    r.start()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        for d in poses(3):
            s.sendto(d, ("127.0.0.1", r.port))
        assert wait_until(lambda: r.stats.received == 3)
        assert r.stats.unpaired == 0
        assert r.send_to_sender(protocol.pack_stats(protocol.StatsMessage(1, 0.0, 3, 0, 0.0, 0)))
        s.close()
    finally:
        r.stop()
