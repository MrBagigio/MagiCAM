"""receiver contro il simulatore in loopback: conteggi esatti, mai una posa vecchia, comandi e token."""

import socket
import time
from itertools import pairwise

import pytest

from magicam import protocol, simulator
from magicam.protocol import Command, CommandMessage, pack_command
from magicam.receiver import Receiver
from magicam.simulator import SimulatorConfig


def wait_until(pred, timeout=3.0):
    t_end = time.perf_counter() + timeout
    while time.perf_counter() < t_end:
        if pred():
            return True
        time.sleep(0.01)
    return pred()


@pytest.fixture
def receiver():
    r = Receiver(port=0, host="127.0.0.1")
    r.start()
    yield r
    r.stop()


def send_all(records_and_data, port, pace_s=0.0005):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _rec, data in records_and_data:
        if data:
            sock.sendto(data, ("127.0.0.1", port))
            if pace_s:
                time.sleep(pace_s)  # il kernel in loopback perde pacchetti a raffica piena: non e' il difetto cercato
    sock.close()


def test_counts_are_exact_with_loss_and_reorder(receiver):
    cfg = SimulatorConfig(rate_hz=60.0, duration_s=10.0, loss=0.05, reorder=0.02, seed=11)
    items = list(simulator.generate(simulator.circle(), cfg))
    never_sent = sum(1 for r, _ in items if not r.sent)
    sent_seqs = [r.seq for r, d in items if r.sent]
    reordered_expected = sum(1 for a, b in pairwise(sent_seqs) if b < a)
    send_all(items, receiver.port)

    st = receiver.stats
    assert wait_until(lambda: st.received + st.reordered == len(sent_seqs)), (st.received, st.reordered)
    assert st.reordered == reordered_expected
    assert st.lost == never_sent + reordered_expected  # il ritardato prima manca (buco) poi arriva (riordinato)
    assert st.rejected == 0
    latest = receiver.latest()
    assert latest is not None
    assert latest[0].seq == max(sent_seqs)  # mai una posa vecchia come «ultima»


def test_latest_never_goes_backwards(receiver):
    cfg = SimulatorConfig(rate_hz=60.0, duration_s=5.0, reorder=0.1, seed=3)
    items = list(simulator.generate(simulator.walk_forward(), cfg))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seen_max = -1
    for _rec, data in items:
        sock.sendto(data, ("127.0.0.1", receiver.port))
        time.sleep(0.0005)
        latest = receiver.latest()
        if latest is not None:
            assert latest[0].seq >= seen_max
            seen_max = latest[0].seq
    sock.close()


def test_rejected_garbage_is_counted_not_raised(receiver):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(b"ciao", ("127.0.0.1", receiver.port))
    sock.sendto(b"MGC2" + b"\0" * 58, ("127.0.0.1", receiver.port))
    sock.close()
    assert wait_until(lambda: receiver.stats.rejected == 2)
    assert receiver.latest() is None


def test_commands_reach_callback_and_token_is_enforced():
    got: list[CommandMessage] = []
    r = Receiver(port=0, host="127.0.0.1", on_command=lambda m, addr: got.append(m), expected_token=42)
    r.start()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(pack_command(CommandMessage(1, 0.0, Command.CALIBRATE, token=42)), ("127.0.0.1", r.port))
        sock.sendto(pack_command(CommandMessage(2, 0.0, Command.FREEZE, token=7)), ("127.0.0.1", r.port))
        sock.close()
        assert wait_until(lambda: r.stats.commands == 1 and r.stats.rejected == 1)
        assert got[0].cmd is Command.CALIBRATE
    finally:
        r.stop()


def test_stats_go_back_to_the_sender(receiver):
    phone = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    phone.bind(("127.0.0.1", 0))
    phone.settimeout(2.0)
    items = list(simulator.generate(simulator.still(), SimulatorConfig(rate_hz=10, duration_s=0.3)))
    for _rec, data in items:
        phone.sendto(data, ("127.0.0.1", receiver.port))
    assert wait_until(lambda: receiver.stats.received == 3)
    assert receiver.send_to_sender(protocol.pack_stats(protocol.StatsMessage(1, 0.0, 3, 0, 1.5, 0)))
    back = protocol.unpack(phone.recv(2048))
    assert isinstance(back, protocol.StatsMessage) and back.received == 3
    phone.close()


def test_stale_detection(receiver):
    assert receiver.stats.is_stale(time.perf_counter())
    items = list(simulator.generate(simulator.still(), SimulatorConfig(rate_hz=10, duration_s=0.1)))
    send_all(items, receiver.port)
    assert wait_until(lambda: receiver.stats.received == 1)
    assert not receiver.stats.is_stale(time.perf_counter())
    assert receiver.stats.is_stale(time.perf_counter() + 1.0)
