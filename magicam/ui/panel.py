"""Pannello MagiCAM dentro Maya. SCRITTO, NON ESEGUITO IN MAYA (F1.10).

Uso in Maya:
    from magicam.ui.panel import show
    panel = show(camera="camera1", port=9000)
Ogni pulsante chiama una funzione di `MayaCameraBridge`/`Session` che ha il suo test fuori da Maya.
"""

from __future__ import annotations

import logging
from typing import Any

from magicam.maya_bridge import MayaCameraBridge
from magicam.receiver import Receiver
from magicam.session import Session

log = logging.getLogger("magicam.ui")

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:  # Maya 2024
    from PySide2 import QtCore, QtWidgets

_PANEL: MagiCamPanel | None = None


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


class MagiCamPanel(QtWidgets.QDialog):  # type: ignore[misc]
    def __init__(self, camera: str, port: int, parent: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MagiCAM")
        self.setObjectName("MagiCamPanel")
        self.session = Session()
        self.receiver = Receiver(port=port)
        self.bridge = MayaCameraBridge(self.session, self.receiver, camera, on_state_changed=self.refresh)
        self._build(camera, port)
        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self.refresh)
        self._poll.start(250)

    # --- costruzione -------------------------------------------------------------------------------------------

    def _build(self, camera: str, port: int) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.camera_edit = QtWidgets.QLineEdit(camera)
        self.port_spin = QtWidgets.QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(port)
        form.addRow("Camera", self.camera_edit)
        form.addRow("Porta UDP", self.port_spin)
        lay.addLayout(form)

        row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Avvia")
        self.start_btn.clicked.connect(self._toggle)
        self.calib_btn = QtWidgets.QPushButton("Calibra")
        self.calib_btn.clicked.connect(self._calibrate)
        self.recenter_btn = QtWidgets.QPushButton("Ricentra")
        self.recenter_btn.clicked.connect(self._recenter)
        self.freeze_btn = QtWidgets.QPushButton("Freeze")
        self.freeze_btn.clicked.connect(self._toggle_freeze)
        for b in (self.start_btn, self.calib_btn, self.recenter_btn, self.freeze_btn):
            row.addWidget(b)
        lay.addLayout(row)

        opts = QtWidgets.QHBoxLayout()
        opts.addWidget(QtWidgets.QLabel("Scala moto"))
        self.scale_spin = QtWidgets.QDoubleSpinBox()
        self.scale_spin.setRange(0.01, 100.0)
        self.scale_spin.setDecimals(2)
        self.scale_spin.setValue(1.0)
        self.scale_spin.valueChanged.connect(self._set_scale)
        opts.addWidget(self.scale_spin)
        self.filter_chk = QtWidgets.QCheckBox("Filtro")
        self.filter_chk.setChecked(True)
        self.filter_chk.toggled.connect(self._set_filter)
        opts.addWidget(self.filter_chk)
        self.lock_h = QtWidgets.QCheckBox("Blocca altezza")
        self.lock_h.toggled.connect(lambda v: setattr(self.session.locks, "height", bool(v)))
        self.lock_d = QtWidgets.QCheckBox("Blocca dolly")
        self.lock_d.toggled.connect(lambda v: setattr(self.session.locks, "dolly", bool(v)))
        opts.addWidget(self.lock_h)
        opts.addWidget(self.lock_d)
        lay.addLayout(opts)

        self.status = QtWidgets.QLabel("fermo")
        self.status.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.status)

    # --- azioni --------------------------------------------------------------------------------------------------

    def _toggle(self) -> None:
        if self.receiver.running:
            self.bridge.stop()
            self.start_btn.setText("Avvia")
        else:
            self.bridge.camera = self.camera_edit.text().strip()
            self.receiver.port = int(self.port_spin.value())
            try:
                self.bridge.start()
            except (RuntimeError, OSError) as e:
                QtWidgets.QMessageBox.critical(self, "MagiCAM", str(e))
                return
            self.start_btn.setText("Ferma")
        self.refresh()

    def _calibrate(self) -> None:
        if not self.bridge.calibrate():
            QtWidgets.QMessageBox.warning(self, "MagiCAM", "Nessuna posa dal telefono: avvia l'app e riprova.")
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

    def _set_filter(self, on: bool) -> None:
        self.session.filter_enabled = bool(on)

    # --- stato ---------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        s = self.session.state()
        st = self.receiver.stats
        ts = self.bridge.stats
        self.freeze_btn.setText("Rilascia" if s.frozen else "Freeze")
        running = "in ascolto" if self.receiver.running else "fermo"
        self.status.setText(
            f"{running} · {s.hold.value} · ricevute {st.received} · perse {st.lost} · riordinate {st.reordered} · "
            f"rifiutate {st.rejected} · latenza {st.latency_ms:.0f} ms · applicate {ts.applied_hz:.0f} Hz · "
            f"tick {ts.last_cost_ms:.2f} ms (max {ts.max_cost_ms:.2f})"
        )

    def closeEvent(self, event: Any) -> None:  # noqa: N802 - firma Qt
        self._poll.stop()
        self.bridge.stop()
        super().closeEvent(event)


def show(camera: str = "camera1", port: int = 9000) -> MagiCamPanel:
    """Apre (o riapre) il pannello e lo RESTITUISCE."""
    global _PANEL
    if _PANEL is not None:
        _PANEL.close()
    _PANEL = MagiCamPanel(camera, port, parent=_maya_main_window())
    _PANEL.show()
    return _PANEL
