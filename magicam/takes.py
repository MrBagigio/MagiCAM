"""Take: campioni con il timestamp del SENSORE, ricampionati agli fps della scena, poi chiavi. Python puro.

Il v1 scriveva una chiave per pacchetto e avanzava la timeline di un fotogramma: 60 pacchetti/s su una scena a
24 fps = take 2,5x veloce, buchi dove l'operatore stava fermo. Qui il tempo e' quello del sensore; la cottura
(maya_bridge.bake_take) riceve una chiave per fotogramma, nessun buco, durata = durata reale.

Una take grezza si salva in JSON con scrittura atomica (tmp + replace) accanto alla scena: se Maya cade, la take c'e'.
Niente si cancella: `TakeLibrary.discard` sposta in `_cestino/`.

Agganciata alla timeline (R1, 2026-10-16): durante una take il tick del bridge scrive nel campione il fotogramma di
Maya che il regista stava guardando (`Sample.frame`). Se la timeline scorreva, le chiavi vanno su QUEI fotogrammi
(`keys_for_take` -> `resample_timeline`); se era ferma, da `rec_frame` (il fotogramma al Rec), non da quello allo Stop.
MISURATO prima della cura: Rec a 1, testina a 100 durante la take, Stop -> chiavi 100-167.
"""

from __future__ import annotations

import functools
import json
import math
import os
import re
import shutil
import time
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path

from magicam import PROTOCOL_VERSION, __version__
from magicam.math3d import Transform, quat_slerp, quat_to_euler_xyz_deg, vec_lerp
from magicam.protocol import PoseMessage

TAKE_FORMAT = 2  # 2: campo `frame` (fotogramma di Maya) in coda al campione; il formato 1 si legge ancora
TAKE_SUFFIX = ".magicam.json"
CESTINO = "_cestino"


class TakeError(ValueError):
    """File di take illeggibile o incoerente. Il messaggio dice cosa."""


@dataclass(frozen=True, slots=True)
class Sample:
    t: float  # t_sensor (s, orologio del telefono)
    camera: Transform  # posa della camera applicata (metri, mondo Maya): cio' che l'operatore ha visto
    phone: Transform  # posa grezza del telefono (mondo ARKit), per ricuocere con altra scala/filtro
    focal_px: float = 0.0
    image_w: int = 0
    image_h: int = 0
    tracking_ok: bool = True
    frame: float | None = None  # fotogramma di Maya al tick che ha applicato questa posa (solo l'ultima del tick)


@dataclass(frozen=True, slots=True)
class Keyframe:
    frame: int
    t: float  # secondi dall'inizio della take
    camera: Transform
    focal_px: float


@dataclass
class Take:
    name: str
    samples: tuple[Sample, ...]
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return 0.0 if len(self.samples) < 2 else self.samples[-1].t - self.samples[0].t

    @property
    def t0(self) -> float:
        return self.samples[0].t if self.samples else 0.0


# --- registrazione -----------------------------------------------------------------------------------------------


class TakeRecorder:
    """Accumula campioni mentre `recording` e' vero. `add` va chiamato a ogni posa applicata (dal tick del bridge)."""

    def __init__(self) -> None:
        self.recording = False
        self.name = ""
        self._samples: list[Sample] = []
        self._last_camera: Transform | None = None
        self._last_t: float | None = None
        self._skipped_no_camera = 0
        self.rec_frame: float | None = None

    def start(self, name: str, frame: float | None = None) -> None:
        """`frame` = fotogramma di Maya al Rec: da li' partono le chiavi se la timeline non scorre."""
        if self.recording:
            raise RuntimeError("take gia' in corso")
        self.name = name or datetime.now().strftime("take_%Y%m%d_%H%M%S")
        self._samples = []
        self._last_t = None
        self._skipped_no_camera = 0
        self.rec_frame = frame
        self.recording = True

    def add(self, msg: PoseMessage, camera: Transform | None, frame: float | None = None) -> None:
        """camera=None vuol dire «la camera non si e' mossa» (hold): si registra l'ultima posa applicata.

        `frame`: il fotogramma di Maya mostrato quando questa posa e' stata applicata (il bridge lo passa solo
        all'ultima posa di ogni tick, quella che la camera ha davvero preso)."""
        if camera is not None:
            self._last_camera = camera
        if not self.recording:
            return
        if self._last_camera is None:
            self._skipped_no_camera += 1  # non ancora calibrata: niente da registrare
            return
        if self._last_t is not None and msg.t_sensor <= self._last_t:
            return  # duplicato o riordinato: il tempo deve avanzare
        self._last_t = msg.t_sensor
        self._samples.append(
            Sample(
                msg.t_sensor,
                self._last_camera,
                Transform(msg.pos, msg.quat),
                msg.focal_px,
                msg.image_w,
                msg.image_h,
                msg.tracking_ok,
                frame,
            )
        )

    def stop(self, metadata: dict[str, object] | None = None) -> Take:
        if not self.recording:
            raise RuntimeError("nessuna take in corso")
        self.recording = False
        meta: dict[str, object] = {
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "magicam_version": __version__,
            "protocol_version": PROTOCOL_VERSION,
            "samples": len(self._samples),
            "skipped_no_camera": self._skipped_no_camera,
            "rec_frame": self.rec_frame,
        }
        if metadata:
            meta.update(metadata)
        return Take(self.name, tuple(self._samples), meta)

    @property
    def sample_count(self) -> int:
        return len(self._samples)


