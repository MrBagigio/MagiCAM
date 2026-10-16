"""Pannello MagiCAM dentro Maya.

Uso in Maya (o dal pulsante della shelf, vedi `magicam.ui.shelf`):
    from magicam.ui.panel import show
    panel = show(camera="magicam_cam1", port=9000)
Ogni pulsante chiama una funzione di `MayaCameraBridge`/`Session` che ha il suo test fuori da Maya: il pannello
non decide niente, mostra lo stato VERO (contatori del ricevitore, flag della sessione, tick del bridge).
"""

from __future__ import annotations

import contextlib
import logging
import socket
import time
from collections import deque
from typing import Any

from magicam.maya_bridge import MayaCameraBridge
from magicam.receiver import Receiver
from magicam.session import Hold, Session

log = logging.getLogger("magicam.ui")

try:
    from PySide6 import QtCore, QtGui, QtWidgets
except ImportError:  # Maya 2024
    from PySide2 import QtCore, QtGui, QtWidgets

_PANEL: MagiCamPanel | None = None

DEFAULT_CAMERA = "magicam_live"  # R2: la camera che il telefono muove; le take vanno su camere loro
_BUILTIN_CAMERAS = {"persp", "top", "front", "side"}

# colori della spia: un solo posto, letti anche dallo stile
GREY, AMBER, GREEN, RED, TEAL = "#6b7280", "#f2a33a", "#3ccf6e", "#ff4d3d", "#1fd8c9"

_STYLE = f"""
QDialog#MagiCamPanel {{ background: #23272c; }}
QLabel {{ color: #d6dade; }}
QGroupBox {{
    color: #9aa3ad; font-weight: bold; border: 1px solid #3a4048; border-radius: 6px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
QPushButton {{
    background: #353b42; color: #e6e9ec; border: 1px solid #454c55; border-radius: 5px; padding: 6px 10px;
}}
QPushButton:hover {{ background: #3f464e; }}
QPushButton:disabled {{ color: #6b7280; background: #2c3136; }}
QPushButton#primary {{ background: #17736c; border-color: {TEAL}; font-weight: bold; padding: 8px; }}
QPushButton#primary:hover {{ background: #1b8a81; }}
QPushButton#danger {{ background: #7a2a24; border-color: {RED}; font-weight: bold; padding: 8px; }}
QPushButton#rec {{ background: #3a2b2b; border-color: #6e3a36; font-weight: bold; }}
QPushButton#recOn {{ background: {RED}; border-color: #ff8a7f; color: white; font-weight: bold; }}
QPushButton#frozen {{ background: #6b4a16; border-color: {AMBER}; }}
QLabel#title {{ color: white; font-size: 17px; font-weight: bold; }}
QLabel#pill {{ border-radius: 9px; padding: 3px 10px; font-weight: bold; color: #111; }}
QLabel#code {{
    color: {TEAL}; font-family: Consolas, monospace; font-size: 20px; font-weight: bold; letter-spacing: 2px;
}}
QLabel#ip {{ color: white; font-family: Consolas, monospace; font-size: 14px; }}
QLabel#statValue {{ color: white; font-family: Consolas, monospace; font-size: 13px; }}
QLabel#statName {{ color: #8b949e; }}
QLabel#hint {{ color: #8b949e; }}
"""


def _maya_main_window() -> Any:
    try:
        from maya import OpenMayaUI

        try:
            from shiboken6 import wrapInstance
        except ImportError:
            from shiboken2 import wrapInstance
        ptr = OpenMayaUI.MQtUtil.mainWindow()
        return wrapInstance(int(ptr), QtWidgets.QWidget) if ptr else None
    except ImportError:
        return None


def local_ipv4() -> list[str]:
    """Gli IPv4 di questo PC da scrivere sul telefono: prima le reti di casa (192.168/10/172.16-31), mai il loopback.

    La via che il sistema usa davvero verso la LAN viene per prima (socket UDP «connesso», nessun pacchetto spedito).
    """
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.1.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip not in found:
                found.append(ip)
    except OSError:
        pass

    def rank(ip: str) -> int:
        if ip.startswith("192.168."):
            return 0
        if ip.startswith("10."):
            return 1
        if ip.startswith("172."):
            return 2
        return 3

    out = [ip for ip in found if not ip.startswith("127.") and not ip.startswith("169.254.")]
    return sorted(out, key=lambda ip: (rank(ip), out.index(ip)))


