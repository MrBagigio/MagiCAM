# CHANGELOG — MagiCAM

Una voce per commit che cambia comportamento, in testa: cosa, perche', cosa e' stato misurato, cosa resta aperto.
«Misurato» vuol dire eseguito, con il numero in `docs/MISURE.md`; altrimenti la voce dice «scritto, non misurato».

### v2 — Bake in blocco misurato, undo pulito, il «Maya inchiodato» che non lo era — 2026-10-15

**Pannello in Maya (F1.10), stesso giorno.** Aperto nel Maya dell'utente su una camera nuova, simulatore a 60 Hz:
Calibra → cerchio Ø 99,2 cm; Freeze → 0 movimento con 229 pose in arrivo; Rilascia → prima posa a 1,5 cm dalla
congelata (un passo); scala 0,1 → Ø 10,08 cm, primo passo 0,131 cm; Rec 20,5 s → 492/492 chiavi. La prima misura dei
«salti» (11,7 e 56 cm) era lo strumento (campioni dal PC in ritardo): rifatta dentro Maya posa per posa. Il gateway
dcc-mcp ha perso di nuovo l'istanza: `tests_maya/mcp_gateway.py` ora parla direttamente col server MCP dentro Maya
quando il gateway tace.

**Cosa.** `bake_take` scrive le curve con `MFnAnimCurve.addKeys` (canali da `takes.channel_curves`, Euler XYZ continui
scegliendo la terna piu' vicina alla precedente); le pose dal vivo non entrano nella coda di undo
(`undoInfo(stateWithoutFlush=False)` attorno a xform/setAttr, `live_undo=True` solo per il contrasto); banchi con
guardia sulla scena (nome o oggetti), ripristino dell'unita', `run_bench_bake.py`, `run_stress_maya.py` con parziali.
App iOS (scritta, non compilata): Freeze/Rec a video dai FLAG del PC, slider logaritmico della scala (SCALE_SET),
feedback aptico.

**Misurato (docs/MISURE.md).** Bake API: 14354 chiavi in 0,174 s, lineare, chiave a meta' esatta, 0 salti Euler,
annullabile (4 undo tolgono bake e curve). Bake vecchio: lineare, 0,87 ms/chiave (~12,5 s a 14354): il blocco di 55
minuti NON era il bake. Quel Maya a 85-88% di CPU e 11 GB era il suo stato di RIPOSO: misurato sulla seconda istanza
vuota, 85% di un core sul main thread (native_id 53668) con uno scriptJob `idleEvent` di dcc-mcp, 10,6 GB privati
prima di qualunque cosa di MagiCAM. A cadere fu il ponte main-thread di dcc-mcp dopo il timeout della chiamata lunga
(ipotesi che regge ai dati, non provata). Correzione di cio' che avevo scritto prima: «Maya inchiodato nel bake».
Stress 120 s (undo on / off): 7200/7200, 0 perse, +27% di un core per il live, memoria ±20 MB (rumore), cima
dell'undo dopo il live non piu' un xform. 114 test fuori da Maya.

**Aperto.** Stress 10 min VALIDO (ogni giro di oggi aveva un mayapy di un'altra chat accanto); l'85% di CPU a riposo
del Maya dell'utente e' un fatto da riferire a chi mantiene dcc-mcp, non di MagiCAM; F2.6 iPhone; pannello aperto
in Maya per la prova dell'utente (esito da scrivere).

### v2 — Prime misure nel Maya vero (2026): convenzione, bridge, latenza, take — 2026-10-15

**Cosa.** `tests_maya/`: `mcp_gateway.py` (client MCP streamable-HTTP per il gateway dcc-mcp del Maya aperto),
`f1_1_convenzione_xform.py` (F1.1), `bench_bridge.py` + `run_bench_bridge.py` (F1.8/F1.9/F3: simulatore dal PC,
bridge dentro Maya). Cure nate dalle misure: `Qt.TimerType` (non `QTimer.TimerType`: il bridge non partiva);
matrice di `xform` in cm INTERNI sempre (`INTERNAL_UNITS_PER_METER`); niente `SO_REUSEADDR` sull'UDP (un orfano
rubava i pacchetti in silenzio); `Receiver.drain_recent()` e tick che passa TUTTE le pose a sessione e take;
`perf_counter` al posto di `monotonic` (15,6 ms di passo su Windows); One Euro tarato (beta 10) con velocita'
angolare come vettore firmato; simulatore `--clock host`.

**Misurato (docs/MISURE.md, docs/CONVENZIONI.md).** F1.1: convenzione riga-vettore confermata, contrasto v1 →
yaw −20 e traslazione persa; traslazione della matrice in cm anche a metri. F1.8: 3600/3600, 0 fuori ordine,
tick 17,0 ms, costo max 2,3 ms, fedelta' 0,5 cm / 0,6°; a METRI prima della cura 1/100 del moto. F1.9: latenza
simulatore→xform p50 8,7 ms, p95 16,4, max 18,1. F3: 30,1 s → 723 chiavi, 0 salti Euler. 104 test fuori da Maya.

**Aperto.** F2.6 (iPhone: verso del moto dal vivo, latenza telefono→viewport, rumore vero per min_cutoff), F4.5 in
Maya (10 min), F3.4 (take dal vivo), pannello PySide6 non ancora aperto in Maya (F1.10), Swift non compilato.

### v2 — F4: pairing, Bonjour, tracking perso, Wi-Fi caduto, stress — 2026-10-15

**Cosa.** `receiver`: abbinamento del mittente con PING/comando col token (TTL 3 s), pose non abbinate contate in
`unpaired`; `session`: ri-ancoraggio senza salto quando il tracking torna normale o fra due pose passa piu' di
`gap_threshold_s` (0,5 s), contatore `reanchors`; `discovery.Advertiser` (zeroconf, opzionale);
`stress` (receiver → session → recorder a 60 Hz, tracemalloc, costo per posa). Bridge: `new_token`,
`require_token`, Bonjour all'avvio, `link_lost` dal silenzio del receiver. Pannello: codice, «Richiedi codice»,
«COLLEGAMENTO PERSO da N s», non abbinate, ri-ancoraggi. App iOS (scritta, non compilata): campo codice,
PING al secondo, `PCBrowser` (NWBrowser `_magicam._udp`), connessione all'endpoint Bonjour, `NSBonjourServices`.

**Perche'.** PIANO §2.3 R3 (tracking ignorato), R5 (rete aperta, Bonjour dichiarato e mai fatto), §0.3 (Wi-Fi che
cade senza salti).