# --- ricampionamento ---------------------------------------------------------------------------------------------


def resample(take: Take, fps: float, start_frame: int = 1) -> list[Keyframe]:
    """Una chiave per fotogramma, da t0 a t0+durata, interpolando per TEMPO (lerp posizione, slerp rotazione).

    Numero di chiavi = floor(durata*fps) + 1: 600 campioni a 60 Hz (9,983 s) su 24 fps -> 240 chiavi.
    """
    if fps <= 0 or math.isnan(fps) or math.isinf(fps):
        raise ValueError(f"fps deve essere > 0: {fps!r}")
    s = take.samples
    if not s:
        return []
    if len(s) == 1:
        return [Keyframe(start_frame, 0.0, s[0].camera, s[0].focal_px)]
    times = [x.t for x in s]
    t0 = times[0]
    n = math.floor(take.duration * fps + 1e-9) + 1
    return [_key_at(s, times, start_frame + k, t0 + k / fps, t0) for k in range(n)]


def _key_at(s: Sequence[Sample], times: Sequence[float], frame: int, t: float, t0: float) -> Keyframe:
    """La posa della camera al tempo `t` del sensore: lerp della posizione, slerp della rotazione."""
    i = bisect_right(times, t) - 1
    i = max(0, min(i, len(s) - 2))
    a, b = s[i], s[i + 1]
    span = b.t - a.t
    u = 0.0 if span <= 0 else max(0.0, min(1.0, (t - a.t) / span))
    cam = Transform(vec_lerp(a.camera.pos, b.camera.pos, u), quat_slerp(a.camera.quat, b.camera.quat, u))
    focal = a.focal_px + (b.focal_px - a.focal_px) * u
    return Keyframe(frame, t - t0, cam, focal)


def timeline_anchors(take: Take) -> list[tuple[float, float]]:
    """(fotogramma, t_sensor) del PRIMO tick che ha visto ogni fotogramma, in ordine crescente.

    Ci si ferma al primo fotogramma che torna indietro (loop della timeline, o testina spostata a mano): da li' in
    poi il legame tempo -> fotogramma non e' piu' quello di una ripresa continua. Lista vuota = la timeline non
    scorreva (meno di due fotogrammi distinti)."""
    out: list[tuple[float, float]] = []
    for smp in take.samples:
        if smp.frame is None:
            continue
        if out and smp.frame < out[-1][0]:
            break
        if not out or smp.frame > out[-1][0]:
            out.append((smp.frame, smp.t))
    return out if len(out) >= 2 else []


def resample_timeline(take: Take, anchors: Sequence[tuple[float, float]]) -> list[Keyframe]:
    """Una chiave per OGNI fotogramma intero che la timeline ha attraversato, con la posa di quando era a video.

    Un fotogramma saltato dal playback prende il tempo interpolato fra i due vicini visti."""
    s = take.samples
    if len(s) < 2 or len(anchors) < 2:
        return []
    times = [x.t for x in s]
    fs = [a[0] for a in anchors]
    ts = [a[1] for a in anchors]
    first, last = math.ceil(fs[0] - 1e-9), math.floor(fs[-1] + 1e-9)
    keys: list[Keyframe] = []
    for frame in range(first, last + 1):
        j = bisect_right(fs, frame) - 1
        j = max(0, min(j, len(fs) - 2))
        df = fs[j + 1] - fs[j]
        u = 0.0 if df <= 0 else (frame - fs[j]) / df
        t = ts[j] + (ts[j + 1] - ts[j]) * u
        keys.append(_key_at(s, times, frame, t, s[0].t))
    return keys


