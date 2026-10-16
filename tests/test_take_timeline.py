"""R1: la take agganciata alla timeline di Maya.

Il tick del bridge, in playback, scatta una volta per fotogramma (MISURATO in Maya 2026 il 2026-10-16: 77 tick in
3,1 s, 76 fotogrammi distinti a 24 fps) e passa il fotogramma solo all'ultima posa del tick. Qui il tick e' simulato
cosi': pose a 60 Hz dal telefono, tick a 24 Hz, testina che avanza di un fotogramma per tick.

Contrasto col prima (misurato in Maya): le chiavi partivano dalla testina allo STOP (Rec a 1, Stop a 100 -> 100-167).
"""

import json
import math
from pathlib import Path

import numpy as np

from magicam.math3d import Transform, quat_from_axis_angle
from magicam.protocol import PoseMessage, TrackingReason, TrackingState
from magicam.takes import (
    TakeRecorder,
    keys_for_take,
    load_take,
    resample,
    save_take,
    timeline_anchors,
)

Y = (0.0, 1.0, 0.0)
T0 = 500.0
POSE_HZ = 60.0
FPS = 24.0


def msg(i: int, t: float) -> PoseMessage:
    return PoseMessage(i, t, TrackingState.NORMAL, TrackingReason.NONE, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def walk(t_rel: float) -> Transform:
    return Transform(pos=(0.3 * t_rel, 1.5, -0.5 * t_rel), quat=quat_from_axis_angle(Y, math.radians(10.0 * t_rel)))


def record_with_ticks(frames_per_tick, seconds: float = 4.0, rec_frame: float = 1.0):
    """Pose a 60 Hz; tick a 24 Hz; `frames_per_tick(k)` = fotogramma della testina al tick k (None = timeline ferma)."""
    rec = TakeRecorder()
    rec.start("timeline", frame=rec_frame)
    n_poses = int(seconds * POSE_HZ)
    poses = [(i, T0 + i / POSE_HZ) for i in range(n_poses)]
    k = 0
    i = 0
    while i < n_poses:
        t_tick = T0 + (k + 1) / FPS
        batch = []
        while i < n_poses and poses[i][1] <= t_tick:
            batch.append(poses[i])
            i += 1
        frame = frames_per_tick(k)
        for j, (seq, t) in enumerate(batch):
            rec.add(msg(seq, t), walk(t - T0), frame if j == len(batch) - 1 else None)
        k += 1
    return rec.stop({"scene_fps": FPS})


def first_seen_t(take, frame: int) -> float:
    return next(s.t for s in take.samples if s.frame is not None and s.frame >= frame)


def test_playing_timeline_keys_land_on_the_frames_the_director_saw():
    take = record_with_ticks(lambda k: 1.0 + k)  # testina da 1, un fotogramma per tick
    keys, mode = keys_for_take(take, FPS, fallback_start=999)
    assert mode == "timeline"
    assert keys[0].frame == 1
    assert [k.frame for k in keys] == list(range(1, keys[-1].frame + 1))
    # ogni chiave = la posa di quando QUEL fotogramma e' comparso
    for k in keys:
        t = first_seen_t(take, k.frame)
        assert np.allclose(k.camera.pos, walk(t - T0).pos, atol=1e-9), k.frame
    # CONTRASTO: il modo di prima (testina allo Stop come primo fotogramma)
    stop_frame = take.samples[-1].frame or 0.0
    old = resample(take, FPS, round(stop_frame))
    assert old[0].frame == round(stop_frame) and old[0].frame > 90


def test_rec_frame_gets_its_key_when_the_first_tick_already_sees_the_next_frame():
    # MISURATO in Maya (banco del 2026-10-16): Rec a 0, il primo tick in playback vede 1 -> chiavi da 1, mancava 0
    take = record_with_ticks(lambda k: 1.0 + k, rec_frame=0.0)
    keys, mode = keys_for_take(take, FPS, fallback_start=99)
    assert mode == "timeline" and keys[0].frame == 0
    assert np.allclose(keys[0].camera.pos, walk(0.0).pos, atol=1e-9)  # la posa del primo campione
    assert [k.frame for k in keys] == list(range(0, keys[-1].frame + 1))
    # ma un playback partito a mano molto dopo il Rec NON si stira all'indietro fino al Rec
    late = record_with_ticks(lambda k: 50.0 + k, rec_frame=0.0)
    assert keys_for_take(late, FPS, 1)[0][0].frame == 50


def test_manual_scrub_is_not_playback_so_frames_are_not_recorded():
    # MISURATO in Maya (banco del 2026-10-16): testina spostata a mano 37 -> 100 con la timeline ferma = 64 chiavi
    # stese su 2 s. Il bridge ora passa il fotogramma solo mentre Maya riproduce: qui = None (timeline ferma).
    take = record_with_ticks(lambda k: None, rec_frame=37.0)
    keys, mode = keys_for_take(take, FPS, fallback_start=1)
    assert mode == "tempo" and keys[0].frame == 37
    # CONTRASTO: con i fotogrammi dello scrub registrati (il modo di prima) diventava «timeline» 37-100
    scrub = record_with_ticks(lambda k: 37.0 if k < 24 else 100.0, rec_frame=37.0)
    k2, m2 = keys_for_take(scrub, FPS, fallback_start=1)
    assert m2 == "timeline" and (k2[0].frame, k2[-1].frame) == (37, 100)


def test_still_timeline_keys_start_at_the_rec_frame_not_at_the_stop():
    take = record_with_ticks(lambda k: 37.0, rec_frame=37.0)  # timeline ferma a 37
    assert timeline_anchors(take) == []
    keys, mode = keys_for_take(take, FPS, fallback_start=1)
    assert mode == "tempo"
    assert keys[0].frame == 37
    assert len(keys) == math.floor(take.duration * FPS + 1e-9) + 1


def test_loop_back_cuts_the_take_at_the_last_forward_frame():
    take = record_with_ticks(lambda k: 1.0 + (k % 50))  # la timeline torna a 1 dopo 50
    anchors = timeline_anchors(take)
    assert anchors[-1][0] == 50.0
    keys, _ = keys_for_take(take, FPS, fallback_start=1)
    assert keys[0].frame == 1 and keys[-1].frame == 50


def test_frames_skipped_by_playback_still_get_a_key_between_neighbours():
    take = record_with_ticks(lambda k: 1.0 + k + (2 if k >= 10 else 0))  # salta 11 e 12
    keys, _ = keys_for_take(take, FPS, fallback_start=1)
    frames = [k.frame for k in keys]
    assert 11 in frames and 12 in frames
    assert frames == list(range(1, frames[-1] + 1))
    t10, t13 = first_seen_t(take, 10), first_seen_t(take, 13)
    k11 = next(k for k in keys if k.frame == 11)
    expect = t10 + (t13 - t10) / 3.0
    assert np.allclose(k11.camera.pos, walk(expect - T0).pos, atol=1e-9)


def test_frames_survive_save_and_format_1_still_loads(tmp_path: Path):
    take = record_with_ticks(lambda k: 1.0 + k, seconds=1.0)
    p = save_take(take, tmp_path / "t.magicam.json")
    back = load_take(p)
    assert [s.frame for s in back.samples] == [s.frame for s in take.samples]
    assert back.metadata["rec_frame"] == 1.0
    assert keys_for_take(back, FPS, 1)[1] == "timeline"
    # un file del formato 1 (19 campi, senza fotogramma) si legge ancora e va «a tempo»
    old = tmp_path / "old.magicam.json"
    rows = [[T0 + i / 60.0] + [0.0] * 6 + [1.0] + [0.0] * 6 + [1.0, 0.0, 0, 0, True] for i in range(10)]
    old.write_text(json.dumps({"magicam_take": 1, "name": "v", "samples": rows}), encoding="utf-8")
    t1 = load_take(old)
    assert all(s.frame is None for s in t1.samples)
    keys, mode = keys_for_take(t1, FPS, fallback_start=5)
    assert mode == "tempo" and keys[0].frame == 5