**Misurato (fuori da Maya).** 13 test nuovi: pose non abbinate = 0 effetto e contate (anche un secondo dispositivo
che spara pose a 5 m: l'ultima posa resta quella del telefono abbinato); abbinamento scaduto dopo 3 s; tracking
limited per 2 s con pose che saltano → camera ferma, al ritorno 0 salto (contrasto: con la vecchia calib > 3 m)
e il passo dopo vale 10 cm; buco di 0,8 s → riparte da dov'era; buco di 0,4 s → nessun ri-ancoraggio; Bonjour
visto da un browser mDNS sulla stessa macchina. Stress 20 s a 60 Hz in loopback: 1200/1200 accettate, 0 perse,
update medio 98 us (max 485), memoria +1,24 MiB (la take: ~1 KiB per campione → ~36 MiB per 10 minuti).

**Aperto.** Stress DENTRO Maya (F4.5: CPU e memoria del processo Maya, 10 min); Bonjour col telefono vero;
il peso della take in memoria (1 KiB/campione: da stringere se le take lunghe pesano).

### v2 — F3: take per timestamp, chiavi agli fps della scena — 2026-10-15

**Cosa.** `magicam/takes.py`: `TakeRecorder` (un campione per posa applicata, col `t_sensor`; in hold tiene l'ultima
posa; scarta tempo che non avanza), `resample` (una chiave per fotogramma, lerp posizione e slerp rotazione per
TEMPO; floor(durata·fps)+1 chiavi), `save_take`/`load_take` (JSON grezzo, tmp + `os.replace`, mai sovrascrive,
rifiuti tipizzati), `TakeLibrary` (accanto alla scena; `discard` sposta in `_cestino/`), `fps_from_maya_time_unit`.
`maya_bridge`: `start_take`/`stop_take` (anche dai comandi del telefono), `bake_take` (xform + setKeyframe per
fotogramma dal fotogramma corrente, focale, `filterCurve` sugli Euler, un solo blocco di undo). Pannello: Rec/Stop,
nome take, «chiavi allo stop».

**Perche'.** PIANO §2.2 T1: il v1 scriveva una chiave per PACCHETTO e avanzava la timeline di un fotogramma: 60
pacchetti/s su 24 fps = take 2,5x veloce, buchi dove l'operatore stava fermo.

**Misurato (fuori da Maya, `tests/test_takes.py`, 19 test).** 600 campioni a 60 Hz → 240 chiavi a 24 fps, durata
9,96 s (contrasto v1: 600 chiavi = 25 s); 10% di campioni persi → ancora 240 chiavi contigue, posizioni esatte sul
moto lineare; operatore fermo 3 s → camera ferma 3 s; hold registra l'ultima posa; file corrotti rifiutati.

**Aperto.** `bake_take` e il pannello in Maya (F3.4: take dal vivo di 20 s, playblast, confronto col video del
telefono). Ricuocere con altra scala dal `phone` grezzo (campo salvato, funzione non scritta). Lista take nella UI.

### v2 — F2: app iOS scritta, non compilata — 2026-10-15

**Cosa.** `ios/Packages/MagiCAMCore`: il protocollo in Swift puro (`Protocol.swift`, `PoseEncoder.swift`, byte per
byte little-endian, niente `withUnsafeBytes` di struct) con XCTest sugli STESSI tre vettori esadecimali di
`tests/test_protocol.py` (pose, command, stats: ora fissati anche lato Python). App `ios/MagiCAM`: `UDPLink`
(Network.framework, riceve le stats del PC), `ARSessionManager` (OGNI frame, `frame.timestamp`, stato e ragione del
tracking, intrinseche, esposizione; ricentra da solo quando il tracking riprende dopo una rilocalizzazione),
`ContentView` (Avvia, Calibra, Ricentra, Freeze, Rec; a video solo i numeri del PC piu' i pacchetti spediti).
Progetto da `ios/project.yml` (XcodeGen), Info.plist generato. CI: `swift test` del pacchetto, poi XcodeGen e build
non firmata per `generic/platform=iOS` → `.ipa`.

**Perche'.** PIANO §2: il v1 inviava solo se il telefono si muoveva (buchi), ignorava il tracking, mentiva a video
(contatore a timer), aveva un pbxproj a mano e tre formati.

**Misurato.** Niente: su questa macchina non c'e' Swift. I vettori Python sono verdi; quelli Swift li prova la CI
(ferma: account GitHub Actions bloccato). Il codice Swift e' «scritto», non «compilato».

**Aperto.** Compilazione e `swift test` in CI (F2.5); installazione con AltStore e prova dal vivo delle 6 righe della
tabella + latenza telefono→viewport (F2.6); Bonjour (F4.2); token di pairing lato app (campo presente, sempre 0).

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
