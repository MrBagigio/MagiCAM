# MagiCAM v2

Camera virtuale: l'iPhone (ARKit) manda la sua posa a Maya via UDP e Maya la applica a una camera, con calibrazione
su un'ancora, scala del moto, freeze e (F3) registrazione delle take agli fps della scena.

**Stato (2026-10-15): fase F0+F1 — lato Maya scritto e provato FUORI da Maya col simulatore. Non ancora eseguito in
Maya, nessuna app iOS v2 (F2).** Il POC di gennaio sta in `legacy/` ed e' superato: `docs/PIANO_DI_LAVORO.md` §2.

## Cosa fa oggi (provato)

- `magicam.protocol`: datagramma binario di 62 byte, versionato, rifiuta tutto cio' che non torna (`docs/PROTOCOL.md`).
- `magicam.math3d`: ancora + scala relativa, con le risposte note di `docs/CONVENZIONI.md` nei test.
- `magicam.receiver`: ultima posa valida, persi/riordinati/rifiutati/latenza contati esatti contro il simulatore.
- `magicam.filters`: One Euro su posizione e quaternione, dt dal sensore (non tarato: F1.9).
- `magicam.session`: calibra, ricentra, freeze senza salto, scala senza salto, blocchi d'asse.
- `magicam.simulator`: telefono finto (`python -m magicam.simulator --traj circle`).

## Cosa e' scritto e NON provato

- `magicam.maya_bridge` (timer sul main thread, `xform` + lente) e `magicam.ui.panel`: aspettano Maya (F1.8-F1.10).
- La convenzione della lista di `xform -matrix`: dichiarata in `docs/CONVENZIONI.md`, da misurare (F1.1).

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
