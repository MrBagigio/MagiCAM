"""Simula la pipeline di maya_receiver.py (ramo feature, SMOOTH_MODE='none', FLIP_YAW=FLIP_PITCH=True,
scale 1) senza Maya. Convenzione di Maya emulata: xform(matrix=L) legge L come riga-vettore
(assi nelle RIGHE, traslazione in 12,13,14); MMatrix(a)*MMatrix(b) = prodotto riga-per-colonna delle liste.
Atteso corretto: ARKit e Maya sono entrambi Y-up destrorsi, camera che guarda -Z -> il moto del telefono
si ripete identico sulla camera (a meno della calibrazione)."""
import numpy as np

def Ry(d):
    a = np.radians(d); c, s = np.cos(a), np.sin(a)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]])
def Rx(d):
    a = np.radians(d); c, s = np.cos(a), np.sin(a)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]])

def swift_pack(R, t):          # ARSessionManager.swift: righe di R, traslazione in 3,7,11 (x100 cm)
    L = np.eye(4); L[:3,:3] = R; L[:3,3] = np.array(t)*100.0
    return L                   # numpy riga-maggiore == lista di 16

D = np.diag([-1.,1.,-1.,1.])   # reflect_z * reflect_x (entrambi i flip accesi di default)
def arkit_to_maya(L): return L @ D

def maya_reads(L):             # cosa vede Maya da xform(ws, matrix=L) + xform(ws, translation=L[3],L[7],L[11])
    Rworld = L[:3,:3].T        # riga-vettore -> rotazione colonna-vettore = trasposta
    t = np.array([L[0,3], L[1,3], L[2,3]])
    return Rworld, t

def angle_axis(R):
    ang = np.degrees(np.arccos(np.clip((np.trace(R)-1)/2, -1, 1)))
    ax = np.array([R[2,1]-R[1,2], R[0,2]-R[2,0], R[1,0]-R[0,1]])
    n = np.linalg.norm(ax)
    return round(ang,2), (np.round(ax/n,3) if n > 1e-9 else ax)

def run(desired_R, desired_t, calib_R, calib_t, pose_R, pose_t, label):
    desired = np.eye(4); desired[:3,:3] = desired_R.T; desired[3,:3] = desired_t   # xform -q -matrix di Maya
    Mc = arkit_to_maya(swift_pack(calib_R, calib_t))
    CALIB = desired @ np.linalg.inv(Mc)
    final = CALIB @ arkit_to_maya(swift_pack(pose_R, pose_t))
    Rw, t = maya_reads(final)
    print(f"{label}\n   camera Maya: rot {angle_axis(Rw)}  trasl {np.round(t,2)}")
    # atteso: camera = desired composta col moto relativo del telefono
    # CALIB porta la posa di calibrazione sulla camera: mondo telefono -> mondo Maya con G = Rd * Rc^T
    G = desired_R @ calib_R.T
    trel = (np.array(pose_t)-np.array(calib_t))*100
    print(f"   atteso     : rot {angle_axis(G @ pose_R)}  trasl {np.round(np.array(desired_t) + G @ trel,2)}")

I = np.eye(3)
run(I,[0,0,0], I,[0,0,0], I,[0,0,0],            "A) riferimento: telefono fermo nella posa di calibrazione")
run(I,[0,0,0], I,[0,0,0], Ry(20),[0,0,0],       "B) telefono gira a sinistra (yaw +20)")
run(I,[0,0,0], I,[0,0,0], Rx(20),[0,0,0],       "C) telefono alza il muso (pitch +20)")
run(I,[0,0,0], I,[0,0,0], I,[0.1,0,0],          "D) telefono si sposta di 10 cm a destra (+X)")
run(I,[0,0,0], I,[0,0,0], I,[0,0,-0.1],         "E) telefono avanza di 10 cm (-Z, dove guarda)")
run(Ry(90),[500,150,0], I,[0,0,0], I,[0,0,-0.1],"F) camera Maya calibrata girata 90 e lontana dall'origine; telefono avanza 10 cm")
