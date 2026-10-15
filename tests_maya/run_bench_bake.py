"""Misura del bake nel Maya aperto: nuovo (MFnAnimCurve.addKeys) contro il primo (xform + setKeyframe per fotogramma),
sulla STESSA take, a lunghezze crescenti. Il primo bake su 14401 chiavi non e' finito in 55 minuti (F4.5, 2026-10-15).

  python tests_maya/run_bench_bake.py --take <cartella>/magicam_bench_takes/stress10min.magicam.json

Atteso, scritto PRIMA:
- nuovo bake: tempo ~lineare nel numero di chiavi, 14401 chiavi in pochi secondi (< 10 s); chiavi = floor(durata·fps)+1
  su translate, rotate (e focalLength se c'e'); 0 salti Euler > 180°; la chiave a meta' riproduce la posa ricampionata
  entro 1e-6 unita'; dopo il bake Maya risponde subito (il gateway torna);
- vecchio bake: misurato a 500, 1000, 2000 chiavi per leggere l'esponente (se > 1 e' la causa del blocco); si ferma li',
  non si rifa' a 14401.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_gateway import Gateway
from run_bench_bridge import LIGHT, PRELUDE

DEFAULT_TAKE = Path.home() / "AppData/Local/Temp/magicam_bench_takes/stress10min.magicam.json"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--take", default=str(DEFAULT_TAKE))
    p.add_argument("--slow-seconds", nargs="*", type=float, default=[20.0, 40.0, 80.0])
    p.add_argument("--api-seconds", nargs="*", type=float, default=[20.0, 80.0, 300.0])
    p.add_argument("--skip-slow", action="store_true")
    a = p.parse_args(argv)
    take = str(Path(a.take).resolve()).replace("\\", "/")

    gw = Gateway()
    gw.start()
    out: dict = {"take": take, "api": [], "slow": []}
    # setup senza simulatore: serve solo la camera e il bridge (fermo) per bake_last_take
    setup = gw.py_json(PRELUDE + "print(bench_bridge.dumps(bench_bridge.setup(unit='cm', port=0)))", "BENCH")
    gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.stop_bridge()))", "BENCH")
    out["setup"] = setup
    try:
        for secs in a.api_seconds:
            t0 = time.perf_counter()
            r = gw.py_json(
                LIGHT + f"print(bench_bridge.dumps(bench_bridge.bake_last_take('api', {secs}, {take!r})))", "BENCH", 900
            )
            r["wall_s"] = time.perf_counter() - t0
            out["api"].append(r)
            print(
                "api",
                secs,
                "s:",
                json.dumps(
                    {
                        k: r[k]
                        for k in (
                            "keys_expected",
                            "keys_returned",
                            "keys_translateX",
                            "keys_rotateY",
                            "euler_jumps_over_180",
                            "mid_key_pos_err_units",
                            "bake_s",
                            "wall_s",
                        )
                    }
                ),
                flush=True,
            )
        # tutta la take col nuovo bake
        t0 = time.perf_counter()
        r = gw.py_json(
            LIGHT + f"print(bench_bridge.dumps(bench_bridge.bake_last_take('api', None, {take!r})))", "BENCH", 1800
        )
        r["wall_s"] = time.perf_counter() - t0
        out["api_full"] = r
        print("api FULL:", json.dumps(r), flush=True)
        if not a.skip_slow:
            for secs in a.slow_seconds:
                t0 = time.perf_counter()
                r = gw.py_json(
                    LIGHT + f"print(bench_bridge.dumps(bench_bridge.bake_last_take('slow', {secs}, {take!r})))",
                    "BENCH",
                    1800,
                )
                r["wall_s"] = time.perf_counter() - t0
                out["slow"].append(r)
                print(
                    "slow",
                    secs,
                    "s:",
                    json.dumps(
                        {
                            k: r[k]
                            for k in (
                                "keys_returned",
                                "euler_jumps_over_180",
                                "mid_key_pos_err_units",
                                "bake_s",
                                "wall_s",
                            )
                        }
                    ),
                    flush=True,
                )
    finally:
        gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.teardown()))", "BENCH")
    print("RESULT=" + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
