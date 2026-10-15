"""Banco F1.8 / F1.9 / F3.2-in-Maya, pilotato dal PC: simulatore qui, bridge dentro il Maya aperto (via gateway MCP).

  python tests_maya/run_bench_bridge.py --unit cm --duration 60 --take 5 35
  python tests_maya/run_bench_bridge.py --unit m --duration 10

Atteso, scritto PRIMA (docs/PIANO_DI_LAVORO.md F1.8/F1.9): 0 pose fuori ordine; coda che non cresce (salti di seq
applicati quasi tutti = 1, mai > qualche unita'); costo del tick ben sotto 16 ms; latenza simulatore->xform <= 2
fotogrammi a 60 Hz (33 ms) in mediana; la camera resta a raggio 0,5 m dall'ancora (50 cm o 0,5 m a seconda
dell'unita': e' il contrasto delle unita'); take di 30 s a 24 fps -> 721 chiavi (floor(30*24)+1), 0 salti Euler.
Stampa un JSON; la riga per docs/MISURE.md la scrive chi legge.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_gateway import Gateway

REPO = Path(__file__).resolve().parent.parent

PRELUDE = f"""
import sys, importlib
for p in ({str(REPO)!r}, {str(REPO / "tests_maya")!r}):
    if p not in sys.path:
        sys.path.insert(0, p)
# C2: si dichiara quale codice gira: i moduli di magicam gia' in memoria si ricaricano dal disco, in ordine
import magicam, magicam.protocol, magicam.math3d, magicam.filters, magicam.receiver, magicam.session
import magicam.takes, magicam.discovery, magicam.maya_bridge
for _m in (magicam.protocol, magicam.math3d, magicam.filters, magicam.receiver, magicam.session,
           magicam.takes, magicam.discovery, magicam.maya_bridge):
    importlib.reload(_m)
import bench_bridge
importlib.reload(bench_bridge)
"""

# dopo il setup NIENTE reload: lo stato del banco (bridge, receiver, misure) vive nel modulo bench_bridge
LIGHT = f"""
import sys
for p in ({str(REPO)!r}, {str(REPO / "tests_maya")!r}):
    if p not in sys.path:
        sys.path.insert(0, p)
import bench_bridge
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--unit", default="cm", choices=["cm", "m"])
    p.add_argument("--duration", type=float, default=60.0)
    p.add_argument("--rate", type=float, default=60.0)
    p.add_argument("--port", type=int, default=9000)
    p.add_argument("--no-filter", action="store_true")
    p.add_argument("--take", nargs=2, type=float, metavar=("START_S", "STOP_S"), default=None)
    p.add_argument("--fps-scene", default=None, help="es. film, pal, 30fps (default: quello della scena)")
    a = p.parse_args(argv)

    gw = Gateway()
    gw.start()
    out: dict = {"args": vars(a)}
    setup = gw.py_json(
        PRELUDE
        + "import maya.cmds as cmds\n"
        + (f"cmds.currentUnit(time={a.fps_scene!r})\n" if a.fps_scene else "")
        + f"print(bench_bridge.dumps(bench_bridge.setup(unit={a.unit!r}, filter_on={not a.no_filter}, port={a.port})))",
        "BENCH",
    )
    out["setup"] = setup
    print("setup:", json.dumps(setup))

    sim = subprocess.Popen(
        [
            sys.executable, "-m", "magicam.simulator",
            "--host", "127.0.0.1", "--port", str(setup["port"]), "--traj", "circle",
            "--rate", str(a.rate), "--duration", str(a.duration), "--clock", "host",
        ],
        cwd=str(REPO),
    )  # fmt: skip
    t0 = time.monotonic()
    try:
        time.sleep(1.5)
        out["calibrate"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.calibrate()))", "BENCH")
        print("calibrate:", json.dumps(out["calibrate"]))
        if a.take:
            start_s, stop_s = a.take
            time.sleep(max(0.0, t0 + start_s - time.monotonic()))
            out["rec_start"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.rec_start('bench')))", "BENCH")
            time.sleep(max(0.0, t0 + stop_s - time.monotonic()))
            out["rec_stop"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.rec_stop()))", "BENCH")
            print("take:", json.dumps(out["rec_stop"]))
        sim.wait(timeout=a.duration + 30)
        time.sleep(0.5)
        out["report"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.report()))", "BENCH")
        gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.stop_bridge()))", "BENCH")
        if a.take:
            out["bake"] = gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.bake_last_take()))", "BENCH", 900)
    finally:
        if sim.poll() is None:
            sim.kill()
        gw.py_json(LIGHT + "print(bench_bridge.dumps(bench_bridge.teardown()))", "BENCH")
    print("RESULT=" + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
