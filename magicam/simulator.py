"""Telefono finto: traiettorie di cui si conosce la risposta, perdita e riordino a comando.

E' lo strumento con cui si provano receiver, session e bridge senza iPhone. Prima di fidarsi dello strumento lo si
passa su un caso di cui si sa l'esito (tests/test_simulator.py).

Uso:  python -m magicam.simulator --host 127.0.0.1 --port 9000 --traj circle --rate 60 --duration 10
"""

from __future__ import annotations

import argparse
import math
import random
import socket
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from magicam.math3d import Transform, quat_from_axis_angle
from magicam.protocol import PoseMessage, TrackingReason, TrackingState, pack_pose

Trajectory = Callable[[float], Transform]  # t (s) -> posa del telefono nel mondo ARKit (metri)

X: tuple[float, float, float] = (1.0, 0.0, 0.0)
Y: tuple[float, float, float] = (0.0, 1.0, 0.0)
Z: tuple[float, float, float] = (0.0, 0.0, 1.0)


def still() -> Trajectory:
    return lambda t: Transform()


def yaw(deg: float) -> Trajectory:
    q = quat_from_axis_angle(Y, math.radians(deg))
    return lambda t: Transform(quat=q)


def pitch(deg: float) -> Trajectory:
    q = quat_from_axis_angle(X, math.radians(deg))
    return lambda t: Transform(quat=q)


def translate(x: float, y: float, z: float) -> Trajectory:
    return lambda t: Transform(pos=(x, y, z))


def circle(radius_m: float = 0.5, period_s: float = 4.0) -> Trajectory:
    """Cerchio nel piano XZ attorno all'origine, telefono che guarda sempre il centro."""

    def f(t: float) -> Transform:
        a = 2.0 * math.pi * t / period_s
        pos = (radius_m * math.sin(a), 0.0, radius_m * math.cos(a))
        # guarda il centro: −Z locale verso l'origine -> yaw = a (a t=0 il telefono a +Z guarda −Z)
        return Transform(pos=pos, quat=quat_from_axis_angle(Y, a))

    return f


def walk_forward(speed_m_s: float = 0.5) -> Trajectory:
    return lambda t: Transform(pos=(0.0, 0.0, -speed_m_s * t))


TRAJECTORIES: dict[str, Callable[[], Trajectory]] = {
    "still": still,
    "yaw20": lambda: yaw(20.0),
    "pitch20": lambda: pitch(20.0),
    "right10cm": lambda: translate(0.10, 0.0, 0.0),
    "forward10cm": lambda: translate(0.0, 0.0, -0.10),
    "circle": circle,
    "walk": walk_forward,
}


@dataclass
class SimulatorConfig:
    rate_hz: float = 60.0
    duration_s: float = 10.0
    loss: float = 0.0  # frazione di pacchetti non inviati
    reorder: float = 0.0  # frazione di pacchetti ritardati di un posto
    limited_from_s: float | None = None  # da quando (s) il tracking e' «limited»
    limited_for_s: float = 0.0
    seed: int | None = 0
    t0: float = 1000.0  # t_sensor di partenza (orologio monotono finto)


@dataclass
class SentRecord:
    seq: int
    t_sensor: float
    pose: Transform
    sent: bool


def generate(traj: Trajectory, cfg: SimulatorConfig) -> Iterator[tuple[SentRecord, bytes]]:
    """Produce (record, datagramma) nell'ordine di INVIO. record.sent=False = pacchetto perso (non prodotto)."""
    rng = random.Random(cfg.seed)
    n = round(cfg.rate_hz * cfg.duration_s)
    dt = 1.0 / cfg.rate_hz
    pending: tuple[SentRecord, bytes] | None = None
    for seq in range(n):
        t_rel = seq * dt
        pose = traj(t_rel)
        state = TrackingState.NORMAL
        reason = TrackingReason.NONE
        if cfg.limited_from_s is not None and cfg.limited_from_s <= t_rel < cfg.limited_from_s + cfg.limited_for_s:
            state, reason = TrackingState.LIMITED, TrackingReason.EXCESSIVE_MOTION
        msg = PoseMessage(seq, cfg.t0 + t_rel, state, reason, pose.pos, pose.quat)
        rec = SentRecord(seq, msg.t_sensor, pose, sent=True)
        if cfg.loss > 0.0 and rng.random() < cfg.loss:
            rec.sent = False
            yield rec, b""
            continue
        item = (rec, pack_pose(msg))
        if cfg.reorder > 0.0 and pending is None and rng.random() < cfg.reorder:
            pending = item  # lo mando dopo il prossimo
            continue
        yield item
        if pending is not None:
            yield pending
            pending = None
    if pending is not None:
        yield pending


def run(traj: Trajectory, cfg: SimulatorConfig, host: str, port: int, realtime: bool = True) -> list[SentRecord]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    records: list[SentRecord] = []
    start = time.monotonic()
    dt = 1.0 / cfg.rate_hz
    for rec, data in generate(traj, cfg):
        records.append(rec)
        if data:
            sock.sendto(data, (host, port))
        if realtime:
            target = start + (rec.seq + 1) * dt
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
    sock.close()
    return records


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MagiCAM: telefono finto")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--traj", choices=sorted(TRAJECTORIES), default="circle")
    p.add_argument("--rate", type=float, default=60.0)
    p.add_argument("--duration", type=float, default=10.0)
    p.add_argument("--loss", type=float, default=0.0)
    p.add_argument("--reorder", type=float, default=0.0)
    p.add_argument("--limited-from", type=float, default=None)
    p.add_argument("--limited-for", type=float, default=0.0)
    a = p.parse_args(argv)
    cfg = SimulatorConfig(a.rate, a.duration, a.loss, a.reorder, a.limited_from, a.limited_for)
    recs = run(TRAJECTORIES[a.traj](), cfg, a.host, a.port)
    sent = sum(1 for r in recs if r.sent)
    print(f"inviati {sent}/{len(recs)} pacchetti ({a.traj} @ {a.rate} Hz per {a.duration} s) a {a.host}:{a.port}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
