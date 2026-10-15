"""take: 240 chiavi a 24 fps da 600 campioni a 60 Hz (il v1 ne faceva 600 = 25 s), nessun buco, fermo = fermo."""

import json
import math
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

from magicam.math3d import Transform, quat_angle, quat_from_axis_angle
from magicam.protocol import PoseMessage, TrackingReason, TrackingState
from magicam.takes import (
    Sample,
    Take,
    TakeError,
    TakeLibrary,
    TakeRecorder,
    default_take_folder,
    fps_from_maya_time_unit,
    load_take,
    resample,
    save_take,
    take_path,
)

Y = (0.0, 1.0, 0.0)
HZ = 60.0
T0 = 1000.0


def msg(i: int, t: float) -> PoseMessage:
    return PoseMessage(i, t, TrackingState.NORMAL, TrackingReason.NONE, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0))


def walk(t_rel: float) -> Transform:
    """Camera che avanza a 0.5 m/s e gira a 10 deg/s."""
    return Transform(pos=(0.0, 1.5, -0.5 * t_rel), quat=quat_from_axis_angle(Y, math.radians(10.0 * t_rel)))


def record(n: int = 600, drop: set[int] | None = None, still: tuple[float, float] | None = None) -> Take:
    rec = TakeRecorder()
    rec.start("prova")
    for i in range(n):
        if drop and i in drop:
            continue
        t_rel = i / HZ
        # fermo fra still[0] e still[1]: la camera resta dov'era
        cam = walk(still[0]) if still and still[0] <= t_rel < still[1] else walk(t_rel)
        rec.add(msg(i, T0 + t_rel), cam)
    return rec.stop({"scene_fps": 24.0})


def test_600_samples_at_60hz_give_240_keys_at_24fps_and_v1_contrast():
    take = record()
    assert len(take.samples) == 600
    assert abs(take.duration - 599 / HZ) < 1e-9
    keys = resample(take, 24.0, start_frame=1)
    assert len(keys) == 240
    assert [k.frame for k in keys] == list(range(1, 241))
    assert all(b.frame == a.frame + 1 for a, b in pairwise(keys))
    assert abs(keys[-1].t - 239 / 24.0) < 1e-9  # ~9.96 s: la durata reale
    # CONTRASTO (v1): una chiave per pacchetto, +1 fotogramma ciascuna -> 600 chiavi = 25 s a 24 fps
    v1_keys = len(take.samples)
    assert v1_keys == 600 and v1_keys / 24.0 == 25.0


def test_keys_follow_the_trajectory_in_time_not_in_packets():
    keys = resample(record(), 24.0)
    for k in keys:
        atteso = walk(k.t)
        assert np.allclose(k.camera.pos, atteso.pos, atol=1e-9), k.frame
        assert quat_angle(k.camera.quat, atteso.quat) < 1e-7, k.frame  # slerp su un giro uniforme: esatto


def test_ten_percent_loss_still_gives_240_keys_without_gaps():
    rng = np.random.default_rng(0)
    drop = set(int(i) for i in rng.choice(np.arange(1, 599), size=60, replace=False))  # mai il primo ne' l'ultimo
    take = record(drop=drop)
    assert len(take.samples) == 540
    keys = resample(take, 24.0)
    assert len(keys) == 240
    assert all(b.frame == a.frame + 1 for a, b in pairwise(keys))
    for k in keys:  # moto lineare: l'interpolazione per tempo lo ricostruisce esatto
        assert np.allclose(k.camera.pos, walk(k.t).pos, atol=1e-9)


def test_operator_still_for_3s_gives_a_still_camera_for_3s():
    take = record(still=(3.0, 6.0))
    keys = resample(take, 24.0)
    inside = [k for k in keys if 3.0 + 1 / 24 <= k.t < 6.0]
    assert len(inside) >= 70
    p0 = inside[0].camera.pos
    assert all(np.allclose(k.camera.pos, p0, atol=1e-12) for k in inside)
    assert all(quat_angle(k.camera.quat, inside[0].camera.quat) < 1e-12 for k in inside)
    before = [k for k in keys if k.t < 2.9]
    assert not np.allclose(before[0].camera.pos, before[-1].camera.pos)  # prima si muoveva


