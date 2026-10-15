"""Lato Maya del banco F1.8/F1.9/F3: si importa DENTRO Maya (via tests_maya/run_bench_bridge.py dal PC).

setup(unit) -> bridge su una camera nuova a (5 m, 1.5 m, 0) yaw 90, receiver su 9000, timer a 60 Hz;
calibrate() quando il simulatore manda; rec_start()/rec_stop(); report() legge TUTTO; teardown().
Il simulatore sul PC manda `t_sensor = time.perf_counter()`: stessa macchina, stesso orologio, quindi
`monotonic_all'applicazione - t_sensor` e' la latenza di tutta la catena (pacing -> UDP -> thread -> tick -> xform).
"""

from __future__ import annotations

import itertools
import json
import math
import statistics
import tempfile
import time
from pathlib import Path

import maya.cmds as cmds

from magicam.maya_bridge import MayaCameraBridge
from magicam.receiver import Receiver
from magicam.session import Session

STATE: dict = {}


def setup(
    unit: str = "cm", tick_hz: float = 60.0, filter_on: bool = True, port: int = 9000, live_undo: bool = False
) -> dict:
    teardown()
    found_unit = cmds.currentUnit(q=True, linear=True)  # C3: chi cambia uno stato lo rimette al valore TROVATO
    # Regola 8: la scena e' dell'utente. Il banco apre una scena nuova SOLO se quella aperta e' «untitled» e senza
    # modifiche; altrimenti si ferma e lo dice (il primo banco faceva file -new -force senza guardare).
    # (`modified` da solo non basta: un Maya appena aperto e' gia' «modificato» dagli script di avvio.)
    extra = [t for t in (cmds.ls(type="transform") or []) if t not in ("persp", "top", "front", "side")]
    if cmds.file(q=True, sceneName=True) or extra:
        raise RuntimeError(f"scena con nome o con oggetti ({extra[:5]}): salva/chiudi tu, il banco non la butta")
    cmds.file(new=True, force=True)
    cmds.currentUnit(linear=unit)
    STATE["found_unit"] = found_unit
    cam = cmds.camera(name="magicam_bench")[0]
    upm = {"cm": 100.0, "m": 1.0, "mm": 1000.0}[unit]
    cmds.xform(cam, ws=True, t=(5.0 * upm, 1.5 * upm, 0.0), ro=(0.0, 90.0, 0.0))
    session = Session(filter_enabled=filter_on)
    receiver = Receiver(port=port, host="0.0.0.0")
    bridge = MayaCameraBridge(session, receiver, cam, tick_hz=tick_hz)
    bridge.advertise = False
    bridge.auto_bake = False
    bridge.live_undo = live_undo  # True solo per il contrasto: pose dal vivo nella coda di undo
    bridge.take_folder = Path(tempfile.gettempdir()) / "magicam_bench_takes"
    latencies: list[float] = []
    applied_seqs: list[int] = []
    tick_times: list[float] = []
    orig_apply = bridge._apply

    def _apply(cam_t, msg):
        orig_apply(cam_t, msg)
        latencies.append(time.perf_counter() - msg.t_sensor)
        applied_seqs.append(msg.seq)

    bridge._apply = _apply  # type: ignore[method-assign]
    orig_tick = bridge.tick

    def tick():
        tick_times.append(time.perf_counter())
        orig_tick()

    bridge.tick = tick  # type: ignore[method-assign]
    try:
        bridge.start()
    except Exception:
        receiver.stop()  # mai lasciare un receiver orfano sulla porta
        cmds.delete(cam)
        raise
    STATE.update(
        cam=cam,
        upm=upm,
        unit=unit,
        session=session,
        receiver=receiver,
        bridge=bridge,
        latencies=latencies,
        applied_seqs=applied_seqs,
        tick_times=tick_times,
        t_start=time.perf_counter(),
        bake=None,
    )
    return {"camera": cam, "unit": unit, "port": receiver.port, "maya": cmds.about(version=True), "tick_hz": tick_hz}


def calibrate() -> dict:
    b: MayaCameraBridge = STATE["bridge"]
    ok = b.calibrate()
    latest = b.receiver.latest()
    return {"ok": ok, "received": b.receiver.stats.received, "latest_seq": None if latest is None else latest[0].seq}


def rec_start(name: str = "bench") -> dict:
    STATE["bridge"].start_take(name)
    return {"recording": True, "t": time.perf_counter() - STATE["t_start"]}


