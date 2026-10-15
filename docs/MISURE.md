# Misure — MagiCAM v2

Ogni riga: data, sha, macchina/Maya/iOS, cosa, come (comando o banco), atteso scritto PRIMA, misurato. Una voce del
piano e' «fatta» solo se la sua misura sta qui.

| data | sha | dove | cosa | atteso (prima) | misurato | note |
|---|---|---|---|---|---|---|
| 2026-10-15 | (F0+F1) | PC Windows, Python 3.10, senza Maya | `math3d.apply_anchor` sui 7 casi noti | tabella in CONVENZIONI.md | 7/7 entro 1e-9 | numpy come oracolo; killer rosso con la convenzione v1 → fallisce come deve |
| 2026-10-15 | (F0+F1) | idem | `receiver` vs simulatore, 5% perdita + 2% riordino, 600 pacchetti a 60 Hz loopback | persi = quelli non inviati dal simulatore, 0 pose vecchie applicate | vedi `tests/test_receiver.py` | loopback, non Wi-Fi |
| 2026-10-15 | (F4) | PC Windows, Python 3.10, loopback, senza Maya | `python -m magicam.stress --duration 20` | 0 perse, update < 500 us, memoria ≈ take | 1200/1200 accettate, 0 perse/riordinate, update medio 98,5 us (max 485), +1239 KiB per 1197 campioni (≈1 KiB/campione) | 3 pose su 1200 non applicate: arrivate nello stesso ms, il tick tiene l'ultima (per scelta) |
| 2026-10-15 | (F1.1) | Maya 2026, Py 3.11.9, cm, via gateway dcc-mcp, farm ferma (C: 120 GB, commit libero 19,8 GB) | `tests_maya/f1_1_convenzione_xform.py` | lista riga-vettore, traslazione 12-14; contrasto v1 diverso | A-E tutti ✔; contrasto v1: t=(0,0,0), yaw −20; traslazione della matrice in cm INTERNI anche a metri | vedi CONVENZIONI.md |
| 2026-10-15 | (F1.8) | idem, scena cm, simulatore `circle` 60 Hz × 60 s dal PC (`tests_maya/run_bench_bridge.py`) | coda, costo tick, ordine, fedelta' | 0 fuori ordine; salti seq ≈1; costo tick ≪ 16 ms; \|cam−A\| = \|P−C\| | 3600/3600 accettate, 0 perse/riordinate/indietro; 3600 pose a sessione e take; tick dt 17,0 ms (p95 17,7, max 33,7); costo max 2,3 ms; salti: 3303×1, 104×2, 1×3; err. distanza 0,53 cm, rotazione 0,62° | prima versione (solo `latest()`): 19% pose non alla take → ora `drain_recent()` |
| 2026-10-15 | (F1.8 unita') | idem, scena a METRI, 60 Hz × 10 s | contrasto unita': stessa fedelta' in m | err. distanza ≤ 2 cm | PRIMA: −41,5 cm (camera mossa di 1/100: matrice in cm interni); DOPO la cura: −1,0 cm, rot 0,62°, 600/600 | il difetto l'ha trovato il contrasto, non il caso cm |
| 2026-10-15 | (F1.9) | idem, cm, `--clock host` (perf_counter condiviso) | latenza simulatore→xform | mediana ≤ 33 ms (2 frame a 60 Hz) | p50 8,7 ms, p95 16,4, max 18,1 (n=3409) | con time.monotonic i valori erano quantizzati a 15,6 ms: strumento scartato |
| 2026-10-15 | (F1.9 taratura) | PC, `tests/test_filter_tuning.py` | One Euro min_cutoff 1, beta 10 | ritardo ≤ 2 cm a 0,8 m/s, ≤ 2° a 90°/s, rumore 2 mm/0,2° attenuato ≥ 3× | 4/4 verdi; in Maya sul cerchio (0,78 m/s, 90°/s): 0,5-1,0 cm, 0,62° | beta 0.05 del paper: ~12 cm di ritardo; velocita' angolare come vettore firmato |
| 2026-10-15 | (F3 in Maya) | idem, take dal simulatore 30,1 s dentro il banco cm, `bake_take` a 24 fps | chiavi = floor(durata·fps)+1, 0 salti Euler | 723 | 1808 campioni (60 Hz), 723/723 chiavi su translate e rotate, fotogrammi 1-723, 0 salti > 180°, 0,99 s, undo «MagiCAM take» | prima versione: 1326 campioni (43 Hz) per lo stesso motivo di F1.8 |

Da fare: F2.6 (iPhone dal vivo, latenza telefono→viewport, rumore vero di ARKit per min_cutoff), F4.5 dentro Maya (10 min,
CPU e memoria del processo), F3.4 (take dal vivo col telefono).
