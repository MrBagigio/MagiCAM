"""simulator: prima di fidarsi dello strumento lo si prova su un caso di cui si sa la risposta (C1)."""

import math
from itertools import pairwise

import numpy as np

from magicam import protocol, simulator
from magicam.math3d import quat_angle
from magicam.protocol import PoseMessage, TrackingState
from magicam.simulator import SimulatorConfig, circle, generate


def test_circle_without_loss_is_reproduced_from_the_datagrams():
    cfg = SimulatorConfig(rate_hz=60.0, duration_s=4.0)
    traj = circle(radius_m=0.5, period_s=4.0)
    seqs = []
    for rec, data in generate(traj, cfg):
        assert rec.sent and data
        msg = protocol.unpack(data)
        assert isinstance(msg, PoseMessage)
        seqs.append(msg.seq)
        t_rel = msg.t_sensor - cfg.t0
        atteso = traj(t_rel)
        assert np.allclose(msg.pos, atteso.pos, atol=1e-6)  # f32
        assert quat_angle(msg.quat, atteso.quat) < 1e-6
        assert abs(math.hypot(msg.pos[0], msg.pos[2]) - 0.5) < 1e-6
    assert seqs == list(range(240))


def test_loss_and_reorder_are_exactly_what_the_records_say():
    cfg = SimulatorConfig(rate_hz=60.0, duration_s=10.0, loss=0.05, reorder=0.02, seed=7)
    recs = list(generate(simulator.still(), cfg))
    n = len(recs)
    assert n == 600
    lost = [r for r, d in recs if not r.sent]
    sent_seqs = [r.seq for r, d in recs if r.sent]
    assert 10 < len(lost) < 50  # ~5% di 600 = 30
    reordered = sum(1 for a, b in pairwise(sent_seqs) if b < a)
    assert 3 < reordered < 30  # ~2% di 600 = 12
    assert set(sent_seqs) | {r.seq for r in lost} == set(range(600))


def test_limited_window_marks_tracking():
    cfg = SimulatorConfig(rate_hz=10.0, duration_s=3.0, limited_from_s=1.0, limited_for_s=1.0)
    states = []
    for _rec, data in generate(simulator.still(), cfg):
        msg = protocol.unpack(data)
        assert isinstance(msg, PoseMessage)
        states.append(msg.tracking_state)
    assert states[:10] == [TrackingState.NORMAL] * 10
    assert states[10:20] == [TrackingState.LIMITED] * 10
    assert states[20:] == [TrackingState.NORMAL] * 10


def test_known_trajectories_exist():
    for name, make in simulator.TRAJECTORIES.items():
        t = make()(0.0)
        assert len(t.pos) == 3, name