def scene_cameras() -> list[str]:
    """Le camere della scena (transform), quelle di MagiCAM prima, senza le quattro di sistema."""
    try:
        import maya.cmds as cmds
    except ImportError:
        return []
    shapes = cmds.ls(type="camera", long=False) or []
    names: list[str] = []
    for sh in shapes:
        parents = cmds.listRelatives(sh, parent=True) or []
        if parents and parents[0] not in _BUILTIN_CAMERAS and parents[0] not in names:
            names.append(parents[0])
    return sorted(names, key=lambda n: (not n.startswith("magicam"), n.lower()))


def create_camera(name: str = DEFAULT_CAMERA) -> str:
    """Crea una camera MagiCAM a 1,6 m d'altezza (unita' della scena) e restituisce il nome del transform."""
    import maya.cmds as cmds

    from magicam.maya_bridge import units_per_meter

    cam = cmds.camera(name=name)[0]
    if cam != name and not cmds.objExists(name):
        cam = cmds.rename(cam, name)
    upm = units_per_meter()
    cmds.xform(cam, ws=True, t=(0.0, 1.6 * upm, 4.0 * upm))
    return str(cam)


class MagiCamPanel(QtWidgets.QDialog):  # type: ignore[misc]
    def __init__(self, camera: str, port: int, parent: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MagiCAM")
        self.setObjectName("MagiCamPanel")
        self.setStyleSheet(_STYLE)
        self.setMinimumWidth(420)
        self.session = Session()
        self.receiver = Receiver(port=port)
        self.bridge = MayaCameraBridge(self.session, self.receiver, camera, on_state_changed=self.refresh)
        self._rate: deque[tuple[float, int]] = deque(maxlen=8)  # (perf_counter, ricevute) per i Hz veri
        self._build(camera, port)
        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self.refresh)
        self._poll.start(250)
        self.refresh()

    # --- costruzione -------------------------------------------------------------------------------------------

    def _build(self, camera: str, port: int) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setSpacing(6)

        head = QtWidgets.QHBoxLayout()
        icon = QtWidgets.QLabel()
        icon_path = _icon_path()
        if icon_path:
            icon.setPixmap(QtGui.QIcon(icon_path).pixmap(28, 28))
        head.addWidget(icon)
        title = QtWidgets.QLabel("MagiCAM")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        self.pill = QtWidgets.QLabel("fermo")
        self.pill.setWordWrap(True)  # un guasto lungo va a capo invece di allargare la finestra
        self.pill.setMaximumWidth(300)
        self.pill.setObjectName("pill")
        head.addWidget(self.pill)
        lay.addLayout(head)

        # --- collegamento ---
        box = QtWidgets.QGroupBox("Collegamento col telefono")
        form = QtWidgets.QGridLayout(box)
        form.setColumnStretch(1, 1)

        form.addWidget(QtWidgets.QLabel("Camera"), 0, 0)
        self.camera_combo = QtWidgets.QComboBox()
        self.camera_combo.setEditable(True)
        self.camera_combo.setToolTip(
            "La camera DAL VIVO che il telefono muove: senza chiavi. Ogni take si cuoce su una camera nuova "
            "nel gruppo magicam_takes_grp."
        )
        form.addWidget(self.camera_combo, 0, 1)
        cam_btns = QtWidgets.QHBoxLayout()
        self.new_cam_btn = QtWidgets.QPushButton("Nuova")
        self.new_cam_btn.setToolTip("Crea una camera MagiCAM a 1,6 m d'altezza")
        self.new_cam_btn.clicked.connect(self._new_camera)
        self.look_btn = QtWidgets.QPushButton("Guarda")
        self.look_btn.setToolTip("Guarda da questa camera nella vista attiva")
        self.look_btn.clicked.connect(self._look_through)
        cam_btns.addWidget(self.new_cam_btn)
        cam_btns.addWidget(self.look_btn)
        form.addLayout(cam_btns, 0, 2)
        self._fill_cameras(camera)

        form.addWidget(QtWidgets.QLabel("IP del PC"), 1, 0)
        ips = local_ipv4()
        self.ip_label = QtWidgets.QLabel("  ·  ".join(ips) if ips else "nessuna rete")
        self.ip_label.setObjectName("ip")
        self.ip_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.ip_label.setToolTip("Da scrivere nell'app, campo Host (il primo e' la rete di casa)")
        form.addWidget(self.ip_label, 1, 1)
        self.port_spin = QtWidgets.QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(port)
        self.port_spin.setPrefix("porta ")
        form.addWidget(self.port_spin, 1, 2)

        form.addWidget(QtWidgets.QLabel("Codice"), 2, 0)
        self.token_label = QtWidgets.QLabel("")
        self.token_label.setObjectName("code")
        self.token_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addWidget(self.token_label, 2, 1)
        code_btns = QtWidgets.QHBoxLayout()
        self.token_btn = QtWidgets.QPushButton("Nuovo")
        self.token_btn.clicked.connect(self._new_token)
        self.pair_chk = QtWidgets.QCheckBox("Richiesto")
        self.pair_chk.setChecked(True)
        self.pair_chk.setToolTip("Spento = qualunque telefono sulla rete muove la camera")
        self.pair_chk.toggled.connect(self._apply_pairing)
        code_btns.addWidget(self.pair_chk)
        code_btns.addWidget(self.token_btn)
        form.addLayout(code_btns, 2, 2)
        self._token = MayaCameraBridge.new_token()
        self._apply_pairing(True)

        self.start_btn = QtWidgets.QPushButton("Avvia")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._toggle)
        form.addWidget(self.start_btn, 3, 0, 1, 3)
        lay.addWidget(box)

        # --- camera ---
        box = QtWidgets.QGroupBox("Camera")
        grid = QtWidgets.QGridLayout(box)
        self.calib_btn = QtWidgets.QPushButton("Calibra")
        self.calib_btn.setToolTip("La posa di adesso del telefono si lega alla posa di adesso della camera")
        self.calib_btn.clicked.connect(self._calibrate)
        self.recenter_btn = QtWidgets.QPushButton("Ricentra")
        self.recenter_btn.setToolTip("Riparte dalla posizione attuale senza salto")
        self.recenter_btn.clicked.connect(self._recenter)
        self.freeze_btn = QtWidgets.QPushButton("Freeze")
        self.freeze_btn.setToolTip("Ferma la camera; il rilascio riparte senza salto")
        self.freeze_btn.clicked.connect(self._toggle_freeze)
        grid.addWidget(self.calib_btn, 0, 0)
        grid.addWidget(self.recenter_btn, 0, 1)
        grid.addWidget(self.freeze_btn, 0, 2)

        grid.addWidget(QtWidgets.QLabel("Scala del moto"), 1, 0)
        self.scale_spin = QtWidgets.QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100.0)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setSingleStep(0.1)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSuffix(" ×")
        self.scale_spin.setToolTip("0,1 = miniatura, 10 = gru; cambia senza salto")
        self.scale_spin.valueChanged.connect(self._set_scale)
        grid.addWidget(self.scale_spin, 1, 1)
        self.filter_chk = QtWidgets.QCheckBox("Filtro anti-tremolio")
        self.filter_chk.setChecked(True)
        self.filter_chk.toggled.connect(self._set_filter)
        grid.addWidget(self.filter_chk, 1, 2)
        self.lock_h = QtWidgets.QCheckBox("Blocca altezza")
        self.lock_h.toggled.connect(lambda v: setattr(self.session.locks, "height", bool(v)))
        self.lock_d = QtWidgets.QCheckBox("Blocca dolly")
        self.lock_d.toggled.connect(lambda v: setattr(self.session.locks, "dolly", bool(v)))
        grid.addWidget(self.lock_h, 2, 1)
        grid.addWidget(self.lock_d, 2, 2)
        lay.addWidget(box)

        # --- take ---
        box = QtWidgets.QGroupBox("Take")
        tl = QtWidgets.QGridLayout(box)
        tl.setColumnStretch(0, 1)
        self.take_name = QtWidgets.QLineEdit()
        self.take_name.setPlaceholderText("nome della take (vuoto = data e ora)")
        tl.addWidget(self.take_name, 0, 0)
        self.rec_btn = QtWidgets.QPushButton("● Rec")
        self.rec_btn.setObjectName("rec")
        self.rec_btn.setMinimumWidth(110)
        self.rec_btn.clicked.connect(self._toggle_rec)
        tl.addWidget(self.rec_btn, 0, 1)
        self.timeline_chk = QtWidgets.QCheckBox("Rec fa partire la timeline (dall'inizio, tempo reale)")
        self.timeline_chk.setChecked(True)
        self.timeline_chk.setToolTip(
            "Le chiavi vanno sui fotogrammi che hai visto scorrere; la take finisce con la timeline o con Stop"
        )
        self.timeline_chk.toggled.connect(lambda v: setattr(self.bridge, "rec_plays_timeline", bool(v)))
        tl.addWidget(self.timeline_chk, 1, 0, 1, 2)
        self.bake_chk = QtWidgets.QCheckBox("Chiavi su una camera nuova allo stop")
        self.bake_chk.setChecked(True)
        self.bake_chk.toggled.connect(lambda v: setattr(self.bridge, "auto_bake", bool(v)))
        tl.addWidget(self.bake_chk, 2, 0, 1, 2)
        self.take_status = QtWidgets.QLabel("")
        self.take_status.setObjectName("hint")
        self.take_status.setWordWrap(True)
        self.take_status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        tl.addWidget(self.take_status, 3, 0, 1, 2)
        lay.addWidget(box)

        # --- numeri veri ---
        box = QtWidgets.QGroupBox("Dal telefono")
        sg = QtWidgets.QGridLayout(box)
        self._stat: dict[str, QtWidgets.QLabel] = {}
        names = [
            ("rate", "Pose al secondo"),
            ("received", "Ricevute"),
            ("lost", "Perse"),
            ("tracking", "Tracking"),
            ("rejected", "Rifiutate"),
            ("unpaired", "Non abbinate"),
            ("tick", "Costo in Maya"),
            ("reanchors", "Ri-ancoraggi"),
        ]
        for i, (key, label) in enumerate(names):
            r, c = divmod(i, 2)
            n = QtWidgets.QLabel(label)
            n.setObjectName("statName")
            v = QtWidgets.QLabel("—")
            v.setObjectName("statValue")
            sg.addWidget(n, r, c * 2)
            sg.addWidget(v, r, c * 2 + 1)
            self._stat[key] = v
        lay.addWidget(box)

        # riga di stato completa, selezionabile (la leggono anche i banchi)
        self.status = QtWidgets.QLabel("fermo")
        self.status.setObjectName("hint")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status)

    # --- camere ------------------------------------------------------------------------------------------------

    @property
    def camera_edit(self) -> Any:
        """Il campo di testo della camera (compatibilita' coi banchi che leggevano `camera_edit.text()`)."""
        return self.camera_combo.lineEdit()

    def _fill_cameras(self, wanted: str) -> None:
        self.camera_combo.clear()
        cams = scene_cameras()
        self.camera_combo.addItems(cams)
        self.camera_combo.setEditText(wanted if wanted else (cams[0] if cams else DEFAULT_CAMERA))

    def _new_camera(self) -> None:
        try:
            name = create_camera(DEFAULT_CAMERA)
        except (RuntimeError, ImportError) as e:
            QtWidgets.QMessageBox.critical(self, "MagiCAM", f"Camera non creata: {e}")
            return
        self._fill_cameras(name)
        self._look_through()

    def _look_through(self) -> None:
        try:
            import maya.cmds as cmds

            cam = self.camera_edit.text().strip()
            panel = cmds.getPanel(withFocus=True)
            if cmds.getPanel(typeOf=panel) != "modelPanel":
                panels = cmds.getPanel(visiblePanels=True) or []
                models = [p for p in panels if cmds.getPanel(typeOf=p) == "modelPanel"]
                if not models:
                    return
                panel = models[0]
            cmds.lookThru(panel, cam)
        except (RuntimeError, ImportError) as e:
            QtWidgets.QMessageBox.warning(self, "MagiCAM", f"Non posso guardare dalla camera: {e}")

    # --- azioni --------------------------------------------------------------------------------------------------

    def _toggle(self) -> None:
        if self.receiver.running:
            self.bridge.stop()
        else:
            self.bridge.camera = self.camera_edit.text().strip()
            self.receiver.port = int(self.port_spin.value())
            try:
                self.bridge.start()
            except (RuntimeError, OSError) as e:
                QtWidgets.QMessageBox.critical(self, "MagiCAM", str(e))
                return
            self._rate.clear()
        self.refresh()

    def _calibrate(self) -> None:
        if not self.bridge.calibrate():
            QtWidgets.QMessageBox.warning(self, "MagiCAM", "Nessuna posa dal telefono: premi Avvia nell'app e riprova.")
        self.refresh()

    def _recenter(self) -> None:
        self.session.recenter()
        self.refresh()

    def _toggle_freeze(self) -> None:
        if self.session.state().frozen:
            self.session.unfreeze()
        else:
            self.session.freeze()
        self.refresh()

    def _set_scale(self, v: float) -> None:
        self.session.set_scale(float(v))

    def _new_token(self) -> None:
        self._token = MayaCameraBridge.new_token()
        self._apply_pairing(self.pair_chk.isChecked())

    def _apply_pairing(self, on: bool) -> None:
        self.bridge.require_token(self._token if on else None)
        self.token_label.setText(f"{self._token:06d}" if on else "aperto a tutta la rete")
        self.token_btn.setEnabled(on)

    def _toggle_rec(self) -> None:
        if self.bridge.recorder.recording:
            try:
                path = self.bridge.stop_take()
            except (RuntimeError, OSError, ValueError) as e:
                QtWidgets.QMessageBox.critical(self, "MagiCAM", f"Take non salvata: {e}")
                return
            self.take_status.setText(self._take_summary(path))
        else:
            self.bridge.start_take(self.take_name.text().strip())
            self.take_status.setText(f"registro «{self.bridge.recorder.name}»…")
        self.refresh()

    def _take_summary(self, path: Any) -> str:
        b = self.bridge
        if b.auto_bake and b.last_take_camera:
            how = "sui fotogrammi visti" if b.last_bake_mode == "timeline" else "dal fotogramma del Rec"
            return f"salvata: {path} · {b.last_bake_keys} chiavi {how} su {b.last_take_camera}"
        return f"salvata: {path}"

    def _set_filter(self, on: bool) -> None:
        self.session.filter_enabled = bool(on)

    # --- stato ---------------------------------------------------------------------------------------------------

    def _pose_rate(self, received: int) -> float:
        now = time.perf_counter()
        self._rate.append((now, received))
        (t0, r0), (t1, r1) = self._rate[0], self._rate[-1]
        return (r1 - r0) / (t1 - t0) if t1 - t0 > 0.5 else 0.0

    def _set_pill(self, text: str, color: str) -> None:
        self.pill.setText(text)
        self.pill.setStyleSheet(f"background: {color};")

    def refresh(self) -> None:
        s = self.session.state()
        st = self.receiver.stats
        ts = self.bridge.stats
        running = self.receiver.running
        rate = self._pose_rate(st.received) if running else 0.0

        # spia: lo stato del collegamento visto dal PC, non quello che il telefono crede
        if not running and self.bridge.fault:
            self._set_pill("FERMO: " + self.bridge.fault, RED)
        elif not running:
            self._set_pill("fermo", GREY)
        elif self.bridge.link_lost:
            silence = st.silence_s(time.perf_counter()) or 0.0
            self._set_pill(f"COLLEGAMENTO PERSO · {silence:.0f} s", RED)
        elif st.received == 0 or rate < 1.0:
            self._set_pill("in attesa del telefono", AMBER)
        elif s.hold is Hold.NOT_CALIBRATED:
            self._set_pill(f"collegato · premi Calibra · {rate:.0f} Hz", AMBER)
        elif s.frozen:
            self._set_pill("FREEZE", AMBER)
        elif s.hold is Hold.TRACKING:
            self._set_pill("tracking del telefono non normale", AMBER)
        else:
            self._set_pill(f"dal vivo · {rate:.0f} Hz", GREEN)

        self.start_btn.setText("Ferma" if running else "Avvia")
        self.start_btn.setObjectName("danger" if running else "primary")
        self.camera_combo.setEnabled(not running)
        self.port_spin.setEnabled(not running)
        self.new_cam_btn.setEnabled(not running)
        for b in (self.calib_btn, self.recenter_btn, self.freeze_btn, self.rec_btn):
            b.setEnabled(running)

        self.freeze_btn.setText("Rilascia" if s.frozen else "Freeze")
        self.freeze_btn.setObjectName("frozen" if s.frozen else "")
        rec = self.bridge.recorder
        self.rec_btn.setText(f"■ Stop · {rec.sample_count}" if rec.recording else "● Rec")
        self.rec_btn.setObjectName("recOn" if rec.recording else "rec")
        if rec.recording and not self.take_status.text().startswith("registro"):
            self.take_status.setText(f"registro «{rec.name}»… (avviata dal telefono)")
        elif not rec.recording and self.take_status.text().startswith("registro") and self.bridge.last_take_path:
            self.take_status.setText(self._take_summary(self.bridge.last_take_path))
        if self.bridge.last_error:
            self.take_status.setText(f"ERRORE {self.bridge.last_error}")
            self.take_status.setStyleSheet(f"color: {RED};")
        else:
            self.take_status.setStyleSheet("")
        for w in (self.start_btn, self.freeze_btn, self.rec_btn):
            w.style().unpolish(w)
            w.style().polish(w)

        latest = self.receiver.latest()
        tracking = "—"
        if latest is not None:
            m = latest[0]
            tracking = {"NORMAL": "normale", "LIMITED": "limitato", "NOT_AVAILABLE": "assente"}.get(
                m.tracking_state.name, m.tracking_state.name.lower()
            )
            if m.tracking_reason.name != "NONE":
                tracking += f" ({m.tracking_reason.name.lower().replace('_', ' ')})"
        values = {
            "rate": f"{rate:.1f}" if running else "—",
            "received": str(st.received),
            "lost": str(st.lost),
            "tracking": tracking,
            "rejected": str(st.rejected),
            "unpaired": str(st.unpaired),
            "tick": f"{ts.last_cost_ms:.2f} ms (max {ts.max_cost_ms:.2f})",
            "reanchors": str(s.reanchors),
        }
        for k, v in values.items():
            self._stat[k].setText(v)

        bonjour = (
            "Bonjour on" if self.bridge.advertiser is not None and self.bridge.advertiser.running else "Bonjour off"
        )
        state = "in ascolto" if running else ("FERMO: " + self.bridge.fault if self.bridge.fault else "fermo")
        if running and self.bridge.link_lost:
            silence = st.silence_s(time.perf_counter()) or 0.0
            state = f"COLLEGAMENTO PERSO da {silence:.1f} s"
        self.status.setText(
            f"{state} · {bonjour} · {s.hold.value} · ricevute {st.received} · perse {st.lost} · "
            f"riordinate {st.reordered} · rifiutate {st.rejected} · non abbinate {st.unpaired} · "
            f"ri-ancoraggi {s.reanchors} · applicate {ts.applied_hz:.0f} Hz · "
            f"tick {ts.last_cost_ms:.2f} ms (max {ts.max_cost_ms:.2f})"
        )

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - firma Qt
        self._poll.stop()
        self.bridge.stop()
        super().closeEvent(event)


def _icon_path() -> str | None:
    from pathlib import Path

    p = Path(__file__).with_name("icons") / "magicam_shelf.svg"
    return str(p) if p.is_file() else None


def show(camera: str = DEFAULT_CAMERA, port: int = 9000) -> MagiCamPanel:
    """Apre (o riapre) il pannello e lo RESTITUISCE. Se la camera chiesta non c'e', propone la prima della scena."""
    global _PANEL
    if _PANEL is not None:
        with contextlib.suppress(RuntimeError):  # oggetto Qt gia' distrutto (finestra chiusa da Maya)
            _PANEL.close()
    _PANEL = MagiCamPanel(camera, port, parent=_maya_main_window())
    _PANEL.show()
    return _PANEL