def rec_stop() -> dict:
    b: MayaCameraBridge = STATE["bridge"]
    n_before = b.recorder.sample_count
    path = b.stop_take()
    STATE["take_path"] = str(path)
    return {"samples": n_before, "path": str(path)}


def _bake_slow(b: MayaCameraBridge, take, cam: str, keys) -> int:
    """Il PRIMO bake (xform + setKeyframe per fotogramma + filterCurve), tenuto qui solo per misurarne la scala:
    su 14401 chiavi non finiva piu' (F4.5, 2026-10-15). Il prodotto usa MFnAnimCurve.addKeys."""
    from magicam.math3d import to_maya_matrix

    cmds.undoInfo(openChunk=True, chunkName="MagiCAM take (slow)")
    try:
        for k in keys:
            cmds.xform(cam, ws=True, matrix=to_maya_matrix(k.camera, b._unit))
            cmds.setKeyframe(cam, attribute=["translate", "rotate"], time=k.frame)
        cmds.filterCurve(f"{cam}.rotateX", f"{cam}.rotateY", f"{cam}.rotateZ")
    finally:
        cmds.undoInfo(closeChunk=True)
    return len(keys)


def clear_camera_anim() -> dict:
    cam = STATE["cam"]
    curves = cmds.listConnections(cam, type="animCurve") or []
    shapes = cmds.listRelatives(cam, shapes=True) or []
    for s in shapes:
        curves += cmds.listConnections(s, type="animCurve") or []
    if curves:
        cmds.delete(curves)
    return {"deleted_curves": len(curves)}


