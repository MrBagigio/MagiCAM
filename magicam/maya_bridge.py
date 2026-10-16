"""L'UNICO modulo che importa `maya`. Un timer sul main thread legge l'ultima posa e la applica alla camera.

Niente `evalDeferred` per pacchetto, niente `cmds` da thread di fondo: il receiver riempie, il tick svuota.

Regia dal vivo (2026-10-16, docs/VALUTAZIONE_REGIA_LIVE.md):
- R1 la take si aggancia alla timeline: il tick scrive nel campione il fotogramma a video; con `rec_plays_timeline`
  il Rec fa partire il playback in tempo reale dall'inizio del range e la take si ferma quando il playback finisce.
- R2 la camera dal vivo non ha animazione (se ne ha, `start` rifiuta) e ogni take si cuoce su una camera NUOVA nel
  gruppo `magicam_takes_grp`: niente lotta fra curve e dal vivo, niente coda della take precedente.
- R3 se la camera sparisce, la scena cambia o il tick fallisce, il ponte si ferma UNA volta, salva la take e lo
  dice (`fault`), invece di un errore per tick.
"""

from __future__ import annotations

import logging
import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magicam import protocol
from magicam.discovery import Advertiser
from magicam.math3d import Transform, from_maya_matrix, to_maya_matrix
from magicam.protocol import Command, CommandMessage, PoseMessage, StatsFlag, StatsMessage
from magicam.receiver import Receiver
from magicam.session import Hold, Session
from magicam.takes import (
    Keyframe,
    Take,
    TakeLibrary,
    TakeRecorder,
    channel_curves,
    default_take_folder,
    fps_from_maya_time_unit,
    keys_for_take,
    resample,
)

log = logging.getLogger("magicam.maya_bridge")

# unita' lineari di Maya -> unita' per metro
UNITS_PER_METER: dict[str, float] = {
    "mm": 1000.0,
    "cm": 100.0,
    "m": 1.0,
    "in": 39.37007874015748,
    "ft": 3.280839895013123,
    "yd": 1.0936132983377078,
}

STATS_PERIOD_S = 0.5
TAKES_GROUP = "magicam_takes_grp"
TRANSFORM_CHANNELS = tuple(f"{a}{x}" for a in ("translate", "rotate") for x in "XYZ")
INTERNAL_UNITS_PER_METER = 100.0  # Maya lavora internamente in cm: xform -matrix usa quelli
DEFAULT_TICK_HZ = 60.0


def _cmds() -> Any:
    import maya.cmds as cmds  # import tardivo: il modulo si importa anche fuori da Maya per i test di forma

    return cmds


def units_per_meter() -> float:
    unit = str(_cmds().currentUnit(q=True, linear=True))
    try:
        return UNITS_PER_METER[unit]
    except KeyError as e:
        raise RuntimeError(f"unita' lineare di Maya non gestita: {unit!r}") from e


@dataclass
class TickStats:
    ticks: int = 0
    applied: int = 0  # tick che hanno mosso la camera
    poses: int = 0  # pose passate a sessione e take (tutte quelle accettate)
    last_cost_ms: float = 0.0
    max_cost_ms: float = 0.0
    applied_hz: float = 0.0
    _window: deque[float] = field(default_factory=lambda: deque(maxlen=120), repr=False)

    def note(self, cost_s: float, applied: bool, now: float) -> None:
        self.ticks += 1
        self.last_cost_ms = cost_s * 1000.0
        self.max_cost_ms = max(self.max_cost_ms, self.last_cost_ms)
        if applied:
            self.applied += 1
            self._window.append(now)
            if len(self._window) >= 2:
                span = self._window[-1] - self._window[0]
                self.applied_hz = (len(self._window) - 1) / span if span > 0 else 0.0


