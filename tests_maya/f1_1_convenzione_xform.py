"""F1.1 — misura della convenzione di `cmds.xform(matrix=...)` nel Maya VERO. Si esegue DENTRO Maya.

Atteso, scritto PRIMA della misura (docs/CONVENZIONI.md): la lista di 16 e' riga-vettore, righe = assi, traslazione
in 12-14. Quindi:
  A) lista con yaw +20 (Ry) nelle righe e (1,2,3) in 12-14  ->  xform -q -t = (1,2,3), -q -ro = (0, 20, 0)
  B) CONTRASTO, la stessa posa nella convenzione del v1 (traslazione in 3,7,11, 3x3 non trasposta)
     -> risultato DIVERSO: traslazione NON (1,2,3) e/o yaw -20
  C) `to_maya_matrix` di magicam deve dare la lista A (byte per byte entro 1e-12)
  D) `from_maya_matrix(xform -q -matrix)` deve tornare la posa data (roundtrip nel Maya vero)
Stampa un JSON con misurato e verdetto; non cambia niente di permanente (scena nuova, poi la camera si cancella).
"""

import json
import math
import sys

import maya.cmds as cmds

REPO = r"C:\Users\alexg\Documents\MagiCAM"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from magicam.math3d import Transform, from_maya_matrix, quat_from_axis_angle, to_maya_matrix  # noqa: E402


def misura() -> dict:
    cmds.file(new=True, force=True)
    unit = cmds.currentUnit(q=True, linear=True)
    cam = cmds.camera(name="magicam_f1_1")[0]
    c, s = math.cos(math.radians(20.0)), math.sin(math.radians(20.0))
    out: dict = {"maya": cmds.about(version=True), "unit": unit}

    # A) convenzione dichiarata: righe = assi (asse X = (c,0,-s), asse Z = (s,0,c) per Ry(+20)), traslazione 12-14
    lista_a = [c, 0.0, -s, 0.0, 0.0, 1.0, 0.0, 0.0, s, 0.0, c, 0.0, 1.0, 2.0, 3.0, 1.0]
    cmds.xform(cam, ws=True, matrix=lista_a)
    out["A_t"] = cmds.xform(cam, q=True, ws=True, t=True)
    out["A_ro"] = cmds.xform(cam, q=True, ws=True, ro=True)
    out["A_matrix_back"] = cmds.xform(cam, q=True, ws=True, matrix=True)

    # B) contrasto: convenzione del v1 (traslazione in 3,7,11; 3x3 colonna-vettore non trasposta)
    lista_b = [c, 0.0, s, 1.0, 0.0, 1.0, 0.0, 2.0, -s, 0.0, c, 3.0, 0.0, 0.0, 0.0, 1.0]
    cmds.xform(cam, ws=True, matrix=lista_b)
    out["B_t"] = cmds.xform(cam, q=True, ws=True, t=True)
    out["B_ro"] = cmds.xform(cam, q=True, ws=True, ro=True)

    # C) la lista che produce magicam (metri -> unita' della scena) contro la lista A (in unita' di scena)
    upm = {"cm": 100.0, "m": 1.0, "mm": 1000.0}[unit]
    t = Transform(pos=(1.0 / upm, 2.0 / upm, 3.0 / upm), quat=quat_from_axis_angle((0.0, 1.0, 0.0), math.radians(20.0)))
    lista_c = to_maya_matrix(t, upm)
    out["C_max_diff"] = max(abs(x - y) for x, y in zip(lista_c, lista_a, strict=False))

    # D) roundtrip nel Maya vero: xform(lista_c) -> q matrix -> from_maya_matrix -> stessa posa
    cmds.xform(cam, ws=True, matrix=lista_c)
    back = from_maya_matrix(list(cmds.xform(cam, q=True, ws=True, matrix=True)), upm)
    out["D_pos_err_m"] = max(abs(a - b) for a, b in zip(back.pos, t.pos, strict=False))
    dot = abs(sum(a * b for a, b in zip(back.quat, t.quat, strict=False)))
    out["D_rot_err_deg"] = math.degrees(2.0 * math.acos(min(1.0, dot)))

    # E) UNITA' (ipotesi dal banco F1.8 a metri, camera mossa di 1/100): la traslazione della LISTA e' in cm
    #    interni qualunque sia l'unita' della scena, mentre -t e' in unita' della UI. Atteso: in scena a metri,
    #    xform(matrix con 100 in [12]) -> xform -q -t = 1.0 (m); e -q -matrix rilegge 100.
    cmds.currentUnit(linear="m")
    cmds.xform(cam, ws=True, matrix=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 100.0, 0.0, 0.0, 1])
    out["E_m_t_from_matrix100"] = cmds.xform(cam, q=True, ws=True, t=True)
    out["E_m_matrix_back12"] = cmds.xform(cam, q=True, ws=True, matrix=True)[12]
    cmds.xform(cam, ws=True, t=(2.0, 0.0, 0.0))  # 2 m con -t (unita' UI)
    out["E_m_matrix12_after_t2m"] = cmds.xform(cam, q=True, ws=True, matrix=True)[12]
    cmds.currentUnit(linear=unit)
    cmds.delete(cam)

    def vicino(v, w, tol=1e-6):
        return all(abs(a - b) < tol for a, b in zip(v, w, strict=False))

    out["verdetto"] = {
        "A_traslazione_12_14": vicino(out["A_t"], [1.0, 2.0, 3.0]),
        "A_yaw_+20": vicino(out["A_ro"], [0.0, 20.0, 0.0], 1e-4),
        "B_contrasto_diverso": not (
            vicino(out["B_t"], [1.0, 2.0, 3.0]) and vicino(out["B_ro"], [0.0, 20.0, 0.0], 1e-4)
        ),
        "C_to_maya_matrix_uguale_ad_A": out["C_max_diff"] < 1e-12,
        "D_roundtrip": out["D_pos_err_m"] < 1e-9 and out["D_rot_err_deg"] < 1e-7,
        "E_matrix_in_cm_interni": vicino(out["E_m_t_from_matrix100"], [1.0, 0.0, 0.0])
        and abs(out["E_m_matrix_back12"] - 100.0) < 1e-9
        and abs(out["E_m_matrix12_after_t2m"] - 200.0) < 1e-9,
    }
    out["CONVENZIONE_MISURATA_OK"] = all(out["verdetto"].values())
    return out


if True:
    RISULTATO = misura()
    print("F1_1_JSON=" + json.dumps(RISULTATO))
