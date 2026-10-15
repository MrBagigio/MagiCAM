"""L'UNICO modulo che importa `maya`. Un timer sul main thread legge l'ultima posa e la applica alla camera.

Niente `evalDeferred` per pacchetto, niente `cmds` da thread di fondo: il receiver riempie, il tick svuota.
SCRITTO, NON ESEGUITO IN MAYA (F1.8): misure di coda e costo per tick da fare con la farm ferma.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magicam import protocol
from magicam.math3d import Transform, from_maya_matrix, to_maya_matrix
from magicam.protocol import Command, CommandMessage, PoseMessage, StatsFlag, StatsMessage
from magicam.receiver import Receiver
from magicam.session import Hold, Session
from magicam.takes import Take, TakeLibrary, TakeRecorder, default_take_folder, fps_from_maya_time_unit, resample

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
    applied: int = 0
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
        self._unit = 100.0
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
        self._unit = units_per_meter()
        if not self.receiver.running:
            self.receiver.start()
        self._start_timer()
        log.info("bridge avviato su %s (%.0f Hz, %s unita'/m)", self.camera, self.tick_hz, self._unit)

    def stop(self) -> None:
        self._stop_timer()
        self.receiver.stop()

    def _start_timer(self) -> None:
        try:
            from PySide6.QtCore import QTimer
        except ImportError:  # Maya 2024
            try:
                from PySide2.QtCore import QTimer
            except ImportError:
                QTimer = None  # noqa: N806
        if QTimer is not None:
            t = QTimer()
            t.setTimerType(QTimer.TimerType.PreciseTimer)
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
            self._drain_commands()
            latest = self.receiver.latest()
            if latest is not None:
                msg, _ = latest
                if msg.seq != self._applied_seq:
                    self._applied_seq = msg.seq
                    cam = self.session.update(msg)
                    if cam is not None:
                        self._apply(cam, msg)
                        applied = True
                    self.recorder.add(msg, cam)  # cam=None (hold): la take tiene l'ultima posa
            self._maybe_send_stats()
        except Exception:
            log.exception("tick")
            raise
        finally:
            self.stats.note(time.perf_counter() - t0, applied, time.monotonic())

    def _apply(self, cam: Transform, msg: PoseMessage) -> None:
        cmds = _cmds()
        cmds.xform(self.camera, ws=True, matrix=to_maya_matrix(cam, self._unit))
        if self.drive_lens and msg.focal_px > 0 and msg.image_w > 0:
            shape = self._shape()
            if shape is not None:
                hfa_in = float(cmds.getAttr(f"{shape}.horizontalFilmAperture"))
                focal_mm = msg.focal_px * hfa_in * 25.4 / msg.image_w
                cmds.setAttr(f"{shape}.focalLength", focal_mm)

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
                self.stop_take()
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
        self.recorder.start(name)
        log.info("take «%s»: registrazione", self.recorder.name)

    def stop_take(self) -> Path:
        """Ferma, salva la take GREZZA (atomico, mai sovrascrive) e, se auto_bake, cuoce le chiavi."""
        cmds = _cmds()
        take = self.recorder.stop(
            {
                "scene": cmds.file(q=True, sceneName=True) or "",
                "scene_fps": self.scene_fps(),
                "units_per_meter": self._unit,
                "camera": self.camera,
                "scale": self.session.scale,
            }
        )
        path = self.take_library().save(take)
        self.last_take_path = path
        log.info("take «%s»: %d campioni, %.2f s -> %s", take.name, len(take.samples), take.duration, path)
        if self.auto_bake:
            self.last_bake_keys = self.bake_take(take)
        return path

    def bake_take(
        self, take: Take, camera: str | None = None, fps: float | None = None, start_frame: int | None = None
    ) -> int:
        """Una chiave per fotogramma, dal fotogramma corrente, in un solo blocco di undo. Torna quante."""
        cmds = _cmds()
        cam = camera or self.camera
        if not cmds.objExists(cam):
            raise RuntimeError(f"camera '{cam}' non esiste")
        fps = fps or self.scene_fps()
        start = round(float(cmds.currentTime(q=True))) if start_frame is None else start_frame
        keys = resample(take, fps, start)
        if not keys:
            return 0
        shapes = cmds.listRelatives(cam, shapes=True, type="camera") or []
        shape = str(shapes[0]) if shapes else None
        hfa_in = float(cmds.getAttr(f"{shape}.horizontalFilmAperture")) if shape else 0.0
        image_w = next((s.image_w for s in take.samples if s.image_w > 0), 0)
        cmds.undoInfo(openChunk=True, chunkName="MagiCAM take")
        try:
            for k in keys:
                cmds.xform(cam, ws=True, matrix=to_maya_matrix(k.camera, self._unit))
                cmds.setKeyframe(cam, attribute=["translate", "rotate"], time=k.frame)
                if self.drive_lens and shape and k.focal_px > 0 and image_w > 0:
                    focal_mm = k.focal_px * hfa_in * 25.4 / image_w
                    cmds.setKeyframe(shape, attribute="focalLength", time=k.frame, value=focal_mm)
            # continuita' degli Euler fra fotogrammi (xform puo' saltare da -179 a +179)
            cmds.filterCurve(f"{cam}.rotateX", f"{cam}.rotateY", f"{cam}.rotateZ")
        finally:
            cmds.undoInfo(closeChunk=True)
        log.info("take «%s»: %d chiavi a %.3f fps da %d", take.name, len(keys), fps, start)
        return len(keys)

    def camera_world(self) -> Transform:
        m = list(_cmds().xform(self.camera, q=True, ws=True, matrix=True))
        return from_maya_matrix(m, self._unit)

    # --- stats verso il telefono ---------------------------------------------------------------------------------

    def _maybe_send_stats(self) -> None:
        now = time.monotonic()
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
