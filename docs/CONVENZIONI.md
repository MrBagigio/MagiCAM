# Convenzioni di MagiCAM v2

Ogni convenzione porta lo stato: **[misurata]** con data, versione di Maya e comando che la rilegge, oppure
**[dichiarata, non misurata]**. Niente si costruisce su una convenzione non misurata senza dirlo (regola E1 della suite:
il DCC si misura, non si deduce). Nel codice la convenzione vive in UN punto: `magicam/math3d.py`.

## Sistemi di riferimento

| | ARKit (`ARFrame.camera.transform`, `worldAlignment = .gravity`) | Maya |
|---|---|---|
| Asse su | +Y | +Y |
| Mano | destra | destra |
| Camera guarda | −Z locale | −Z locale |
| Unita' | metri | `cmds.currentUnit(q=True, linear=True)` (cm di default) |

Stesse convenzioni: **nessuna riflessione d'asse serve**. Il moto relativo del telefono si trasporta nel telaio della
camera-ancora cosi' com'e'. *[dichiarata dalle documentazioni Apple e Autodesk; la prova del verso la da' F2.6 con
l'iPhone: gira a sinistra → la camera gira a sinistra.]*

## Quaternione

`(x, y, z, w)`, unitario, come `simd_quatf` di ARKit e come `scipy.spatial.transform.Rotation`. Ruota un vettore con
`v' = q v q*`. La rotazione `R(q)` (3x3) e' in **convenzione colonna-vettore**: `v' = R v`, le colonne di `R` sono gli
assi locali espressi nel mondo. *[matematica, verificata nei test contro numpy]*

## Trasformazione

`Transform(pos, quat)` = posa di un telaio nel mondo: `x_world = R(q) x_local + pos`.
Composizione `A ∘ B` = prima `B` poi `A`: `(A∘B).pos = A.R B.pos + A.pos`, `(A∘B).q = A.q B.q`.
Inversa: `pos' = −Rᵀ pos`, `q' = q*`.

## Ancora e scala (il cuore di v2)

Al momento della calibrazione si salvano `C` (posa del telefono nel mondo ARKit) e `A` (posa della camera nel mondo
Maya, in metri). Per ogni posa `P` del telefono:

```
rel   = C⁻¹ ∘ P                 # moto del telefono rispetto a dove era quando ha calibrato
rel.pos *= scale                # la scala del mondo agisce sul moto RELATIVO, attorno all'ancora
camera = A ∘ rel                # trasportato nel telaio della camera-ancora
```

Risposte note (test `tests/test_math3d.py`, scritte PRIMA del codice):

| C | A | P | camera attesa |
|---|---|---|---|
| I | I | I | I |
| I | I | yaw +20° | yaw +20° |
| I | I | pitch +20° | pitch +20° |
| I | I | +0.10 m in X | +0.10 m in X |
| I | I | −0.10 m in Z (avanti) | −0.10 m in Z |
| I | pos (5, 1.5, 0), yaw 90° | −0.10 m in Z | pos (4.9, 1.5, 0), yaw 90° |
| I | I, scale 0.1 | +0.10 m in X | +0.01 m in X |

## La lista di `cmds.xform(matrix=…)` — [dichiarata, NON misurata: F1.1]

Maya tratta i punti come **righe**: `p' = p · M`. La lista di 16 che `xform -q -ws -matrix` restituisce e che
`xform -ws -matrix` accetta e' `M` riga per riga, quindi:

- indici 0-2 = asse X locale nel mondo, 4-6 = asse Y, 8-10 = asse Z (le RIGHE sono gli assi);
- indici 12, 13, 14 = traslazione;
- la 3x3 e' la **trasposta** di `R(q)` della convenzione colonna-vettore qui sopra.

`math3d.to_maya_matrix(T)` produce esattamente questo. Il POC di gennaio metteva la traslazione in 3, 7, 11 e la 3x3
non trasposta: ecco il moto invertito (`docs/PIANO_DI_LAVORO.md` §2.1 F1).

**Misura da fare (F1.1)**, in un Maya nudo, farm ferma:
```python
import maya.cmds as cmds, math
cmds.file(new=True, force=True)
cam = cmds.camera()[0]
c, s = math.cos(math.radians(20)), math.sin(math.radians(20))
# yaw +20 (Ry), traslazione (1,2,3) in 12-14, convenzione riga-vettore
cmds.xform(cam, ws=True, matrix=[c,0,-s,0,  0,1,0,0,  s,0,c,0,  1,2,3,1])
print(cmds.xform(cam, q=True, ws=True, t=True))   # atteso [1.0, 2.0, 3.0]
print(cmds.xform(cam, q=True, ws=True, ro=True))  # atteso [0.0, 20.0, 0.0]
# CONTRASTO: la stessa posa nella convenzione del POC deve dare un risultato DIVERSO
cmds.xform(cam, ws=True, matrix=[c,0,s,1,  0,1,0,2,  -s,0,c,3,  0,0,0,1])
print(cmds.xform(cam, q=True, ws=True, t=True), cmds.xform(cam, q=True, ws=True, ro=True))
```
Esito, data, versione di Maya: *da scrivere qui.*
