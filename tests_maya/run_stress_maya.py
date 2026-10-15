"""F4.5 — stress di 10 minuti DENTRO il Maya aperto: simulatore 60 Hz dal PC, bridge in Maya, take per tutta la corsa,
campionamento ogni 10 s di CPU e memoria del PROCESSO Maya (PowerShell: nessuna dipendenza nuova).

  python tests_maya/run_stress_maya.py --duration 600

Atteso, scritto PRIMA:
- 36000/36000 pose accettate, 0 perse, 0 riordinate, 0 indietro; tutte passate a sessione e take;
- costo del tick: massimo < 16 ms su tutta la corsa (nessun tick che buchi un fotogramma a 60 Hz);
- memoria privata di Maya: crescita ≈ la take in memoria (36000 campioni × ~1 KiB ≈ 35-40 MB) + poco altro;
  dopo lo stop del bridge e lo scarto della take nessuna crescita ulteriore nel minuto seguente;
- CPU del processo Maya durante la corsa: dichiarata (non c'e' un tetto scritto: la misura decide), e torna al
  valore di riposo dopo lo stop;
- bake di 10 minuti a 24 fps: 14401 chiavi (floor(600·24)+1 ± 1 per la durata reale), 0 salti Euler.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import itertools

from mcp_gateway import Gateway
from run_bench_bridge import LIGHT, PRELUDE, REPO

PS_SAMPLE = (
    "Get-Process -Id {pid} | Select-Object -Property WorkingSet64,PrivateMemorySize64,"
    "@{{n='cpu_s';e={{$_.TotalProcessorTime.TotalSeconds}}}} | ConvertTo-Json -Compress"
)


def sample_process(pid: int) -> dict:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_SAMPLE.format(pid=pid)],
        capture_output=True,
        text=True,
        timeout=20,
    ).stdout
    d = json.loads(out)
    return {
        "t": time.perf_counter(),
        "ws_mb": d["WorkingSet64"] / 2**20,
        "private_mb": d["PrivateMemorySize64"] / 2**20,
        "cpu_s": float(d["cpu_s"]),
    }


class Sampler(threading.Thread):
    def __init__(self, pid: int, period_s: float) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.period_s = period_s
        self.samples: list[dict] = []
        self._halt = threading.Event()  # non `_stop`: e' un metodo interno di Thread

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                self.samples.append(sample_process(self.pid))
            except Exception as e:  # noqa: BLE001 - il campionatore riporta, non ferma la corsa
                self.samples.append({"t": time.perf_counter(), "error": str(e)})
            self._halt.wait(self.period_s)

    def stop(self) -> None:
        self._halt.set()


def cpu_percent(samples: list[dict]) -> list[float]:
    """% di UN core fra campioni consecutivi (TotalProcessorTime somma tutti i core)."""
    out = []
    good = [s for s in samples if "cpu_s" in s]
    for a, b in itertools.pairwise(good):
        dt = b["t"] - a["t"]
        if dt > 0:
            out.append(100.0 * (b["cpu_s"] - a["cpu_s"]) / dt)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--duration", type=float, default=600.0)
    p.add_argument("--rate", type=float, default=60.0)
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--sample-period", type=float, default=10.0)
    a = p.parse_args(argv)

    gw = Gateway()
    gw.start()
    pid = int(gw.py("import os; print(os.getpid())").strip().splitlines()[-1])
    out: dict = {"args": vars(a), "maya_pid": pid}

    # riposo PRIMA: 30 s di campioni senza bridge
    rest = Sampler(pid, 5.0)
    rest.start()
    time.sleep(30.0)
    rest.stop()
    rest.join()
    out["rest_before"] = {"samples": rest.samples, "cpu_pct": cpu_percent(rest.samples)}
    print("PARTIAL=" + json.dumps({"rest_before": out["rest_before"]}), flush=True)

    setup = gw.py_json(PRELUDE + f"print(bench_bridge.dumps(bench_bridge.setup(unit='cm', port={a.port})))", "BENCH")
    out["setup"] = setup
    sampler = Sampler(pid, a.sample_period)
    sampler.start()
    sim = subprocess.Popen(
        [
            sys.executable, "-m", "magicam.simulator",
            "--host", "127.0.0.1", "--port", str(setup["port"]), "--traj", "circle",
            "--rate", str(a.rate), "--duration", str(a.duration), "--clock", "host",
        ],
        cwd=str(REPO),
    )  # fmt: skip
    try:
        time.sleep(1.5)
        out["calibrate"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.calibrate()))", "BENCH")
        time.sleep(0.5)
        out["rec_start"] = gw.py_json(
            LIGHT + "print(bench_bridge.dumps(bench_bridge.rec_start('stress10min')))", "BENCH"
        )
        # ogni minuto un report intermedio: la coda e il costo del tick si guardano DURANTE, non solo alla fine
        out["progress"] = []
        t_end = time.perf_counter() + a.duration
        while time.perf_counter() < t_end - 5 and sim.poll() is None:
            time.sleep(60.0)
            r = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.report()))", "BENCH")
            out["progress"].append(
                {
                    k: r[k]
                    for k in (
                        "elapsed_s",
                        "receiver",
                        "tick",
                        "applied_seq_gaps",
                        "latency_ms",
                        "poses_through_session",
                    )
                }
            )
            print("minuto:", json.dumps(out["progress"][-1]["tick"]), json.dumps(out["progress"][-1]["receiver"]))
        sim.wait(timeout=60)
        time.sleep(0.5)
        out["rec_stop"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.rec_stop()))", "BENCH", 600)
        out["report"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.report()))", "BENCH")
        print("PARTIAL=" + json.dumps({"rec_stop": out["rec_stop"], "report": out["report"]}), flush=True)
        gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.stop_bridge()))", "BENCH")
        sampler.stop()
        sampler.join()
        out["during"] = {"samples": sampler.samples, "cpu_pct": cpu_percent(sampler.samples)}
        print("PARTIAL=" + json.dumps({"during": out["during"]}), flush=True)
        # memoria dopo lo stop (take ancora in memoria nel recorder? no: stop_take l'ha salvata e il recorder la tiene
        # finche' non si riavvia). Si scarta la take dal recorder e si guarda se la memoria torna.
        gw.py(LIGHT + "bench_bridge.STATE['bridge'].recorder._samples = []\nimport gc; gc.collect()")
        after = Sampler(pid, 5.0)
        after.start()
        time.sleep(60.0)
        after.stop()
        after.join()
        out["rest_after"] = {"samples": after.samples, "cpu_pct": cpu_percent(after.samples)}
        print("PARTIAL=" + json.dumps({"rest_after": out["rest_after"]}), flush=True)
        t_bake = time.perf_counter()
        out["bake"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.bake_last_take()))", "BENCH", 1800)
        out["bake"]["wall_s"] = time.perf_counter() - t_bake
        print("PARTIAL=" + json.dumps({"bake": out["bake"]}), flush=True)
    finally:
        sampler.stop()
        if sim.poll() is None:
            sim.kill()
        gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.teardown()))", "BENCH")

    def mem(samples: list[dict], key: str) -> list[float]:
        return [s[key] for s in samples if key in s]

    out["summary"] = {
        "cpu_pct_rest_before_mean": statistics.mean(out["rest_before"]["cpu_pct"])
        if out["rest_before"]["cpu_pct"]
        else None,
        "cpu_pct_during_mean": statistics.mean(out["during"]["cpu_pct"]) if out["during"]["cpu_pct"] else None,
        "cpu_pct_during_max": max(out["during"]["cpu_pct"]) if out["during"]["cpu_pct"] else None,
        "cpu_pct_rest_after_mean": statistics.mean(out["rest_after"]["cpu_pct"])
        if out["rest_after"]["cpu_pct"]
        else None,
        "private_mb_start": mem(out["during"]["samples"], "private_mb")[0],
        "private_mb_end": mem(out["during"]["samples"], "private_mb")[-1],
        "private_mb_after_discard": mem(out["rest_after"]["samples"], "private_mb")[-1],
        "ws_mb_start": mem(out["during"]["samples"], "ws_mb")[0],
        "ws_mb_end": mem(out["during"]["samples"], "ws_mb")[-1],
    }
    print("SUMMARY=" + json.dumps(out["summary"]))
    print("RESULT=" + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