def keys_for_take(take: Take, fps: float, fallback_start: int) -> tuple[list[Keyframe], str]:
    """Le chiavi di una take e come sono state messe: «timeline» (fotogrammi visti) o «tempo» (dal Rec, agli fps).

    Senza timeline che scorre, la prima chiave e' il fotogramma al Rec (`metadata.rec_frame`); `fallback_start`
    solo per le take vecchie che non lo hanno."""
    anchors = timeline_anchors(take)
    rec = take.metadata.get("rec_frame")
    if anchors:
        # MISURATO (banco del 2026-10-16): Rec a 0, il primo tick vede gia' 1 -> mancava la chiave del Rec. Il
        # fotogramma del Rec e' a video dal primo campione fino al primo fotogramma visto dopo.
        # Solo se il playback e' partito DAL Rec (entro 2 fotogrammi): un playback avviato a mano molto dopo
        # stirerebbe il moto sull'intervallo.
        if isinstance(rec, (int, float)) and 0 < anchors[0][0] - rec <= 2 and take.samples[0].t < anchors[0][1]:
            anchors = [(float(rec), take.samples[0].t), *anchors]
        return resample_timeline(take, anchors), "timeline"
    start = round(float(rec)) if isinstance(rec, (int, float)) else fallback_start
    return resample(take, fps, start), "tempo"


_FPS_NAMES = {
    "game": 15.0,
    "film": 24.0,
    "pal": 25.0,
    "ntsc": 30.0,
    "show": 48.0,
    "palf": 50.0,
    "ntscf": 60.0,
    "23.976fps": 23.976,
    "29.97fps": 29.97,
    "29.97df": 29.97,
    "47.952fps": 47.952,
    "59.94fps": 59.94,
}


def fps_from_maya_time_unit(unit: str) -> float:
    """`cmds.currentUnit(q=True, time=True)` -> fps. Nomi storici e la forma `Nfps`."""
    u = unit.strip().lower()
    if u in _FPS_NAMES:
        return _FPS_NAMES[u]
    m = re.fullmatch(r"(\d+(?:\.\d+)?)fps", u)
    if m:
        return float(m.group(1))
    raise ValueError(f"unita' di tempo di Maya non riconosciuta: {unit!r}")


# --- file --------------------------------------------------------------------------------------------------------


def _sample_to_row(s: Sample) -> list[object]:
    return [
        s.t,
        *s.camera.pos,
        *s.camera.quat,
        *s.phone.pos,
        *s.phone.quat,
        s.focal_px,
        s.image_w,
        s.image_h,
        s.tracking_ok,
        s.frame,
    ]


def _row_to_sample(row: Sequence[object]) -> Sample:
    if len(row) not in (19, 20):
        raise TakeError(f"campione con {len(row)} campi, attesi 19 (formato 1) o 20")
    f = [float(x) for x in row[:16]]  # type: ignore[arg-type]
    for v in f:
        if math.isnan(v) or math.isinf(v):
            raise TakeError("campione con valore non finito")
    return Sample(
        f[0],
        Transform((f[1], f[2], f[3]), (f[4], f[5], f[6], f[7])),
        Transform((f[8], f[9], f[10]), (f[11], f[12], f[13], f[14])),
        f[15],
        int(row[16]),  # type: ignore[call-overload]
        int(row[17]),  # type: ignore[call-overload]
        bool(row[18]),
        None if len(row) == 19 or row[19] is None else float(row[19]),  # type: ignore[arg-type]
    )


def take_path(folder: Path, name: str) -> Path:
    safe = re.sub(r"[^\w\-.]+", "_", name).strip("_") or "take"
    return folder / f"{safe}{TAKE_SUFFIX}"