def test_hold_records_last_camera_and_skips_before_calibration():
    rec = TakeRecorder()
    rec.start("hold")
    rec.add(msg(0, T0), None)  # non calibrata: niente
    assert rec.sample_count == 0
    rec.add(msg(1, T0 + 0.1), Transform(pos=(1, 2, 3)))
    rec.add(msg(2, T0 + 0.2), None)  # hold: la camera resta a (1,2,3)
    rec.add(msg(3, T0 + 0.2), Transform(pos=(9, 9, 9)))  # tempo che non avanza: scartato
    take = rec.stop()
    assert len(take.samples) == 2
    assert take.samples[1].camera.pos == (1, 2, 3)
    assert take.metadata["skipped_no_camera"] == 1


def test_recorder_lifecycle_errors():
    rec = TakeRecorder()
    with pytest.raises(RuntimeError):
        rec.stop()
    rec.start("a")
    with pytest.raises(RuntimeError):
        rec.start("b")


def test_resample_edge_cases():
    assert resample(Take("vuota", ()), 24.0) == []
    one = Take("una", (Sample(5.0, Transform(pos=(1, 0, 0)), Transform()),))
    keys = resample(one, 24.0, start_frame=101)
    assert len(keys) == 1 and keys[0].frame == 101
    with pytest.raises(ValueError):
        resample(one, 0.0)


@pytest.mark.parametrize(
    "unit, fps",
    [
        ("film", 24.0),
        ("pal", 25.0),
        ("ntsc", 30.0),
        ("ntscf", 60.0),
        ("23.976fps", 23.976),
        ("120fps", 120.0),
        ("25fps", 25.0),
    ],
)
def test_fps_from_maya_time_unit(unit, fps):
    assert fps_from_maya_time_unit(unit) == fps


def test_fps_unknown_unit_raises():
    with pytest.raises(ValueError):
        fps_from_maya_time_unit("millisec")


def test_save_load_roundtrip_atomic_and_never_overwrites(tmp_path: Path):
    take = record(n=30)
    p1 = save_take(take, take_path(tmp_path, "shot 01/A"))
    assert p1.name == "shot_01_A.magicam.json"
    p2 = save_take(take, take_path(tmp_path, "shot 01/A"))
    assert p2 != p1 and p2.exists() and p1.exists()
    assert not list(tmp_path.glob("*.tmp*"))
    back = load_take(p1)
    assert back.name == "prova" and len(back.samples) == 30
    for a, b in zip(back.samples, take.samples, strict=True):
        assert a.t == b.t
        assert np.allclose(a.camera.pos, b.camera.pos) and np.allclose(a.camera.quat, b.camera.quat)
        assert np.allclose(a.phone.pos, b.phone.pos)
    assert back.metadata["scene_fps"] == 24.0


def test_load_rejects_garbage(tmp_path: Path):
    bad = tmp_path / "x.magicam.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(TakeError):
        load_take(bad)
    bad.write_text(json.dumps({"magicam_take": 1, "samples": [[1, 2, 3]]}), encoding="utf-8")
    with pytest.raises(TakeError, match="19"):
        load_take(bad)
    row = [1.0] + [0.0] * 15 + [0, 0, True]
    row2 = list(row)
    row2[0] = 0.5  # tempo che torna indietro
    bad.write_text(json.dumps({"magicam_take": 1, "samples": [row, row2]}), encoding="utf-8")
    with pytest.raises(TakeError, match="crescente"):
        load_take(bad)
    bad.write_text(json.dumps({"magicam_take": 7, "samples": []}), encoding="utf-8")
    with pytest.raises(TakeError, match="v1"):
        load_take(bad)


def test_library_lists_and_discards_into_cestino(tmp_path: Path):
    lib = TakeLibrary(tmp_path / "magicam_takes")
    assert lib.list() == []
    p = lib.save(record(n=5))
    assert lib.list() == [p]
    moved = lib.discard(p)
    assert not p.exists() and moved.exists() and moved.parent.name == "_cestino"
    assert lib.list() == []
    with pytest.raises(TakeError):
        lib.discard(tmp_path / "altrove.magicam.json")


def test_default_take_folder(tmp_path: Path):
    assert default_take_folder("C:/scene/shot.ma") == Path("C:/scene").resolve() / "magicam_takes"
    assert default_take_folder(None, home=tmp_path) == tmp_path / "Documents" / "magicam_takes"
    assert default_take_folder("", home=tmp_path) == tmp_path / "Documents" / "magicam_takes"
