# MagiCAM v2

Camera virtuale: l'iPhone (ARKit) manda la sua posa a Maya via UDP e Maya la applica a una camera, con calibrazione
su un'ancora, scala del moto, freeze e (F3) registrazione delle take agli fps della scena.

**Stato (2026-10-15): F0+F1 — lato Maya scritto e provato FUORI da Maya col simulatore; F2 — app iOS SCRITTA e
NON COMPILATA (nessun Mac qui: la compila la CI su GitHub, ferma finche' l'account Actions e' bloccato). Niente
eseguito in Maya ne' su iPhone.** Il POC di gennaio sta in `legacy/` ed e' superato: `docs/PIANO_DI_LAVORO.md` §2.

## Cosa fa oggi (provato)

- `magicam.protocol`: datagramma binario di 62 byte, versionato, rifiuta tutto cio' che non torna (`docs/PROTOCOL.md`).
- `magicam.math3d`: ancora + scala relativa, con le risposte note di `docs/CONVENZIONI.md` nei test.
- `magicam.receiver`: ultima posa valida, persi/riordinati/rifiutati/latenza contati esatti contro il simulatore.
- `magicam.filters`: One Euro su posizione e quaternione, dt dal sensore (non tarato: F1.9).
- `magicam.session`: calibra, ricentra, freeze senza salto, scala senza salto, blocchi d'asse.
- `magicam.simulator`: telefono finto (`python -m magicam.simulator --traj circle`).
- `magicam.takes`: take per timestamp del sensore, ricampionate agli fps della scena (600 campioni a 60 Hz → 240
  chiavi a 24 fps, durata reale; il v1 ne faceva 600 = 25 s), JSON grezzo atomico accanto alla scena, cestino.

## Cosa e' scritto e NON provato

- `magicam.maya_bridge` (timer sul main thread, `xform` + lente, cottura delle chiavi con filtro Euler) e
  `magicam.ui.panel` (anche Rec/Stop take): aspettano Maya (F1.8-F1.10, F3.4).
- La convenzione della lista di `xform -matrix`: dichiarata in `docs/CONVENZIONI.md`, da misurare (F1.1).
- `ios/`: app SwiftUI (`MagiCAM/`) + pacchetto `Packages/MagiCAMCore` (protocollo, XCTest sugli stessi vettori di
  Python), progetto generato da XcodeGen (`ios/project.yml`). Mai compilata: lo fa `.github/workflows/ios-build.yml`
  (`swift test`, poi build non firmata → `.ipa` da installare con AltStore).

## Provare senza Maya

```bash
pip install -e ".[dev]"
pytest
python -m magicam.simulator --host 127.0.0.1 --port 9000 --traj yaw20
```

## In Maya (quando sara' misurato)

```python
import sys; sys.path.insert(0, r"C:\Users\alexg\Documents\MagiCAM")
from magicam.ui.panel import show
panel = show(camera="camera1", port=9000)
```

## Documenti

`docs/PIANO_DI_LAVORO.md` (quadro, verdetto, To-Do con accettazione e prova) · `docs/PROTOCOL.md` ·
`docs/CONVENZIONI.md` · `docs/MISURE.md` · `CHANGELOG.md`.
