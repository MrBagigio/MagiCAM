"""Pulsante MagiCAM su una shelf di Maya (di solito «Custom»), con l'icona SVG.

Uso in Maya, una volta:
    from magicam.ui.shelf import install
    install("Custom")
Idempotente: se il pulsante MagiCAM c'e' gia' lo aggiorna, non ne aggiunge un secondo. Salva SOLO quella shelf, dopo
una copia di sicurezza del suo file (`shelf_<nome>.mel.bak_magicam_<data>`): le altre shelf non si toccano.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

LABEL = "MagiCAM"
ICON_NAME = "magicam_shelf.svg"
REPO_ROOT = Path(__file__).resolve().parents[2]
ICON_SRC = Path(__file__).with_name("icons") / ICON_NAME

COMMAND = (
    "import sys\n"
    f'radice = r"{REPO_ROOT}"\n'
    "if radice not in sys.path:\n"
    "    sys.path.insert(0, radice)\n"
    "from magicam.ui.panel import show\n"
    "show()\n"
)


def install(shelf: str = "Custom") -> str:
    """Mette (o aggiorna) il pulsante e salva la shelf. Restituisce il nome del pulsante."""
    import maya.cmds as cmds
    import maya.mel as mel

    top = mel.eval("$tmp = $gShelfTopLevel")
    if not cmds.shelfLayout(shelf, exists=True):
        raise RuntimeError(f"shelf «{shelf}» non trovata")

    icons_dir = Path(cmds.internalVar(userBitmapsDir=True))
    icons_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ICON_SRC, icons_dir / ICON_NAME)

    existing = [
        b
        for b in (cmds.shelfLayout(shelf, q=True, childArray=True) or [])
        if cmds.objectTypeUI(b) == "shelfButton" and cmds.shelfButton(b, q=True, label=True) == LABEL
    ]
    opts = dict(
        label=LABEL,
        annotation="MagiCAM - camera virtuale dall'iPhone: apre il pannello (collegamento, calibra, take)",
        image=ICON_NAME,
        image1=ICON_NAME,
        style="iconOnly",
        sourceType="python",
        command=COMMAND,
        # MISURATO (2026-10-16): un pulsante creato su una scheda non in vista si salva con «-visible 0», e al
        # riavvio di Maya resterebbe nascosto. Lo si dichiara visibile e si mostra la scheda PRIMA di salvare.
        visible=True,
        manage=True,
    )
    cmds.shelfTabLayout(top, e=True, selectTab=shelf)
    if existing:
        button = existing[0]
        cmds.shelfButton(button, e=True, **opts)
    else:
        button = cmds.shelfButton(parent=shelf, **opts)

    shelf_file = Path(cmds.internalVar(userShelfDir=True)) / f"shelf_{shelf}.mel"
    if shelf_file.is_file():
        backup = shelf_file.with_name(f"{shelf_file.name}.bak_magicam_{time.strftime('%Y%m%d_%H%M%S')}")
        shutil.copy2(shelf_file, backup)
    mel.eval(f'saveShelf "{shelf}" "{(shelf_file.parent / f"shelf_{shelf}").as_posix()}"')
    saved = shelf_file.read_text(encoding="utf-8", errors="replace")
    at = saved.find(f'-label "{LABEL}"')
    block = saved[saved.rfind("shelfButton", 0, at) : at] if at >= 0 else ""
    if not block or "-visible 0" in block:
        raise RuntimeError(f"pulsante {LABEL} salvato invisibile in {shelf_file}: guarda il file")
    return str(button)
