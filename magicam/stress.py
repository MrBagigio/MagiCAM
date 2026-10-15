"""Stress fuori da Maya: receiver -> session -> recorder a 60 Hz, memoria e costo per posa misurati.

    python -m magicam.stress --duration 600          # 10 minuti, come F4.5 (la parte in Maya resta da fare)

Misura: pose accettate, perse/riordinate (loopback: attese 0), picco di memoria Python (tracemalloc) all'inizio e
alla fine, costo medio e massimo di `Session.update` + `TakeRecorder.add` per posa. Il tetto sulla crescita della
memoria e' in tests/test_stress.py, con la durata corta.
"""

from __future__ import annotations

import argparse
import sys
import time
import tracemalloc
from dataclasses import dataclass

from magicam import simulator
from magicam.math3d import Transform
from magicam.receiver import Receiver
from magicam.session import Session
from magicam.simulator import SimulatorConfig
from magicam.takes import TakeRecorder


@dataclass
class StressReport:
    duration_s: float
    sent: int
    received: int
    lost: int
    reordered: int
    updates: int
    mean_update_us: float
    max_update_us: float
    mem_start_kib: float
    mem_end_kib: float
    samples_recorded: int

    @property
    def mem_growth_kib(self) -> float:
        return self.mem_end_kib - self.mem_start_kib


def run(duration_s: float, rate_hz: float = 60.0, record: bool = True, realtime: bool = True) -> StressReport:
    tracemalloc.start()
    receiver = Receiver(port=0, host="127.0.0.1")
    receiver.start()
    session = Session()
    recorder = TakeRecorder()
    cfg = SimulatorConfig(rate_hz=rate_hz, duration_s=duration_s)
    traj = simulator.circle()
    try:
        # calibrazione: telefono all'origine, camera a 1.5 m d'altezza
        session.calibrate(traj(0.0), Transform(pos=(0.0, 1.5, 0.0)))
        if record:
            recorder.start("stress")
        # il "bridge": consuma l'ultima posa a ogni giro, come il tick di Maya
        import threading

        sender = threading.Thread(
            target=simulator.run,
            args=(traj, cfg, "127.0.0.1", receiver.port),
            kwargs={"realtime": realtime},
            daemon=True,
        )
        mem_start = tracemalloc.get_traced_memory()[0] / 1024.0
        costs: list[float] = []
        applied_seq = -1
        sender.start()
        t_end = time.perf_counter() + duration_s + 1.0
        while sender.is_alive() or time.perf_counter() < t_end:
            latest = receiver.latest()
            if latest is not None and latest[0].seq != applied_seq:
                msg = latest[0]
                applied_seq = msg.seq
                t0 = time.perf_counter()
                cam = session.update(msg)
                recorder.add(msg, cam)
                costs.append(time.perf_counter() - t0)
            elif not sender.is_alive():
                break
            else:
                time.sleep(0.001)
        mem_end = tracemalloc.get_traced_memory()[0] / 1024.0
        st = receiver.stats
        return StressReport(
            duration_s=duration_s,
            sent=round(rate_hz * duration_s),
            received=st.received,
            lost=st.lost,
            reordered=st.reordered,
            updates=len(costs),
            mean_update_us=(sum(costs) / len(costs) * 1e6) if costs else 0.0,
            max_update_us=(max(costs) * 1e6) if costs else 0.0,
            mem_start_kib=mem_start,
            mem_end_kib=mem_end,
            samples_recorded=recorder.sample_count,
        )
    finally:
        receiver.stop()
        tracemalloc.stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="MagiCAM: stress fuori da Maya")
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--rate", type=float, default=60.0)
    p.add_argument("--no-record", action="store_true")
    a = p.parse_args(argv)
    r = run(a.duration, a.rate, record=not a.no_record)
    print(
        f"{r.duration_s:.0f} s @ {a.rate:.0f} Hz: inviate {r.sent}, accettate {r.received}, perse {r.lost}, "
        f"riordinate {r.reordered}; update {r.updates} "
        f"(media {r.mean_update_us:.1f} us, max {r.max_update_us:.0f} us); "
        f"memoria {r.mem_start_kib:.0f} -> {r.mem_end_kib:.0f} KiB (+{r.mem_growth_kib:.0f}); "
        f"campioni registrati {r.samples_recorded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
