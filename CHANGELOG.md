# CHANGELOG — MagiCAM

Una voce per commit che cambia comportamento, in testa: cosa, perche', cosa e' stato misurato, cosa resta aperto.
«Misurato» vuol dire eseguito, con il numero in `docs/MISURE.md`; altrimenti la voce dice «scritto, non misurato».

### v2 — F0+F1: fondamenta e lato Maya senza Maya — 2026-10-15

**Cosa.** Il POC di gennaio va in `legacy/` (storia conservata, tag `legacy-2026-01`); nasce il pacchetto `magicam`:
`protocol` (datagramma binario versionato), `math3d` (quaternioni, trasformazioni, ancora e scala relativa, con la
convenzione di Maya dichiarata in un solo punto), `filters` (One Euro), `receiver` (thread UDP che tiene l'ultima posa
e conta persi/riordinati/latenza), `simulator` (telefono finto con traiettorie note, perdita e riordino), `session`
(ancora, scala, freeze, recenter), `maya_bridge` (l'unico modulo che importa `maya`), `ui` (pannello PySide6).
CI: ruff, mypy strict, pytest su 3.10 e 3.11; workflow iOS pronto ma fermo fino a `ios/project.yml` (F2).

**Perche'.** `docs/PIANO_DI_LAVORO.md` §2: moto invertito, calibrazione che perde la posizione, comandi del telefono
mai recapitati, tempo legato alla rete, test che codificavano il difetto.

**Misurato.** Solo fuori da Maya: i test di `math3d` contro le risposte note della tabella §2.1 (6 casi + ancora fuori
dall'origine + scala), con numpy come oracolo indipendente e un killer rosso che ripercorre la convenzione di v1;
`receiver` contro il simulatore con perdita e riordino noti (conteggi esatti); `filters` su gradino e rumore.

**Aperto.** La convenzione di `xform -matrix` e' DICHIARATA in `magicam/math3d.py` e `docs/CONVENZIONI.md`, non
misurata in Maya (F1.1, aspetta il si' dell'utente con la farm ferma). `maya_bridge` e `ui` sono scritti e non
eseguiti in Maya (F1.8-F1.10). Nessuna misura dal vivo di latenza (F1.9). Il ramo `v2` parte da `1c3ad1b` (punta
del ramo feature) e non da `master`, diversamente dal piano F0.2: cosi' `legacy/` tiene anche i 32 commit del lavoro
vero. Licenza da decidere (repo pubblico senza LICENSE). La CI su GitHub NON e' girata al primo push (2026-10-15 09:11 UTC, run 38711072226/537): «account locked due to a billing issue» su GitHub Actions; i quattro controlli (ruff, format, mypy, pytest) sono verdi solo in locale.
