"""Stato della sessione dell'operatore: ancora, scala, freeze, recenter, blocchi d'asse, filtro.

Python puro. `Session.update(pose)` restituisce la posa della camera in metri nel mondo di Maya, o None quando la
camera non deve muoversi (non calibrata, freeze, tracking non normale). Il bridge applica, la UI legge `state()`.

Senza salto (F4.3, F4.4): quando il tracking torna normale dopo un'interruzione, o quando fra due pose passa piu'
di `gap_threshold_s` (Wi-Fi caduto), la camera riparte da dov'e' — ancora = ultima posa applicata, calib = posa
attuale del telefono — perche' nel frattempo il mondo ARKit o l'operatore possono essersi spostati.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from magicam.filters import OneEuroQuat, OneEuroVec3
from magicam.math3d import Transform, apply_anchor
from magicam.protocol import PoseMessage

log = logging.getLogger("magicam.session")

DEFAULT_GAP_THRESHOLD_S = 0.5


class Hold(Enum):
    """Perche' la camera non si muove."""

    NONE = "ok"
    NOT_CALIBRATED = "non calibrata"
    FROZEN = "freeze"
    TRACKING = "tracking non normale"


@dataclass
class AxisLocks:
    height: bool = False  # Y della camera fissa all'ancora
    dolly: bool = False  # XZ fissi (solo rotazione)
    roll: bool = False  # roll azzerato (F5, qui solo il flag)


@dataclass
class SessionState:
    calibrated: bool
    frozen: bool
    scale: float
    hold: Hold
    tracking_ok: bool
    last_camera: Transform | None
    reanchors: int  # quante volte la sessione e' ripartita senza salto (tracking, buchi, unfreeze, scala)


@dataclass
class Session:
    scale: float = 1.0
    locks: AxisLocks = field(default_factory=AxisLocks)
    filter_enabled: bool = True
    gap_threshold_s: float = DEFAULT_GAP_THRESHOLD_S
    pos_filter: OneEuroVec3 = field(default_factory=OneEuroVec3)
    rot_filter: OneEuroQuat = field(default_factory=OneEuroQuat)
    _anchor: Transform | None = None
    _calib: Transform | None = None
    _frozen: bool = False
    _last_phone: Transform | None = None
    _last_camera: Transform | None = None
    _last_t: float | None = None
    _tracking_ok: bool = True
    _reanchors: int = 0

    # --- comandi dell'operatore ---------------------------------------------------------------------------------

    def calibrate(self, phone: Transform, camera_now: Transform) -> None:
        """Da qui in avanti il moto del telefono rispetto a `phone` muove la camera a partire da `camera_now`."""
        self._calib = phone
        self._anchor = camera_now
        self._last_camera = camera_now
        self._frozen = False
        self._reset_filters()
        log.info("calibrata: ancora %s", camera_now)

    def recenter(self) -> bool:
        """Riporta la camera sull'ancora senza spostarla: la posa ATTUALE del telefono diventa la nuova calib."""
        if self._anchor is None or self._last_phone is None:
            return False
        self._calib = self._last_phone
        self._reset_filters()
        return True

    def freeze(self) -> None:
        self._frozen = True

    def unfreeze(self) -> bool:
        """Rilascia senza salto: la camera dov'e' adesso diventa la nuova ancora, il telefono dov'e' la nuova calib."""
        if not self._frozen:
            return False
        self._frozen = False
        self._reanchor_here()
        return True

    def set_scale(self, scale: float) -> None:
        if scale <= 0.0:
            raise ValueError("scala > 0")
        self._reanchor_here()  # cambia scala senza salto
        self.scale = scale

    def reset(self) -> None:
        self._anchor = None
        self._calib = None
        self._frozen = False
        self._last_camera = None
        self._last_t = None
        self._reset_filters()

    # --- flusso ------------------------------------------------------------------------------------------------

    def update(self, msg: PoseMessage) -> Transform | None:
        """Posa della camera (metri, mondo Maya) per questa posa del telefono, o None se la camera deve stare ferma."""
        phone = Transform(msg.pos, msg.quat)
        was_ok = self._tracking_ok
        self._tracking_ok = msg.tracking_ok
        gap_s = 0.0 if self._last_t is None else msg.t_sensor - self._last_t
        self._last_t = msg.t_sensor
        if self._anchor is not None and msg.tracking_ok and ((not was_ok) or gap_s > self.gap_threshold_s):
            # il tracking e' tornato, o c'e' stato un buco: la camera riparte da dov'e', col telefono dov'e' ORA
            self._last_phone = phone
            self._reanchor_here()
            log.info("ri-ancorata senza salto (%s)", f"buco di {gap_s:.2f} s" if was_ok else "tracking tornato")
        self._last_phone = phone
        if self.hold() is not Hold.NONE:
            return None
        assert self._anchor is not None and self._calib is not None
        cam = apply_anchor(self._anchor, self.scale, self._calib, phone)
        if self.filter_enabled:
            cam = Transform(
                self.pos_filter.filter(cam.pos, msg.t_sensor), self.rot_filter.filter(cam.quat, msg.t_sensor)
            )
        cam = self._apply_locks(cam)
        self._last_camera = cam
        return cam

    def hold(self) -> Hold:
        if self._anchor is None or self._calib is None:
            return Hold.NOT_CALIBRATED
        if self._frozen:
            return Hold.FROZEN
        if not self._tracking_ok:
            return Hold.TRACKING
        return Hold.NONE

    def state(self) -> SessionState:
        return SessionState(
            calibrated=self._anchor is not None,
            frozen=self._frozen,
            scale=self.scale,
            hold=self.hold(),
            tracking_ok=self._tracking_ok,
            last_camera=self._last_camera,
            reanchors=self._reanchors,
        )

    @property
    def last_camera(self) -> Transform | None:
        return self._last_camera

    # --- interni -----------------------------------------------------------------------------------------------

    def _reanchor_here(self) -> None:
        if self._anchor is None or self._last_camera is None or self._last_phone is None:
            return
        self._anchor = self._last_camera
        self._calib = self._last_phone
        self._reanchors += 1
        self._reset_filters()

    def _apply_locks(self, cam: Transform) -> Transform:
        if self._anchor is None:
            return cam
        px, py, pz = cam.pos
        if self.locks.height:
            py = self._anchor.pos[1]
        if self.locks.dolly:
            px, pz = self._anchor.pos[0], self._anchor.pos[2]
        return cam.with_pos((px, py, pz))

    def _reset_filters(self) -> None:
        self.pos_filter.reset()
        self.rot_filter.reset()