class MayaCameraBridge:
    """Collega Receiver -> Session -> camera di Maya, dal main thread."""

    def __init__(
        self,
        session: Session,
        receiver: Receiver,
        camera: str,
        tick_hz: float = DEFAULT_TICK_HZ,
        drive_lens: bool = True,
        on_state_changed: Callable[[], None] | None = None,
    ) -> None:
        self.session = session
        self.receiver = receiver
        self.camera = camera
        self.tick_hz = tick_hz
        self.drive_lens = drive_lens
        self.on_state_changed = on_state_changed
        self.stats = TickStats()
        self.recorder = TakeRecorder()
        self.take_folder: Path | None = None  # None = accanto alla scena (takes.default_take_folder)
        self.auto_bake = True  # allo stop della take: chiavi sulla camera
        self.last_take_path: Path | None = None
        self.last_bake_keys = 0
        self.advertiser: Advertiser | None = None
        self.advertise = True  # Bonjour, se zeroconf c'e'
        self.link_lost = False  # nessun pacchetto da piu' di STALE_AFTER_S dopo averne ricevuti
        self.live_undo = False  # True = le pose dal vivo entrano nella coda di undo (solo per il contrasto del banco)
        self.rec_plays_timeline = True  # R1: Rec fa partire la timeline (tempo reale, una volta) e lo Stop la ferma
        self.rec_from_range_start = True  # R1: ... dall'inizio del range di playback
        self.fault: str | None = None  # R3: perche' il ponte si e' fermato da solo (None = nessun guasto)
        self.last_error: str | None = None  # ultimo errore di una take (salvataggio, bake): lo mostra il pannello
        self.unsaved_take: Take | None = None  # take ferma ma NON salvata (errore): si puo' riprovare
        self.last_take_camera: str | None = None
        self.last_bake_mode = ""
        self._playing_take = False
        self._saved_playback: dict[str, Any] | None = None
        self._unit = INTERNAL_UNITS_PER_METER
        self._ui_unit = 100.0
        self._timer: Any = None
        self._script_job: int | None = None
        self._applied_seq: int | None = None
        self._commands: deque[CommandMessage] = deque()
        self._last_stats_sent = 0.0
        self._stats_seq = 0
        receiver.on_command = self._queue_command  # chiamata nel thread di rete: solo accoda

    # --- ciclo di vita ---------------------------------------------------------------------------------------

    def start(self) -> None:
        cmds = _cmds()
        if not cmds.objExists(self.camera):
            raise RuntimeError(f"camera '{self.camera}' non esiste")
        driven = self.animated_channels(self.camera)
        if driven:
            # R2, MISURATO il 2026-10-16: con le curve sulla camera, +1 fotogramma la riporta sulla curva (32,9 cm)
            raise RuntimeError(
                f"la camera dal vivo '{self.camera}' ha animazione su {', '.join(driven)}: il telefono non la "
                "comanderebbe in playback. Usa una camera senza chiavi (pulsante Nuova); le take vanno su camere loro."
            )
        self.fault = None
        # MISURATO (F1.1-E, Maya 2026): la lista di xform -matrix e' in cm INTERNI qualunque sia l'unita' della
        # scena (-t invece e' in unita' della UI). Il banco a metri lo aveva mostrato: camera mossa di 1/100.
        self._unit = INTERNAL_UNITS_PER_METER
        self._ui_unit = units_per_meter()
        if not self.receiver.running:
            self.receiver.start()
        self._start_timer()
        self._start_scene_watch()
        if self.advertise:
            self.advertiser = Advertiser(self.receiver.port)
            self.advertiser.start()
        log.info("bridge avviato su %s (%.0f Hz, %s unita'/m)", self.camera, self.tick_hz, self._unit)

    def stop(self, save_take: bool = True) -> None:
        """Ferma tutto. Una take in corso si salva (e si cuoce se la scena e' sana): chiudere il pannello a meta' take
        prima la perdeva (i campioni restavano in un registratore che nessuno leggeva piu')."""
        self._stop_timer()
        self._stop_scene_watch()
        if save_take and self.recorder.recording:
            self._stop_take_safely(bake=self.fault is None)
        self._end_playback()
        if self.advertiser is not None:
            self.advertiser.stop()
            self.advertiser = None
        self.receiver.stop()

    # --- R3: guasti -------------------------------------------------------------------------------------------

    def _fail(self, reason: str, bake: bool = False) -> None:
        """Ferma il ponte UNA volta, salva la take e lascia scritto perche'. Mai un'eccezione per tick."""
        if self.fault is not None and not self.receiver.running:
            return
        self.fault = reason
        log.error("MagiCAM fermo: %s", reason)
        self._stop_timer()
        self._stop_scene_watch()
        if self.recorder.recording:
            self._stop_take_safely(bake=bake)
        self._end_playback()
        if self.advertiser is not None:
            self.advertiser.stop()
            self.advertiser = None
        self.receiver.stop()
        if self.on_state_changed is not None:
            self.on_state_changed()

    def _start_scene_watch(self) -> None:
        # «deleteAll» scatta prima che una scena nuova o aperta svuoti quella di adesso: la take si salva in tempo
        self._scene_jobs = [
            int(_cmds().scriptJob(event=["deleteAll", self._on_scene_cleared], runOnce=True)),
        ]

    def _stop_scene_watch(self) -> None:
        jobs = getattr(self, "_scene_jobs", [])
        if not jobs:
            return  # niente da togliere: non si interroga Maya (un guasto si deve poter chiudere anche senza)
        cmds = _cmds()
        for job in jobs:
            if cmds.scriptJob(exists=job):
                cmds.scriptJob(kill=job, force=True)
        self._scene_jobs = []

    def _on_scene_cleared(self) -> None:
        self._scene_jobs = []  # runOnce: il job se ne va da solo, non lo si uccide dall'interno della sua chiamata
        self._fail("scena nuova o aperta: collegamento fermato, take salvata senza chiavi")

    @staticmethod
    def animated_channels(node: str) -> list[str]:
        """I canali di trasformazione che qualcosa pilota (curve, vincoli, espressioni)."""
        cmds = _cmds()
        out = []
        for ch in TRANSFORM_CHANNELS:
            if cmds.listConnections(f"{node}.{ch}", source=True, destination=False, skipConversionNodes=True):
                out.append(ch)
        return out

    # --- pairing (F4.1) ------------------------------------------------------------------------------------------

    @staticmethod
    def new_token() -> int:
        """Codice a 6 cifre da leggere sul pannello e scrivere sul telefono."""
        return 100000 + secrets.randbelow(900000)

    def require_token(self, token: int | None) -> None:
        """None = chiunque sulla LAN; un intero = solo i mittenti che mandano PING/comandi con quel token."""
        self.receiver.expected_token = token

    def _start_timer(self) -> None:
        try:
            from PySide6.QtCore import Qt, QTimer
        except ImportError:  # Maya 2024
            try:
                from PySide2.QtCore import Qt, QTimer
            except ImportError:
                QTimer = None  # noqa: N806
                Qt = None  # noqa: N806
        if QTimer is not None:
            t = QTimer()
            # MISURATO in Maya 2026 (F1.8): l'enum e' Qt.TimerType, non QTimer.TimerType; PySide2: Qt.PreciseTimer
            precise = getattr(Qt, "TimerType", Qt).PreciseTimer
            t.setTimerType(precise)
            t.timeout.connect(self.tick)
            t.start(round(1000.0 / self.tick_hz))
            self._timer = t
        else:
            # ripiego: idle event. Gira piu' spesso del necessario; il tick scarta le pose gia' applicate.
            self._script_job = int(_cmds().scriptJob(event=["idle", self.tick]))

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._script_job is not None:
            cmds = _cmds()
            if cmds.scriptJob(exists=self._script_job):
                cmds.scriptJob(kill=self._script_job, force=True)
            self._script_job = None

    # --- il tick (main thread) -------------------------------------------------------------------------------

    def tick(self) -> None:
        t0 = time.perf_counter()
        applied = False
        try:
            cmds = _cmds()
            if not cmds.objExists(self.camera):
                # R3, MISURATO prima della cura: 59 eccezioni in 1 s, una per tick, e il pannello diceva «dal vivo»
                self._fail(f"la camera '{self.camera}' non c'e' piu': take salvata senza chiavi")
                return
            self._drain_commands()
            if self._playing_take and self.recorder.recording and not cmds.play(q=True, state=True):
                # R1: il playback e' finito (fine del range) o il regista l'ha fermato: fine della take
                self._stop_take_safely(bake=True)
            pending = self.receiver.drain_recent()
            if pending:
                # ogni posa passa da sessione (filtro a dt regolare) e take; la camera prende solo l'ultima.
                # R1: il fotogramma a video va all'ULTIMA posa del tick, quella che la camera prende davvero.
                # MISURATO (banco del 2026-10-16): una testina spostata A MANO durante la take (37 -> 100) veniva
                # presa per un playback e 2 s di moto finivano stesi su 64 fotogrammi. Il fotogramma conta solo
                # mentre Maya sta davvero riproducendo.
                playing = self.recorder.recording and bool(cmds.play(q=True, state=True))
                frame = float(cmds.currentTime(q=True)) if playing else None
                last_cam = None
                for j, msg in enumerate(pending):
                    cam = self.session.update(msg)
                    self.recorder.add(msg, cam, frame if j == len(pending) - 1 else None)
                    if cam is not None:
                        last_cam = cam
                msg = pending[-1]
                self._applied_seq = msg.seq
                self.stats.poses += len(pending)
                if last_cam is not None:
                    self._apply(last_cam, msg)
                    applied = True
            st = self.receiver.stats
            self.link_lost = st.last_recv_mono is not None and st.is_stale(time.perf_counter())
            self._maybe_send_stats()
        except Exception as e:  # R3: un guasto ferma il ponte una volta, non un errore per tick
            log.exception("tick")
            self._fail(f"errore nel tick: {e}")
        finally:
            self.stats.note(time.perf_counter() - t0, applied, time.perf_counter())

    def _apply(self, cam: Transform, msg: PoseMessage) -> None:
        cmds = _cmds()
        # Le pose dal vivo NON entrano nella coda di undo (60 al secondo, e con la coda infinita del Maya
        # dell'utente — misurata il 2026-10-15 — erano 36000 voci in dieci minuti): stateWithoutFlush spegne la
        # registrazione senza buttare cio' che l'artista ha gia' in coda. `live_undo=True` solo per il contrasto.
        if not self.live_undo:
            cmds.undoInfo(stateWithoutFlush=False)
        try:
            cmds.xform(self.camera, ws=True, matrix=to_maya_matrix(cam, self._unit))
            if self.drive_lens and msg.focal_px > 0 and msg.image_w > 0:
                shape = self._shape()
                if shape is not None:
                    hfa_in = float(cmds.getAttr(f"{shape}.horizontalFilmAperture"))
                    focal_mm = msg.focal_px * hfa_in * 25.4 / msg.image_w
                    cmds.setAttr(f"{shape}.focalLength", focal_mm)
        finally:
            if not self.live_undo:
                cmds.undoInfo(stateWithoutFlush=True)

    def _shape(self) -> str | None:
        cmds = _cmds()
        shapes = cmds.listRelatives(self.camera, shapes=True, type="camera") or []
        return str(shapes[0]) if shapes else None

    # --- comandi (dal telefono, dalla UI) ----------------------------------------------------------------------

    def _queue_command(self, msg: CommandMessage, addr: tuple[str, int]) -> None:
        self._commands.append(msg)

    def _drain_commands(self) -> None:
        while self._commands:
            msg = self._commands.popleft()
            self.handle_command(msg.cmd, msg.value)

    def handle_command(self, cmd: Command, value: float = 0.0) -> None:
        if cmd is Command.CALIBRATE:
            self.calibrate()
        elif cmd is Command.RECENTER:
            self.session.recenter()
        elif cmd is Command.FREEZE:
            self.session.freeze()
        elif cmd is Command.UNFREEZE:
            self.session.unfreeze()
        elif cmd is Command.SCALE_SET:
            self.session.set_scale(value)
        elif cmd is Command.REC_START:
            if not self.recorder.recording:
                self.start_take()
        elif cmd is Command.REC_STOP:
            if self.recorder.recording:
                self._stop_take_safely(bake=True)
        elif cmd is Command.PING:
            pass
        if self.on_state_changed is not None:
            self.on_state_changed()

    def calibrate(self) -> bool:
        """La posa ATTUALE del telefono si lega alla posa ATTUALE della camera di Maya."""
        latest = self.receiver.latest()
        if latest is None:
            log.warning("calibrazione: nessuna posa dal telefono")
            return False
        msg, _ = latest
        self.session.calibrate(Transform(msg.pos, msg.quat), self.camera_world())
        return True

    # --- take (F3) ------------------------------------------------------------------------------------------------

    def scene_fps(self) -> float:
        return fps_from_maya_time_unit(str(_cmds().currentUnit(q=True, time=True)))

    def take_library(self) -> TakeLibrary:
        folder = self.take_folder
        if folder is None:
            scene = _cmds().file(q=True, sceneName=True) or None
            folder = default_take_folder(scene)
        return TakeLibrary(folder)

    def start_take(self, name: str = "") -> None:
        cmds = _cmds()
        self.last_error = None
        if self.rec_plays_timeline:
            self._begin_playback()
        self.recorder.start(name, frame=float(cmds.currentTime(q=True)))
        log.info("take «%s»: registrazione dal fotogramma %s", self.recorder.name, self.recorder.rec_frame)

    def stop_take(self, bake: bool | None = None) -> Path:
        """Ferma, salva la take GREZZA (atomico, mai sovrascrive) e, se auto_bake, la cuoce su una camera NUOVA.

        Il salvataggio viene prima di tutto: se poi il bake fallisce, la take e' gia' su disco. Se fallisce il
        salvataggio, la take resta in `unsaved_take` (si puo' riprovare con `save_unsaved_take`)."""
        cmds = _cmds()
        self._end_playback()
        take = self.recorder.stop(
            {
                "scene": cmds.file(q=True, sceneName=True) or "",
                "scene_fps": self.scene_fps(),
                "units_per_meter": self._unit,
                "camera": self.camera,
                "scale": self.session.scale,
            }
        )
        self.unsaved_take = take
        path = self.take_library().save(take)
        self.unsaved_take = None
        self.last_take_path = path
        log.info("take «%s»: %d campioni, %.2f s -> %s", take.name, len(take.samples), take.duration, path)
        if self.auto_bake if bake is None else bake:
            self.last_bake_keys = self.bake_take(take)
        return path

    def save_unsaved_take(self) -> Path | None:
        if self.unsaved_take is None:
            return None
        path = self.take_library().save(self.unsaved_take)
        self.unsaved_take = None
        self.last_take_path = path
        return path

    def _stop_take_safely(self, bake: bool) -> Path | None:
        """Stop da telefono, da fine playback, da guasto: l'errore si scrive in `last_error`, non si perde nel log."""
        try:
            return self.stop_take(bake=bake and self.auto_bake)
        except Exception as e:  # lo stop non deve mai lasciare una take senza traccia
            self.last_error = f"take: {e}"
            log.exception("stop della take")
            if self.recorder.recording:
                self.recorder.recording = False
            return None
        finally:
            if self.on_state_changed is not None:
                self.on_state_changed()

    # --- R1: playback durante la take ------------------------------------------------------------------------

    def _begin_playback(self) -> None:
        """Playback in tempo reale, una volta, dall'inizio del range. MISURATO in Maya 2026: `play` torna in 2 ms e
        il timer del ponte scatta una volta per fotogramma; con `playbackSpeed=0` (il «tutti i fotogrammi» della
        scena dell'utente) il playback non e' a tempo reale, quindi si mette 1 e alla fine si rimette com'era."""
        cmds = _cmds()
        self._saved_playback = {
            "loop": cmds.playbackOptions(q=True, loop=True),
            "playbackSpeed": cmds.playbackOptions(q=True, playbackSpeed=True),
        }
        cmds.playbackOptions(loop="once", playbackSpeed=1.0)
        if self.rec_from_range_start:
            cmds.currentTime(cmds.playbackOptions(q=True, minTime=True))
        cmds.play(forward=True, state=True)
        self._playing_take = True

    def _end_playback(self) -> None:
        if not self._playing_take and self._saved_playback is None:
            return
        cmds = _cmds()
        if self._playing_take and cmds.play(q=True, state=True):
            cmds.play(state=False)
        self._playing_take = False
        if self._saved_playback is not None:
            cmds.playbackOptions(**self._saved_playback)
            self._saved_playback = None

    def take_camera(self, take: Take) -> str:
        """R2: una camera NUOVA per la take, copia della camera dal vivo (obiettivo, dorso), figlia del gruppo delle
        take a origine e scala 1: i valori cotti sono nel mondo, e una camera dal vivo dentro un rig non li falsa."""
        cmds = _cmds()
        if not cmds.objExists(TAKES_GROUP):
            cmds.group(empty=True, name=TAKES_GROUP, world=True)
        safe = "".join(c if c.isalnum() or c == "_" else "_" for c in take.name).strip("_") or "take"
        if safe[0].isdigit():
            safe = f"take_{safe}"
        dup = cmds.duplicate(self.camera, name=f"{safe}_cam", returnRootsOnly=True, inputConnections=False)[0]
        for ch in (*TRANSFORM_CHANNELS, "scaleX", "scaleY", "scaleZ"):
            cmds.setAttr(f"{dup}.{ch}", lock=False)
        extra = [
            c for c in (cmds.listRelatives(dup, children=True, fullPath=True) or []) if cmds.nodeType(c) != "camera"
        ]
        if extra:
            cmds.delete(extra)
        dup = cmds.parent(dup, TAKES_GROUP)[0]
        cmds.setAttr(f"{dup}.scale", 1, 1, 1, type="double3")
        return str(dup)

    def bake_take(
        self, take: Take, camera: str | None = None, fps: float | None = None, start_frame: int | None = None
    ) -> int:
        """Una chiave per fotogramma in un solo blocco di undo. Torna quante.

        Senza `camera`, su una camera NUOVA (R2, `take_camera`). Fotogrammi: quelli che la timeline ha mostrato
        durante la take (R1), altrimenti dal fotogramma del Rec; `start_frame` li forza «a tempo» da li'."""
        cmds = _cmds()
        fps = fps or self.scene_fps()
        if start_frame is not None:
            keys, mode = resample(take, fps, start_frame), "tempo"
        else:
            keys, mode = keys_for_take(take, fps, fallback_start=round(float(cmds.currentTime(q=True))))
        if not keys:
            return 0
        cmds.undoInfo(openChunk=True, chunkName="MagiCAM take")
        try:
            cam = camera or self.take_camera(take)
            n = self._bake_keys(take, keys, cam)
        finally:
            cmds.undoInfo(closeChunk=True)
        self.last_take_camera = cam
        self.last_bake_mode = mode
        log.info(
            "take «%s»: %d chiavi (%s) su %s, fotogrammi %d-%d", take.name, n, mode, cam, keys[0].frame, keys[-1].frame
        )
        return n

    def _bake_keys(self, take: Take, keys: list[Keyframe], cam: str) -> int:
        cmds = _cmds()
        if not cmds.objExists(cam):
            raise RuntimeError(f"camera '{cam}' non esiste")
        shapes = cmds.listRelatives(cam, shapes=True, type="camera") or []
        shape = str(shapes[0]) if shapes else None
        hfa_in = float(cmds.getAttr(f"{shape}.horizontalFilmAperture")) if shape else 0.0
        image_w = next((s.image_w for s in take.samples if s.image_w > 0), 0)
        focal_scale = (hfa_in * 25.4 / image_w) if (self.drive_lens and shape and image_w > 0) else None
        rotate_order = int(cmds.getAttr(f"{cam}.rotateOrder"))
        curves = channel_curves(keys, self._unit, focal_scale)
        if rotate_order != 0:
            curves = self._reorder_euler(curves, rotate_order)
        # Le chiavi si scrivono IN BLOCCO con l'API (MFnAnimCurve.addKeys): il primo bake faceva xform + setKeyframe
        # per fotogramma e su 14401 chiavi non finiva piu' (F4.5, 2026-10-15). Le curve NUOVE nascono dentro il
        # blocco di undo del chiamante (createNode + connectAttr), quindi l'undo le toglie con tutte le chiavi; su una
        # curva che esisteva gia' le chiavi aggiunte dall'API NON sono annullabili: lo si dice nel log.
        for attr, values in curves.items():
            node, plug = (shape, "focalLength") if attr == "focalLength" else (cam, attr)
            if node is None:
                continue
            self._write_curve(f"{node}.{plug}", attr, [k.frame for k in keys], values)
        return len(keys)

    @staticmethod
    def _reorder_euler(curves: dict[str, list[float]], rotate_order: int) -> dict[str, list[float]]:
        """Da XYZ (gradi) all'ordine di rotazione della camera, con l'API; poi di nuovo continui."""
        import maya.api.OpenMaya as om  # noqa: N813 - alias di uso comune in Maya

        from magicam.takes import euler_unwrap_deg

        rx, ry, rz = curves["rotateX"], curves["rotateY"], curves["rotateZ"]
        out_x: list[float] = []
        out_y: list[float] = []
        out_z: list[float] = []
        for x, y, z in zip(rx, ry, rz, strict=True):
            e = om.MEulerRotation(math.radians(x), math.radians(y), math.radians(z), om.MEulerRotation.kXYZ)
            r = e.reorder(rotate_order)
            out_x.append(math.degrees(r.x))
            out_y.append(math.degrees(r.y))
            out_z.append(math.degrees(r.z))
        new = dict(curves)
        new["rotateX"], new["rotateY"], new["rotateZ"] = (
            euler_unwrap_deg(out_x),
            euler_unwrap_deg(out_y),
            euler_unwrap_deg(out_z),
        )
        return new

    def _write_curve(self, plug_name: str, attr: str, frames: list[int], values: list[float]) -> None:
        import maya.api.OpenMaya as om  # noqa: N813 - alias di uso comune in Maya
        import maya.api.OpenMayaAnim as oma  # noqa: N813

        cmds = _cmds()
        sel = om.MSelectionList()
        sel.add(plug_name)
        plug = sel.getPlug(0)
        if plug.isDestination:
            src = plug.source().node()
            if not src.hasFn(om.MFn.kAnimCurve):
                raise RuntimeError(f"{plug_name} e' pilotato da un nodo che non e' una curva: non ci cuocio sopra")
            fn = oma.MFnAnimCurve(src)
            log.warning("%s: curva esistente, le chiavi aggiunte non sono annullabili con undo", plug_name)
        else:
            curve_type = (
                "animCurveTA"
                if attr.startswith("rotate")
                else "animCurveTL"
                if attr.startswith("translate")
                else "animCurveTU"
            )
            node = cmds.createNode(curve_type, name=f"{plug_name.replace('.', '_')}_magicam")
            cmds.connectAttr(f"{node}.output", plug_name)
            sel2 = om.MSelectionList()
            sel2.add(node)
            fn = oma.MFnAnimCurve(sel2.getDependNode(0))
        unit = om.MTime.uiUnit()
        times = om.MTimeArray([om.MTime(float(f), unit) for f in frames])
        if attr.startswith("rotate"):
            vals = om.MDoubleArray([math.radians(v) for v in values])  # animCurveTA: radianti interni
        else:
            vals = om.MDoubleArray(values)
        fn.addKeys(times, vals, oma.MFnAnimCurve.kTangentGlobal, oma.MFnAnimCurve.kTangentGlobal, True)

    def camera_world(self) -> Transform:
        m = list(_cmds().xform(self.camera, q=True, ws=True, matrix=True))
        return from_maya_matrix(m, self._unit)

    # --- stats verso il telefono ---------------------------------------------------------------------------------

    def _maybe_send_stats(self) -> None:
        now = time.perf_counter()
        if now - self._last_stats_sent < STATS_PERIOD_S:
            return
        self._last_stats_sent = now
        st = self.receiver.stats
        s = self.session.state()
        flags = 0
        if s.calibrated:
            flags |= StatsFlag.CALIBRATED
        if s.frozen:
            flags |= StatsFlag.FROZEN
        if self.recorder.recording:
            flags |= StatsFlag.RECORDING
        if s.hold is Hold.TRACKING:
            flags |= StatsFlag.TRACKING_BAD
        self._stats_seq += 1
        msg = StatsMessage(self._stats_seq, now, st.received, st.lost, st.latency_ms, flags)
        self.receiver.send_to_sender(protocol.pack_stats(msg))
