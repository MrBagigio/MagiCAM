# Misure — MagiCAM v2

Ogni riga: data, sha, macchina/Maya/iOS, cosa, come (comando o banco), atteso scritto PRIMA, misurato. Una voce del
piano e' «fatta» solo se la sua misura sta qui.

| data | sha | dove | cosa | atteso (prima) | misurato | note |
|---|---|---|---|---|---|---|
| 2026-10-15 | (F0+F1) | PC Windows, Python 3.10, senza Maya | `math3d.apply_anchor` sui 7 casi noti | tabella in CONVENZIONI.md | 7/7 entro 1e-9 | numpy come oracolo; killer rosso con la convenzione v1 → fallisce come deve |
| 2026-10-15 | (F0+F1) | idem | `receiver` vs simulatore, 5% perdita + 2% riordino, 600 pacchetti a 60 Hz loopback | persi = quelli non inviati dal simulatore, 0 pose vecchie applicate | vedi `tests/test_receiver.py` | loopback, non Wi-Fi |

Da fare: F1.1 (convenzione xform in Maya 2025), F1.8 (coda e costo per tick in Maya), F1.9 (latenza simulatore→camera,
taratura One Euro), F2.6 (iPhone dal vivo, latenza telefono→viewport).