def save_take(take: Take, path: Path) -> Path:
    """Scrittura atomica: file temporaneo accanto, poi `os.replace`. Non sovrascrive: aggiunge un suffisso."""
    path.parent.mkdir(parents=True, exist_ok=True)
    final = path
    k = 1
    while final.exists():
        final = path.with_name(f"{path.name[: -len(TAKE_SUFFIX)]}_{k}{TAKE_SUFFIX}")
        k += 1
    doc = {
        "magicam_take": TAKE_FORMAT,
        "name": take.name,
        "metadata": take.metadata,
        "samples": [_sample_to_row(s) for s in take.samples],
    }
    tmp = final.with_name(final.name + f".tmp{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, separators=(",", ":"))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
    return final


def load_take(path: Path) -> Take:
    try:
        with path.open(encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise TakeError(f"{path.name}: {e}") from e
    if not isinstance(doc, dict) or doc.get("magicam_take") not in (1, TAKE_FORMAT):
        raise TakeError(f"{path.name}: non e' una take MagiCAM (formati 1-{TAKE_FORMAT})")
    rows = doc.get("samples")
    if not isinstance(rows, list):
        raise TakeError(f"{path.name}: campioni assenti")
    samples = tuple(_row_to_sample(r) for r in rows)
    for a, b in pairwise(samples):
        if b.t <= a.t:
            raise TakeError(f"{path.name}: tempo non crescente a t={b.t}")
    meta = doc.get("metadata") or {}
    if not isinstance(meta, dict):
        raise TakeError(f"{path.name}: metadata non e' un oggetto")
    return Take(str(doc.get("name", path.stem)), samples, meta)


class TakeLibrary:
    """La cartella delle take accanto alla scena. Niente si cancella: `discard` sposta in `_cestino/`."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def list(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(p for p in self.folder.iterdir() if p.name.endswith(TAKE_SUFFIX) and p.is_file())

    def save(self, take: Take) -> Path:
        return save_take(take, take_path(self.folder, take.name))

    def load(self, path: Path) -> Take:
        return load_take(path)

    def discard(self, path: Path) -> Path:
        if path.parent != self.folder:
            raise TakeError(f"{path} non sta nella libreria {self.folder}")
        cestino = self.folder / CESTINO
        cestino.mkdir(exist_ok=True)
        dest = cestino / f"{int(time.time())}_{path.name}"
        shutil.move(str(path), str(dest))
        return dest


def default_take_folder(scene_path: str | None, home: Path | None = None) -> Path:
    """Accanto alla scena salvata (`<cartella>/magicam_takes`), altrimenti `~/Documents/magicam_takes`."""
    if scene_path:
        return Path(scene_path).resolve().parent / "magicam_takes"
    return (home or Path.home()) / "Documents" / "magicam_takes"


def _nearest_turn(a: float, prev: float) -> float:
    """`a` spostato di multipli di 360 per stare entro 180 da `prev`."""
    return a - 360.0 * round((a - prev) / 360.0)


def _euler_distance(c: tuple[float, float, float], prev: tuple[float, float, float]) -> float:
    """Somma dei salti (gradi) fra una terna candidata e la precedente, ogni asse al giro piu' vicino."""
    return sum(abs(_nearest_turn(v, p) - p) for v, p in zip(c, prev, strict=True))


def euler_unwrap_deg(angles: Sequence[float]) -> list[float]:
    """Angoli in gradi resi CONTINUI: ogni valore si sposta di multipli di 360 per stare entro 180 dal precedente.

    Le curve di Maya interpolano i numeri, non le rotazioni: −179 → +179 sarebbe un giro intero in un fotogramma.
    """
    out: list[float] = []
    for a in angles:
        if out:
            prev = out[-1]
            a = a - 360.0 * round((a - prev) / 360.0)
        out.append(a)
    return out


def channel_curves(
    keys: Sequence[Keyframe], unit_per_meter: float, focal_scale_mm_per_px: float | None = None
) -> dict[str, list[float]]:
    """Dalle chiavi ai valori per canale di Maya: translate (unita' interne), rotate XYZ (gradi, continui),
    focalLength (mm) se c'e' la scala focale. Python puro: la scrittura in blocco la fa maya_bridge."""
    tx: list[float] = []
    ty: list[float] = []
    tz: list[float] = []
    rx: list[float] = []
    ry: list[float] = []
    rz: list[float] = []
    focal: list[float] = []
    for k in keys:
        px, py, pz = k.camera.pos
        tx.append(px * unit_per_meter)
        ty.append(py * unit_per_meter)
        tz.append(pz * unit_per_meter)
        # Due terne XYZ danno la stessa rotazione: (x, y, z) e (x+180, 180−y, z+180). Si sceglie quella piu' vicina
        # alla chiave precedente (come l'Euler filter di Maya), altrimenti uno yaw che passa 90° fa saltare x e z a 180.
        ex, ey, ez = quat_to_euler_xyz_deg(k.camera.quat)
        candidates = ((ex, ey, ez), (ex + 180.0, 180.0 - ey, ez + 180.0))
        if rx:
            prev = (rx[-1], ry[-1], rz[-1])
            ex, ey, ez = min(candidates, key=functools.partial(_euler_distance, prev=prev))
            ex, ey, ez = _nearest_turn(ex, prev[0]), _nearest_turn(ey, prev[1]), _nearest_turn(ez, prev[2])
        rx.append(ex)
        ry.append(ey)
        rz.append(ez)
        if focal_scale_mm_per_px is not None:
            focal.append(k.focal_px * focal_scale_mm_per_px)
    curves = {
        "translateX": tx,
        "translateY": ty,
        "translateZ": tz,
        "rotateX": rx,  # gia' continui: scelta del candidato + giro piu' vicino, chiave per chiave
        "rotateY": ry,
        "rotateZ": rz,
    }
    if focal_scale_mm_per_px is not None and any(f > 0 for f in focal):
        curves["focalLength"] = focal
    return curves


def iter_frames(keys: Iterable[Keyframe]) -> Iterable[int]:
    for k in keys:
        yield k.frame