def bake_last_take(method: str = "api", max_seconds: float | None = None, take_path: str | None = None) -> dict:
    """Si chiama a bridge FERMO (dopo stop()), cosi' il tick non sovrascrive i canali animati.

    method: "api" (prodotto: MFnAnimCurve.addKeys) o "slow" (il primo bake, per la misura di scala);
    max_seconds: tronca la take ai primi N secondi (misure a 1000/2000/4000 chiavi).
    """
    from dataclasses import replace

    from magicam.takes import load_take, resample

    b: MayaCameraBridge = STATE["bridge"]
    take = load_take(Path(take_path or STATE["take_path"]))
    if max_seconds is not None:
        t0s = take.samples[0].t
        take = replace(take, samples=tuple(s for s in take.samples if s.t - t0s <= max_seconds))
    cam = STATE["cam"]
    clear_camera_anim()
    cmds.currentTime(1)
    t0 = time.perf_counter()
    if method == "slow":
        n = _bake_slow(b, take, cam, resample(take, b.scene_fps(), 1))
    else:
        n = b.bake_take(take, start_frame=1)
    dt = time.perf_counter() - t0
    # verifica a campione: la chiave a meta' deve riprodurre la posa ricampionata (posizione in unita' UI)
    keys = resample(take, b.scene_fps(), 1)
    mid = keys[len(keys) // 2]
    cmds.currentTime(mid.frame)
    pos_ui = cmds.xform(cam, q=True, ws=True, t=True)
    exp_ui = [c * STATE["upm"] for c in mid.camera.pos]
    mid_err_units = max(abs(a - e) for a, e in zip(pos_ui, exp_ui, strict=True))
    fps = b.scene_fps()
    counts = {a: cmds.keyframe(f"{cam}.{a}", q=True, keyframeCount=True) for a in ("translateX", "rotateY")}
    times = cmds.keyframe(f"{cam}.translateX", q=True, timeChange=True) or []
    rot_y = cmds.keyframe(f"{cam}.rotateY", q=True, valueChange=True) or []
    jumps = sum(1 for a, c in itertools.pairwise(rot_y) if abs(c - a) > 180.0)
    out = {
        "samples": len(take.samples),
        "duration_s": take.duration,
        "fps": fps,
        "keys_expected": math.floor(take.duration * fps + 1e-9) + 1,
        "keys_returned": n,
        "keys_translateX": counts["translateX"],
        "keys_rotateY": counts["rotateY"],
        "first_frame": times[0] if times else None,
        "last_frame": times[-1] if times else None,
        "euler_jumps_over_180": jumps,
        "bake_s": dt,
        "method": method,
        "mid_key_pos_err_units": mid_err_units,
        "undo_name": cmds.undoInfo(q=True, undoName=True),
    }
    STATE["bake"] = out
    return out


def report() -> dict:
    b: MayaCameraBridge = STATE["bridge"]
    st = b.receiver.stats
    lat = STATE["latencies"]
    seqs = STATE["applied_seqs"]
    ticks = STATE["tick_times"]
    gaps = [c - a for a, c in itertools.pairwise(seqs)]
    tick_dt = [c - a for a, c in itertools.pairwise(ticks)]
    cam = STATE["cam"]
    pos = cmds.xform(cam, q=True, ws=True, t=True)
    anchor = (5.0 * STATE["upm"], 1.5 * STATE["upm"], 0.0)
    dist_from_anchor = math.dist(pos, anchor)
    # ATTESO: |cam - A| = |P - C| (scala 1, rel.pos solo ruotato da A); yaw(cam) - yaw(A) = yaw(P) - yaw(C).
    # (Il primo banco pretendeva il raggio del cerchio: sbagliato, il cerchio e' centrato sull'origine ARKit.)
    sess = b.session
    expected_dist = None
    rot_err_deg = None
    if sess.calib is not None and sess.last_phone is not None and sess.anchor is not None:
        from magicam.math3d import from_maya_matrix, quat_angle, quat_conj, quat_mul, vec_norm, vec_sub

        expected_dist = vec_norm(vec_sub(sess.last_phone.pos, sess.calib.pos)) * STATE["upm"]
        cam_t = from_maya_matrix(list(cmds.xform(cam, q=True, ws=True, matrix=True)), STATE["upm"])
        d_cam = quat_mul(quat_conj(sess.anchor.quat), cam_t.quat)
        d_phone = quat_mul(quat_conj(sess.calib.quat), sess.last_phone.quat)
        rot_err_deg = math.degrees(quat_angle(d_cam, d_phone))

    def pct(v, p):
        if not v:
            return None
        v = sorted(v)
        return v[min(len(v) - 1, round(p * (len(v) - 1)))]

    return {
        "unit": STATE["unit"],
        "elapsed_s": time.perf_counter() - STATE["t_start"],
        "receiver": {
            "received": st.received,
            "lost": st.lost,
            "reordered": st.reordered,
            "rejected": st.rejected,
            "latency_ms_estimate": st.latency_ms,
        },
        "tick": {
            "ticks": b.stats.ticks,
            "applied": b.stats.applied,
            "applied_hz": b.stats.applied_hz,
            "cost_ms_last": b.stats.last_cost_ms,
            "cost_ms_max": b.stats.max_cost_ms,
            "dt_ms_mean": statistics.mean(tick_dt) * 1000 if tick_dt else None,
            "dt_ms_p95": (pct(tick_dt, 0.95) or 0) * 1000,
            "dt_ms_max": max(tick_dt) * 1000 if tick_dt else None,
        },
        "applied_seq_gaps": {
            "n": len(gaps),
            "eq1": sum(1 for g in gaps if g == 1),
            "eq2": sum(1 for g in gaps if g == 2),
            "gt2": sum(1 for g in gaps if g > 2),
            "max": max(gaps) if gaps else None,
            "backwards": sum(1 for g in gaps if g < 1),
        },
        "latency_ms": {
            "n": len(lat),
            "mean": statistics.mean(lat) * 1000 if lat else None,
            "p50": (pct(lat, 0.5) or 0) * 1000,
            "p95": (pct(lat, 0.95) or 0) * 1000,
            "max": max(lat) * 1000 if lat else None,
        },
        "session": {"hold": b.session.hold().value, "reanchors": b.session.state().reanchors},
        # C2: quale codice ha girato, e cosa sta in cima alla coda di undo dopo il live (xform = pose dal vivo in coda)
        "live_undo": getattr(b, "live_undo", "n/a: codice senza live_undo"),
        "undo_top": cmds.undoInfo(q=True, undoName=True),
        "camera_pos": pos,
        "camera_dist_from_anchor_units": dist_from_anchor,
        "expected_dist_units_P_minus_C": expected_dist,
        "dist_err_units": None if expected_dist is None else dist_from_anchor - expected_dist,
        "rot_rel_err_deg": rot_err_deg,
        "poses_through_session": b.stats.poses,
        "bake": STATE.get("bake"),
    }


def stop_bridge() -> dict:
    STATE["bridge"].stop()
    return {"stopped": True}


def teardown() -> dict:
    b = STATE.get("bridge")
    if b is not None:
        try:
            b.stop()
        except Exception as e:  # noqa: BLE001 - banco: si riporta, non si nasconde
            print("teardown:", e)
    cam = STATE.get("cam")
    if cam and cmds.objExists(cam):
        cmds.delete(cam)
    found = STATE.get("found_unit")
    if found:
        cmds.currentUnit(linear=found)
    STATE.clear()
    return {"clean": True}


def dumps(d: dict) -> str:
    return "BENCH=" + json.dumps(d)
