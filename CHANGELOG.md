# CHANGELOG — MagiCAM

Una voce per commit che cambia comportamento, in testa: cosa, perche', cosa e' stato misurato, cosa resta aperto.
«Misurato» vuol dire eseguito, con il numero in `docs/MISURE.md`; altrimenti la voce dice «scritto, non misurato».

### v2 — Regia dal vivo R4: iPhone da ripresa — 2026-10-16

**Cosa.** (1) Mentre trasmette, l'app spegne il blocco automatico dello schermo (`isIdleTimerDisabled`, rimesso
quando si ferma): prima non lo toccava, e tenendo il telefono senza toccarlo l'app andava in sottofondo allo scadere
del blocco. (2) In cima alla vista, un banner grande colorato e un pulsante REC grande (64 pt): il banner lo decide
`LiveStatus` in MagiCAMCore (Swift puro, con test) solo da cio' che il PC CONFERMA con le sue stats — verde «DAL VIVO»
solo con stats fresche (< 3 s), calibrata, tracking normale, senza freeze; rosso «MAYA NON RISPONDE» senza stats,
anche se la rete UDP e' «pronta» (quindi anche quando il ponte in Maya si ferma per un guasto R3). (3) Stato termico:
«caldo» arancio, «critico» rosso con l'invito a fermarsi.

**Misurato.** Niente sul telefono ancora. `LiveStatusTests` (4 test, ogni stato contro il suo opposto) e la build:
vedi il run CI del commit.

**Aperto.** Da provare sul telefono: lo schermo resta acceso oltre il blocco automatico; il banner passa a rosso
quando si ferma il pannello in Maya. Installazione con Sideloadly (PC sull'hotspot, Surfshark spento).

### v2 — Regia dal vivo R1-R3: take sulla timeline, una camera per take, guasti che si dicono — 2026-10-16

**Cosa.** Dai quattro bloccanti misurati in docs/VALUTAZIONE_REGIA_LIVE.md. **R1** il tick scrive nel campione il
fotogramma a video, solo mentre Maya riproduce; Rec (`rec_plays_timeline`, predefinito) fa partire il playback una
volta, a tempo reale, dall'inizio del range, e la take finisce quando il playback finisce; le chiavi vanno sui
fotogrammi visti (`keys_for_take` → `resample_timeline`, formato take 2 col campo `frame`, il formato 1 si legge
ancora), altrimenti «a tempo» dal fotogramma del Rec, mai da quello dello Stop. **R2** la camera dal vivo non deve
avere animazione (`start` rifiuta, con il motivo), e ogni take si cuoce su una camera NUOVA, copia di quella dal vivo,
nel gruppo `magicam_takes_grp` a origine: niente lotta curve/dal vivo, niente coda della take prima, valori nel mondo
anche se la camera dal vivo sta in un rig. **R3** camera sparita, scena nuova o aperta (`deleteAll`), errore nel tick:
il ponte si ferma UNA volta, salva la take e scrive il motivo in `fault`; lo stop (pannello chiuso, telefono, fine
playback) salva sempre la take e mette gli errori in `last_error`. Pannello: casella «Rec fa partire la timeline»,
guasto in rosso, take con camera e modo («sui fotogrammi visti» / «dal fotogramma del Rec»), camera predefinita
`magicam_live`.

**Misurato.** In Maya prima di scrivere: `cmds.play` torna in 2 ms, il timer scatta una volta per fotogramma in
playback. Dopo la cura, stesso banco di prima (docs/MISURE.md): C chiavi 0-74 sui fotogrammi visti; testina spostata a
mano → 37-99 a tempo; camera dal vivo senza curve, 0,0 cm al cambio di fotogramma; camera con chiavi rifiutata; camera
cancellata → 1 errore invece di 59 al secondo. Il primo giro dopo la cura ha trovato due difetti nuovi (chiave del Rec
mancante, scrub preso per playback): curati, con test e rimisurati. Test: 116 verdi (7 nuovi sulla timeline).

**Aperto.** Prova «scena nuova» non fatta (scena dell'utente in uso). Mai provato col telefono vero sopra
un'animazione. Un Rec dal telefono a timeline ferma con Maya che non riproduce va «a tempo» (voluto).

### v2 — Pannello rifatto, icona e pulsante nella shelf — 2026-10-16

**Cosa.** `magicam/ui/panel.py` riscritto: sezioni Collegamento / Camera / Take / Dal telefono, spia colorata dello
stato visto dal PC (fermo, in attesa del telefono, collegato ma da calibrare, dal vivo a N Hz, FREEZE, tracking non
normale, COLLEGAMENTO PERSO), IP del PC da scrivere sull'app, codice grande, elenco delle camere della scena con
«Nuova» e «Guarda», pose al secondo calcolate dai contatori veri, stato del tracking dell'ultima posa, take avviata
dal telefono mostrata anche nel pannello. Stesse funzioni di bridge e sessione di prima. Corretto anche il silenzio
del collegamento: il pannello lo misurava con `time.monotonic` contro un istante del ricevitore preso con
`perf_counter` (orologi diversi, numero senza senso). Nuovi `magicam/ui/icons/magicam_shelf.svg` e
`magicam/ui/shelf.py` (`install("Custom")`: copia l'icona tra le icone di Maya, pulsante idempotente, salva SOLO
quella shelf dopo una copia `shelf_Custom.mel.bak_magicam_<data>`).

**Misurato.** In Maya 2026 dell'utente: pannello aperto, pulsante sulla shelf Custom, file salvato con 6 pulsanti
(i 5 di prima + MagiCAM, diff col backup = solo il blocco nuovo). Difetto trovato rileggendo il file: il pulsante
creato con la scheda non in vista era salvato con `-visible 0` (al riavvio sarebbe sparito); dopo la cura
(`visible=True` e scheda mostrata prima di `saveShelf`) `-visible 1`, e `install` ora rilegge il file e si ferma se
il blocco dice `-visible 0`. Il riavvio di Maya col pulsante non e' ancora stato provato. Il pannello nuovo non e'
ancora stato usato con il telefono collegato.

### v2 — iPhone: formato video a fps massimi e PING alla connessione pronta — 2026-10-16

**Cosa.** Due correzioni nate dal primo collegamento dal vivo (docs/MISURE.md, F2.6). (1) `ARSessionManager.start`
sceglie in `ARWorldTrackingConfiguration.supportedVideoFormats` (fotocamera posteriore) il formato con piu' fps, a
parita' quello con piu' pixel (`VideoFormatPicker` in MagiCAMCore), invece del default, che su quel telefono girava a
30 fps (327 frame in 10,90 s dal t_sensor); la vista mostra il formato scelto e quelli disponibili, e il PING
periodico va agli fps del formato (prima «ogni 60 frame» = ogni 2 s a 30 Hz). (2) `UDPLink` (spostato in MagiCAMCore)
ha un `greeting`: il PING col codice parte quando la connessione passa a `.ready`, a ogni passaggio, sotto lo stesso
lock dei `send`, quindi prima di ogni posa. Prima il PING partiva subito dopo `connect`, a link non pronto, e `send`
lo scartava in silenzio: le pose arrivavano «non abbinate» fino al PING del 60° frame (31 all'avvio il 2026-10-16).

**Misurato.** `swift test` di MagiCAMCore in CI (non c'e' Swift su questo PC): banco su UDP vero in loopback, le
pose spedite da PRIMA che il link sia pronto; il primo datagramma di ogni connessione (anche la seconda) e' il PING,
uno solo. Contrasto nello stesso banco col modo di prima (PING subito dopo `connect`, niente greeting): `send`
restituisce false e il PING non arriva mai, le pose si'. Esito in CI e build dell'.ipa: vedi il run del commit.

**Aperto.** Sul telefono non misurato: quanti fps da' davvero il formato scelto (t_sensor, come F2.6) e che il PC
abbini dalla prima posa (0 «non abbinate»). Lo installa l'utente con Sideloadly. Se il telefono offre solo formati
a 30 fps la vista lo dice («Disponibili: …»).

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
