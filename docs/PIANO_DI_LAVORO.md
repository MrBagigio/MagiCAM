# MagiCAM — documento di lavoro: quadro, verdetto e To-Do verso la barra AAA (WETA FX)

Scritto il 2026-10-15 dalla sessione «MagiCAM» a partire da un clone di lettura di https://github.com/MrBagigio/MagiCAM
(scratchpad della sessione, sha di `feature/stress-ci-and-receiver-tuning` = `1c3ad1b`). Niente modificato nel repo,
niente push. Questo file passa nel repo come `docs/PIANO_DI_LAVORO.md` alla fase F0 e da li' si aggiorna.

Legenda delle prove: **[D]** dimostrato (con la prova citata) · **[L]** letto nel codice, non eseguito ·
**[NM]** non misurato: ipotesi, da provare prima di costruirci sopra.

---

## 0. La barra

Una camera virtuale che uno studio AAA mette in mano a un operatore pretende:

1. **Fedelta'**: il moto del telefono si ripete identico sulla camera, in ogni direzione, da qualunque posa di partenza,
   con la camera di Maya in qualunque punto del mondo (non solo all'origine). Scala del mondo scelta dall'operatore
   (1:1, 1:10 per «camminare in una miniatura»), applicata al moto RELATIVO all'ancora di calibrazione.
2. **Tempo**: ogni campione porta il timestamp del sensore; la take si registra per tempo e si cuoce agli fps della scena;
   latenza telefono→viewport misurata, non stimata; la timeline di Maya non dipende dalla rete.
3. **Robustezza**: perdita di pacchetti, riordino, perdita di tracking ARKit (limited/relocalizing), Wi-Fi che cade,
   Maya lenta: niente salti, niente coda che cresce, niente crash, e lo stato detto a video.
4. **Ergonomia da set**: calibra/ricentra con un tasto, «freeze» (congela la camera mentre l'operatore si risistema),
   blocchi d'asse (dolly, altezza), zoom/focale, take con nome e metadati, ripeti la take.
5. **Codice da pipeline**: pacchetto installabile, nessuno stato globale, tipi, log, errori che parlano, test che
   diventano rossi quando il comportamento e' sbagliato (provato revertendo la cura), CI che compila davvero l'app,
   documentazione che corrisponde al codice, versione del protocollo.
6. **Lente**: la camera virtuale ha una lente (focale, filmback, near/far) coerente con cio' che l'operatore vede sul
   telefono; senza, l'inquadratura che l'operatore compone non e' quella che Maya rende.

Lo stato attuale sta sotto la barra su tutti e sei i punti. Sotto, punto per punto, cosa e come e' stato visto.

---

## 1. Cos'e' e com'e' fatto oggi

iPhone (ARKit world tracking) → UDP JSON → Maya applica la posa a una camera. In piu': calibrazione, 5 smoothing,
registrazione di chiavi, modo «elicottero» (joystick), streaming del viewport verso il telefono. Scritto il 20-21/01/2026
quasi interamente con un assistente AI (il README parla in prima persona come un assistente: «Ho aggiunto…», «Vuoi che crei…»).

| Ramo | Commit | Contenuto |
|---|---|---|
| `master` (default) | 2 | POC iniziale, 1.505 righe |
| `main` | 7 | master + 5 commit per far compilare un pbxproj scritto a mano |
| `feature/stress-ci-and-receiver-tuning` | 32 (fino al 21/01 15:05) | il lavoro vero: receiver 2.025 righe (~80 globali), ContentView 940, test, Launcher, tool |

CI (GitHub Actions, log scaduti con HTTP 410, quindi solo gli esiti): ultimo build iOS (`1c3ad1b`, elicottero) **rosso**;
«Python package tests» alterna rosso e verde negli ultimi 8 push. La causa del rosso iOS **[NM]**: non si legge piu'.

---

## 2. Difetti, rivalutati

### 2.1 Fedelta' — rotti i fondamentali

**F1 [D] La matrice arriva in una convenzione e Maya la legge in un'altra.** Swift (`ARSessionManager.swift:95-115`)
manda la 4x4 riga per riga con la traslazione agli indici 3,7,11 (colonna-vettore). `cmds.xform(matrix=…)` e
`om.MMatrix(list)` leggono riga-vettore: assi nelle righe, traslazione in 12,13,14. La rotazione arriva trasposta
(= inversa). Il codice ci ha messo sopra due riflessioni (`FLIP_YAW`, `FLIP_PITCH`, `maya_receiver.py:307-348`) e un
`xform translation` separato (`:510-515`) per salvare la traslazione. Prova: `scratchpad/sim_magicam.py`, che emula la
convenzione di Maya (vedi 3.1 per il limite). Calibrazione a identita':

| Telefono | Camera in Maya (simulata) | Atteso |
|---|---|---|
| fermo nella posa di calibrazione | ferma | ferma ✔ (riferimento) |
| yaw +20° (gira a sinistra) | yaw −20° | +20° ✘ |
| pitch +20° (alza il muso) | +20° | +20° ✔ |
| +10 cm a destra (+X) | −10 cm | +10 ✘ |
| avanza 10 cm (−Z) | +10 cm (arretra) | −10 ✘ |

I 12 commit del 21/01 «fix coordinate conversion» (`299f0af` … `6fa6a5e`) inseguono questo difetto a segni: un asse alla
volta, senza una risposta nota scritta prima. Il «pitch giusto» e' un caso: la riflessione su Z e X lascia la rotazione
attorno a X invariata.

**F2 [D] La calibrazione perde la posizione della camera.** `CALIB = desired · inv(incoming)` e poi `final = CALIB · pose`
(`:932-960`, `:548-553`). `desired` viene da `xform -q -matrix` (traslazione in 12-14), quindi il prodotto mette la
traslazione di Maya in 12-14; il codice la rilegge da 3,7,11 (`_set_matrix`). Simulato: camera calibrata a (500,150,0)
girata di 90°, telefono avanza 10 cm → camera a (−10, 0, 0) invece che a (490, 150, 0). All'origine il difetto e'
invisibile (D1: uno spazio si prova fuori dall'origine).

**F3 [L] La scala del moto e' applicata alla posa ASSOLUTA, non al moto relativo.** `_scale_matrix` (`:360-406`) scala
la traslazione del telefono rispetto all'origine di ARKit (il punto dove l'app e' partita) e l'angolo della rotazione
assoluta. Con `TRANSLATION_SCALE=0.25` e il telefono a 2 m dall'origine, la calibrazione poi lo riporta sulla camera, ma ogni
passo dell'operatore viene scalato attorno a un punto che non e' l'ancora: la camera «orbita». I preset Slow/Fast
(`:1260-1292`) sono questo.

**F4 [L] Unita' cablate.** Swift moltiplica per 100 (`translationScale = 100.0`, cm); il receiver non legge
`cmds.currentUnit`. Scena in metri o pollici → 100x o 39x.

**F5 [L] Nessuna lente.** Il pacchetto porta solo la posa. Focale, filmback, near/far della camera di Maya non sono
toccati: cio' che l'operatore inquadra sul telefono non e' cio' che Maya rende (barra, punto 6). ARKit espone
`camera.intrinsics` e `imageResolution`: non sono usati.

### 2.2 Tempo

**T1 [L] La registrazione lega la timeline alla rete.** Una chiave per pacchetto e `currentTime +1` (`:518-526`): 60
pacchetti/s su una scena a 24 fps = take 2,5x veloce; con il Wi-Fi che balbetta il tempo si deforma. Il telefono inoltre
non invia se non si muove di ≥1 mm / soglia di rotazione (`ARSessionManager.swift:70-89`): la take ha buchi dove
l'operatore e' fermo, e la timeline si ferma con lui.

**T2 [L] Il timestamp `t` e' inviato e mai usato.** Il receiver non misura latenza, non riordina, non scarta pacchetti
vecchi; il sequence number non esiste. L'orologio del telefono e del PC non sono messi in relazione.

**T3 [L] Il modo elicottero muove «per pacchetto», non per secondo.** `_process_joystick` (`:1005-1086`) somma
`move_speed` a ogni messaggio (30 Hz nominali): la velocita' del drone dipende dalla frequenza dei pacchetti, non da dt.
Il joystick dell'app normalizza dividendo per 50 (`ContentView.swift:82-85`) ma la manopola arriva al massimo a
`(size−knob)/2` = 36 px (size 120) o 42 px (140): il drone non raggiunge mai il 100% (72% / 84%).

### 2.3 Robustezza

**R1 [L] Dal telefono passa solo la posa.** `_server_loop` (`:678-750`) legge da ogni pacchetto il solo campo `matrix`
e lo reimpacchetta come `pose`. I messaggi `calib`, `cmd` (heli_on/off, reset_calib) e `joystick` via UDP non arrivano
mai al loro gestore in `_process_packet`. Dunque: Calibra dal telefono = una posa qualunque; modo drone dal telefono =
morto (l'app invia solo UDP JSON, mai OSC). Il rosso di CI e la storia dei commit non lo sanno.

**R2 [L] Thread e main thread.** `cmds.evalDeferred` chiamato da thread di fondo a ogni pacchetto (60 Hz) e dal thread
di interpolazione: se Maya e' lenta la coda cresce e la camera insegue il passato; `cmds.xform(q=True)` chiamato da un
thread di fondo in `_enable_helicopter_mode` e in `_calibrate_from_incoming` (non e' sicuro fuori dal main thread).
Nessuna misura della profondita' della coda.

**R3 [L] Stato del tracking ignorato.** ARKit segnala `.limited(.initializing/.relocalizing/.excessiveMotion/
.insufficientFeatures)` e `.notAvailable`: l'app invia comunque, Maya applica comunque. Al riavvio del tracking la
camera salta.

**R4 [L] Smoothing che deforma.** `matrix_exp` fa la media elemento per elemento della 4x4 (`:585-590`) con
l'ortonormalizzazione disattivata «perche' corrompeva la scala» (`:279-284`): il risultato ha taglio e scala. Cinque modi
(`none`, `matrix_interp`, `matrix_exp`, `alpha_beta`, `kalman` = lo stesso alpha-beta) con 9 parametri a video: nessuno
tarato con una misura, nessuno con una risposta nota.

**R5 [L] Rete aperta.** UDP su `0.0.0.0` senza pairing ne' token: ogni dispositivo sulla LAN muove la camera. Il
servizio Bonjour `_magicam._udp` e' dichiarato nell'Info.plist e mai implementato: l'operatore scrive l'IP a mano.

**R6 [L] Streaming del viewport.** `playblast` su file PNG a ogni fotogramma (`:1875-1935`), cambio della camera del
primo `modelPanel` (anche se e' quello dell'artista), `_PENDING_STREAM_FRAME` condiviso fra thread senza lock, 15 fps
nominali. Per un monitor di set serve la cattura del buffer (`omui.M3dView.readColorBuffer`) o la texture, non il disco.

### 2.4 Codice e processo

**C1 [L] Un file, ~80 variabili globali, 23 `except Exception: pass/print`** (contati con grep su `maya_receiver.py`).
Ogni funzione legge e scrive globali; i preset scrivono sia i widget sia i globali; `_ui_start` salva 10 preferenze e
ne dimentica 8 (flip, scale, heli, stream); `_ui_start_stream` ricarica e riscrive il file: due scrittori.

**C2 [L] I test non possono fallire per il difetto giusto.** `tests/conftest.py`: `MMatrix.inverse()` restituisce la
matrice stessa («sufficiente per i test»); il finto `MMatrix.__mul__` moltiplica le liste nella convenzione del codice,
non in quella di Maya; `test_process_packet_applies_matrix` PRETENDE la traslazione in 3,7,11 (codifica F1);
`test_validate_matrix_good` accetta `[1.0]*16`, che non e' una trasformazione rigida; `test_stress_basic` accetta il 60%
di pacchetti persi. Nessun test con una risposta nota («gira a sinistra → la camera gira a sinistra»). Nessuno e' stato
provato rosso revertendo una cura.

**C3 [L] L'app mente a video.** `frameCount` sale con un timer da 0,5 s (`ContentView.swift:66-70`), non coi pacchetti
inviati: la statistica «frames» e' un orologio. Un canale che mente e' peggio di uno che tace.

**C4 [L] Build e CI.** pbxproj scritto a mano (ID `A1…F6`), 5 commit per farlo compilare; `tools/build_ios.sh` punta a
`swift/MagiCAM.xcodeproj` e allo scheme `ARKitSender`, che non esistono; `swift/ARKitSender.swift` (UIKit legacy) e'
compilato nel target insieme alla app SwiftUI; `Info.plist` su master pretende `armv7`; su feature dichiara
`UILaunchScreen.UIColorName = LaunchScreenBackground` senza asset. Il rosso dell'ultimo build e' senza log.

**C5 [L] Launcher.py.** Percorso cablato `C:\Users\alexg\Documents\maya\scripts\MagiCAM\maya` (non esiste su questa
macchina), cancella `C:/temp/magicam_log.csv`, tutte le cartelle `magicam_stress_*` in %TEMP% e `tmp_extract`,
`tmp_check_repack` relative alla cwd di Maya: un launcher che cancella e' una via di danno (regola 8: cio' che non si disfa
e' dell'utente).

**C6 [L] Documentazione.** README promette cose che il codice non fa (Calibra dal telefono, OSC dal telefono, drone) e
descrive il payload vecchio (`{"matrix", "t"}`); niente LICENSE, versione, CHANGELOG, specifica del protocollo.
`_log` apre e chiude il file CSV a ogni messaggio (60 Hz).

### 2.5 Cosa invece regge

- L'idea e la scelta di ARKit world tracking → UDP → Maya: giusta e semplice.
- `_mat_to_quat`, `_quat_to_mat`, `_quat_slerp`, `AlphaBetaFilter`: corrette per quel che fanno (verificate a lettura;
  roundtrip identita' nel test). Da buttare comunque perche' in v2 la rotazione viaggia come quaternione.
- Lo scheletro SwiftUI (host/porta/Start/Calibra), il `JoystickView`, il `ViewportStreamReceiver` (framing
  lunghezza+payload fatto bene).
- La via di build senza Mac: GitHub Actions su `macos-latest` → `.ipa` non firmata → AltStore da Windows. Da rifare con
  XcodeGen, ma la via e' quella.

---

## 3. Cosa NON e' provato (e va provato prima di costruire)

**3.1 La convenzione di Maya nella simulazione e' emulata, non misurata.** `sim_magicam.py` assume che
`cmds.xform(ws=True, matrix=L)` legga `L` come riga-vettore con la traslazione in 12-14 e che `om.MMatrix(a)*om.MMatrix(b)`
sia il prodotto riga-per-colonna delle liste. E' la convenzione documentata e quella che usa tutto MetaUpgrader, ma per la
regola E1 (il DCC si misura, non si deduce) il PRIMO passo della F1 e' misurarla nel Maya vero su un caso nudo, con la
farm ferma e il si' dell'utente. Se la misura smentisse l'emulazione, F1 e F2 vanno rilette (non e' probabile, ma la
prova va fatta: una simulazione che condivide la presunzione del codice e' lo strumento che non distingue, C1).

**3.2 Nessuna misura dal vivo.** Niente e' stato eseguito in Maya ne' su iPhone. Latenza, jitter, perdita pacchetti,
costo per fotogramma: tutti **[NM]**. I numeri della barra (sotto) si fissano dopo la prima misura, non prima.

**3.3 Il rosso di CI iOS.** Log scaduti. Si ricompila in F2 e si legge.

---

## 4. Verdetto per componente

| Componente | Verdetto | Perche' |
|---|---|---|
| Protocollo JSON + OSC + blob OSC | **butta** | tre formati, nessuna versione, nessun sequence/timestamp usato; il telefono ne usa uno |
| `_arkit_to_maya_matrix` (flip) | **butta** | pezza sopra F1; in v2 non servono riflessioni (entrambi Y-up, destrorsi, camera verso −Z) |
| Calibrazione | **riscrivi** | idea giusta (ancora), implementazione rotta (F2) e senza scala relativa (F3) |
| 5 smoothing + 9 parametri | **butta** | uno solo, One Euro, tarato con una misura |
| Batch averaging nel server loop | **butta** | media di pose = latenza; si tiene l'ULTIMA posa e si filtra |
| Registrazione per pacchetto | **butta** | T1; si registra per timestamp, si cuoce agli fps della scena |
| Modo elicottero | **riscrivi in F5** | idea utile; moto per dt, joystick normalizzato, stato dentro una classe |
| Streaming playblast | **butta** | R6; in F5 cattura del buffer del viewport |
| UI `cmds.*` con 30 widget | **riscrivi** | PySide6, una vista di uno stato, pochi controlli da set |
| Launcher.py | **butta** | C5 |
| Test + conftest finto | **butta** | C2; si rifanno contro risposte note, con il finto Maya che ha la convenzione MISURATA |
| pbxproj a mano, build_ios.sh | **butta** | XcodeGen da `project.yml` |
| Swift: ARSessionManager | **riscrivi** | invio ogni frame, pacchetto binario, stato tracking, intrinseche |
| Swift: ContentView | **riduci** | tieni scheletro e JoystickView; via timer-fake, 940 righe → viste separate |
| Swift: ViewportStreamReceiver | **tieni** | framing corretto; cambia solo il formato del frame se serve |
| README | **riscrivi** | C6 |

---

## 5. Architettura v2

```
MagiCAM/
├── magicam/                      # pacchetto Python, Python puro salvo maya_bridge
│   ├── __init__.py               # __version__, PROTOCOL_VERSION
│   ├── protocol.py               # dataclass Pose/Lens/Command, pack/unpack binario, versione
│   ├── math3d.py                 # quaternioni, matrici 4x4 (convenzione DICHIARATA nel modulo), calib, scala relativa
│   ├── filters.py                # OneEuroFilter (pos, quat), dt dal timestamp del sensore
│   ├── receiver.py               # thread UDP: ultima posa + statistiche (seq perse, latenza, Hz); nessun Maya
│   ├── session.py                # stato della sessione: ancora, scala, freeze, blocchi d'asse, take in corso
│   ├── takes.py                  # registrazione: campioni timestampati → resample agli fps → chiavi; metadati JSON
│   ├── maya_bridge.py            # l'UNICO modulo che importa maya.*: timer main thread, applica posa+lente, cuoce take
│   ├── ui/                       # PySide6: pannello operatore (stato, calibra, freeze, scala, take, rec)
│   └── simulator.py              # telefono finto: traiettorie note (giro 20°, 10 cm, cerchio), perdita pacchetti, tracking limited
├── ios/
│   ├── project.yml               # XcodeGen
│   └── MagiCAM/                  # App, ARSessionManager, PoseEncoder, Views/
├── tests/                        # pytest, Python puro; risposte note e contrasti; finto Maya con convenzione misurata
├── tests_maya/                   # banchi che girano DENTRO Maya (mayapy), lanciati solo a mano col si' dell'utente
├── docs/
│   ├── PROTOCOL.md               # specifica binaria, versione, esempi esadecimali
│   ├── CONVENZIONI.md            # la convenzione di matrice MISURATA in Maya, con il comando che la rilegge
│   ├── MISURE.md                 # latenza, jitter, Hz, costo/frame: data, sha, macchina, come
│   └── PIANO_DI_LAVORO.md        # questo file
├── .github/workflows/            # pytest (ubuntu) · ios-build (macos, XcodeGen + xcodebuild unsigned → .ipa)
├── pyproject.toml                # ruff, mypy, pytest; `pip install -e .`
└── CHANGELOG.md
```

**Flusso dei dati.** iPhone → pacchetto binario (vedi 6) a ogni `ARFrame` (60 Hz) → `receiver.py` tiene l'ultima posa
valida e le statistiche → un `QTimer`/`scriptJob` sul main thread di Maya alla frequenza del viewport legge l'ultima
posa, la porta nel mondo di Maya (`math3d.apply_anchor`: `M_maya = A · S · inv(P_calib) · P_phone` con `A` = ancora
(camera al momento della calibrazione), `S` = scala del moto relativo, tutto in UNA funzione con la convenzione scritta
in testa), la filtra (One Euro con dt dal timestamp del sensore), la applica a camera e lente in un solo `xform` + `setAttr`.
Se `takes.recording`, il campione (timestamp sensore, posa grezza, lente) va in memoria; allo stop si ricampiona agli fps
della scena e si cuociono le chiavi (una per fotogramma, nessun buco).

**Cosa NON fa v2 per scelta.** Nessun thread che chiama `cmds`; nessun `evalDeferred` per pacchetto; nessuna media di
pacchetti; nessuna riflessione d'asse; nessuna preferenza salvata a meta'; nessun `except: pass`.

---

## 6. Protocollo v2 (bozza da fissare in F1, `docs/PROTOCOL.md`)

Un datagramma UDP, little-endian, header comune:

| campo | tipo | note |
|---|---|---|
| magic | `u32` | `'MGC2'` |
| version | `u16` | 2 |
| type | `u16` | 1 pose · 2 command · 3 ack/stats (PC→telefono) |
| seq | `u32` | progressivo per tipo |
| t_sensor | `f64` | `ARFrame.timestamp` (secondi, orologio monotono del telefono) |

`pose` (type 1): `tracking_state u8` (0 normal · 1 limited · 2 notAvailable, + `reason u8`), `pos f32[3]` (metri,
mondo ARKit), `quat f32[4]` (x,y,z,w, mondo ARKit), `focal_px f32`, `image_w u16`, `image_h u16`, `exposure_offset f32`.
Totale 24 + 1+1+12+16+4+2+2+4 = 66 byte (contro ~450 del JSON). Niente matrice: il quaternione non puo' avere taglio
ne' scala (R4 muore qui), e la convenzione di matrice resta tutta in `math3d.py`.

`command` (type 2): `cmd u16` (1 calibrate · 2 recenter · 3 freeze · 4 unfreeze · 5 rec_start · 6 rec_stop ·
7 scale_set + `f32`), con `token u32` di pairing (R5).

`stats` (type 3, PC→telefono, 2 Hz): pacchetti ricevuti/persi, latenza stimata, stato (calibrato / in take / freeze):
il telefono mostra numeri VERI (C3).

Discovery: il PC pubblica `_magicam._udp` via Bonjour/mDNS (`zeroconf` in Python, `NWBrowser` su iOS); l'IP a mano resta
come ripiego.

---

## 7. TO-DO completa

Ogni voce ha: cosa · **Accettazione** (misurabile) · **Prova** (come e contro cosa). Una voce e' «fatta» solo quando la
prova e' stata eseguita e il numero sta in `docs/MISURE.md` con data e sha; altrimenti e' «scritta».

### F0 — Repo e fondamenta (senza Maya, senza iPhone)

- [x] F0.1 Clonare in cartella definitiva (proposta `C:\Users\alexg\Documents\MagiCAM`; decide l'utente).
- [x] F0.2 Tag `legacy-2026-01` su `1c3ad1b` (e `legacy-2026-01-master` su `master`); ramo `v2` da `1c3ad1b`, non da `master`: cosi' `legacy/` tiene i 32 commit del lavoro vero. Mai force. Push dell'utente o
      autorizzato da lui.
- [x] F0.3 Spostare il codice vecchio in `legacy/` (non cancellare: regola 8), con un `legacy/README.md` che rimanda a
      questo documento. **Accettazione**: `git log --follow` conserva la storia.
- [x] F0.4 `pyproject.toml` (ruff, mypy strict su `magicam/`, pytest), `pip install -e .`, pre-commit.
      **Accettazione**: `ruff check . && mypy magicam && pytest` verde su un pacchetto vuoto.
- [ ] F0.5 CI `pytest.yml` (ubuntu, Python 3.10 e 3.11 = Maya 2024/2025) e `ios-build.yml` (macos, XcodeGen). *(scritti; verdi solo dopo il primo push su `v2`, che decide l'utente)*
      **Accettazione**: badge verdi sul ramo `v2` al primo push.
- [x] F0.6 `docs/PROTOCOL.md`, `docs/CONVENZIONI.md` (vuoto, con la lista delle misure da fare), `CHANGELOG.md`,
      LICENSE (decide l'utente), README nuovo con «cosa fa OGGI» separato da «cosa fara'».
- [x] F0.7 Portare questo file in `docs/PIANO_DI_LAVORO.md`.

### F1 — Lato Maya: matematica, ricezione, applicazione (verificabile su Windows col simulatore)

- [ ] F1.1 **Misurare la convenzione di Maya** (3.1): in un Maya nudo, `xform(matrix=L)` con `L` = traslazione (1,2,3) in
      12-14 e rotazione nota (yaw 20°), poi `xform -q -t` e `-q -ro`; e `MMatrix(a)*MMatrix(b)` contro numpy. Scrivere il
      comando e l'esito in `docs/CONVENZIONI.md`. **Prova**: il caso opposto (traslazione in 3,7,11) deve dare un
      risultato DIVERSO e sbagliato (contrasto). **Farm ferma, si' dell'utente, ≥5 GB su C:, ≥6 GB di commit liberi.**
- [x] F1.2 `protocol.py`: pack/unpack con `struct`, versione, rifiuto di magic/versione sbagliati.
      **Prova**: roundtrip su valori limite (NaN rifiutato, quaternione non unitario rifiutato), un byte corrotto → eccezione
      tipizzata, mai `pass`.
- [x] F1.3 `math3d.py`: `quat↔mat` (convenzione dichiarata), `apply_anchor(anchor, scale, p_calib, p_phone)`.
      **Prova contro risposte note**: le 6 righe della tabella di F1 (gira a sinistra → camera a sinistra, ecc.) PIU'
      il caso F2 (ancora a (500,150,0) girata 90°: avanza 10 cm → (490,150,0)) PIU' scala 0.1 attorno all'ancora
      (10 cm reali → 1 cm, ancora ferma). **Killer rosso**: lo stesso test con la convenzione trasposta deve fallire
      (si prova revertendo, mai checkout).
- [x] F1.4 `filters.py`: One Euro per posizione (3 canali) e per quaternione (slerp verso la misura con alpha da *(provato su gradino, rumore e dt irregolare; i default NON sono tarati: F1.9)*
      cutoff), dt dal `t_sensor`. **Prova**: ingresso gradino → tempo di salita dichiarato; ingresso costante +
      rumore gaussiano noto → attenuazione misurata; dt irregolare (pacchetti persi) → nessun salto superiore a X.
      I numeri (mincutoff, beta) si tarano in F1.9, non si inventano.
- [x] F1.5 `receiver.py`: thread UDP non bloccante, tiene l'ultima posa valida per `seq`, scarta seq vecchi, conta
      persi/riordinati, stima latenza (`t_ricezione − t_sensor`, con offset stimato dal minimo su finestra), stato
      tracking. Nessun import di `maya`. **Prova**: simulatore con 5% perdita + 2% riordino → 0 pose vecchie applicate,
      conteggi esatti contro quelli del simulatore.
- [x] F1.6 `simulator.py`: telefono finto da riga di comando: traiettorie note (fermo, yaw 20°, 10 cm destra, avanti,
      cerchio r=0.5 m a 60 Hz), perdita/riordino configurabili, tracking `limited` a comando, `t_sensor` monotono.
      **Prova**: il simulatore e' lo strumento di tutti i test di F1: si prova prima su un caso di cui si sa la risposta
      (C1) — il ricevitore deve riprodurre la traiettoria del cerchio con errore < 1e-6 m a filtro spento.
- [x] F1.7 `session.py`: ancora, scala, freeze (tiene l'ultima posa applicata e al rilascio ri-ancora senza salto),
      recenter, blocchi d'asse (altezza, dolly). **Prova**: freeze → muovi il telefono 1 m → unfreeze: camera ferma,
      e il passo successivo di 10 cm da' 10 cm (contrasto: senza ri-ancoraggio salterebbe di 1 m).
- [ ] F1.8 `maya_bridge.py`: un solo timer sul main thread (frequenza = refresh del viewport, max 60 Hz), legge l'ultima *(scritto 2026-10-15, non eseguito in Maya)*
      posa, applica posa+lente in un `xform` + `setAttr` (focal, filmback da intrinseche), legge `currentUnit` e
      converte i metri. Niente `evalDeferred` per pacchetto. Camera scelta dall'utente, mai `modelPanel` altrui.
      **Prova dentro Maya (F1.1 condizioni)**: simulatore a 60 Hz per 60 s → profondita' coda = 0, nessun frame
      applicato fuori ordine, costo per tick misurato (`cmds.timerX`), scena in cm e in m (contrasto unita').
- [ ] F1.9 **Prima misura dal vivo in Maya col simulatore**: latenza simulatore→camera (timestamp nel pacchetto vs
      `xform -q` sul tick), jitter, Hz effettivi; taratura del One Euro su una traiettoria registrata (si scrive PRIMA
      l'atteso: quanto ritardo si accetta, p.es. ≤ 2 frame a 60 Hz). → `docs/MISURE.md`.
- [ ] F1.10 UI PySide6: stato (ricevo/persi/latenza/tracking), Calibra, Recenter, Freeze, scala, blocchi, camera, *(scritto 2026-10-15, non eseguito in Maya; i pulsanti chiamano Session/Bridge, che hanno i test)*
      Rec. La UI legge uno stato, non scrive globali. **Prova**: ogni pulsante ha un test che chiama la stessa funzione
      della UI e verifica lo stato (il pulsante NON e' il test: la funzione lo e').
- [ ] F1.11 Preferenze: un solo file, un solo scrittore, scrittura atomica (tmp + rename), tutte le chiavi.
      **Prova**: salva/ricarica/compara; file corrotto → default e avviso, non crash.

### F2 — App iOS minima (Mac non necessario)

- [ ] F2.1 `ios/project.yml` (XcodeGen), target iOS 15+, solo i 4-5 file Swift; `ARKitSender.swift` legacy fuori.
- [ ] F2.2 `PoseEncoder.swift`: pacchetto di 6 (`struct` → `Data`, little-endian). **Prova**: test XCTest con vettore
      esadecimale noto condiviso con `tests/test_protocol.py` (lo stesso byte-array in entrambi).
- [ ] F2.3 `ARSessionManager`: invia OGNI frame (niente soglie), `t_sensor = frame.timestamp`, tracking state,
      intrinseche; `worldAlignment = .gravity`; riavvio tracking → comando `recenter` automatico con avviso.
- [ ] F2.4 Riscrivere la vista principale: host/porta (o Bonjour), Start/Stop, Calibra, Freeze, Rec, statistiche VERE
      dal messaggio `stats` del PC (C3 muore). ≤ 300 righe per file.
- [ ] F2.5 CI iOS: XcodeGen + `xcodebuild CODE_SIGNING_ALLOWED=NO` → `.ipa` artifact. **Accettazione**: verde, e il log
      si legge. Installazione via AltStore (Windows) provata dall'utente.
- [ ] F2.6 **Prima misura dal vivo con l'iPhone**: le 6 righe della tabella F1 fatte a mano (telefono su un tavolo, segni
      a 10 cm; giro a vista) → la camera di Maya si muove nel verso e nella misura attesi, con ancora all'origine E con
      ancora a (500,150,0) girata 90°. Latenza telefono→viewport misurata (ripresa video a 240 fps del telefono e dello
      schermo, o LED sincronizzato). → `docs/MISURE.md`.

### F3 — Take

- [ ] F3.1 `takes.py`: Rec start/stop (da UI o dal telefono), campioni in memoria (t_sensor, pos, quat, lente, tracking),
      metadati (nome take, scena, fps, unita', sha app/pacchetto, device, data), salvataggio JSON della take GREZZA
      accanto alla scena (una take non si perde se Maya cade: scrittura atomica).
- [ ] F3.2 Ricampionamento agli fps della scena (interpolazione lineare pos, slerp quat, per tempo), cottura delle chiavi
      su camera e lente, dal fotogramma corrente; `undo` in un solo chunk. **Prova**: 60 Hz per 10 s su scena a 24 fps
      → 240 chiavi esatte, durata 10,00 s (contrasto: il vecchio codice darebbe 600 chiavi = 25 s); con il 10% dei
      pacchetti persi → ancora 240 chiavi, nessun buco; take in cui l'operatore sta fermo 3 s → la camera sta ferma 3 s.
- [ ] F3.3 Lista take, ricuoci su un'altra camera, elimina (sposta in `_cestino/`, regola 8).
- [ ] F3.4 Prova dal vivo: una take di 20 s con l'iPhone, playblast, confronto a occhio col video del telefono (B3).

### F4 — Robustezza e rete

- [ ] F4.1 Pairing con token (mostrato dal PC, inserito o scansionato sul telefono); pacchetti senza token ignorati e
      contati. **Prova**: secondo simulatore senza token → 0 effetto, contatore sale.
- [ ] F4.2 Bonjour/mDNS lato PC (`zeroconf`) e `NWBrowser` lato iOS. **Prova**: telefono trova il PC senza IP.
- [ ] F4.3 Tracking `limited`/`notAvailable`: la camera si congela, l'UI lo dice, al ritorno si ri-ancora senza salto.
      **Prova**: simulatore manda `limited` per 2 s con pose che saltano → camera ferma.
- [ ] F4.4 Wi-Fi che cade: timeout dichiarato (p.es. 0,5 s senza pacchetti → stato «perso», camera ferma).
- [ ] F4.5 Stress misurato: 60 Hz per 10 min dentro Maya, memoria e CPU del processo Maya prima/dopo (H1).

### F5 — Extra, uno alla volta e solo se li vuoi

- [ ] F5.1 Modo drone: moto per dt, joystick normalizzato a ±1 vero, velocita' in unita'/s, dentro `session.py`.
- [ ] F5.2 Monitor di set: cattura del color buffer del viewport (`M3dView.readColorBuffer`) → JPEG in memoria → TCP;
      misura fps e latenza; mai toccare il panel dell'artista.
- [ ] F5.3 Zoom/focale dal telefono (slider o pinch), lente registrata nella take.
- [ ] F5.4 Timecode (LTC via audio o NTP) per sincronizzare con altre riprese del set.
- [ ] F5.5 Supporto Android (ARCore) con lo stesso protocollo.

### F6 — Chiusura

- [ ] F6.1 `docs/MISURE.md` completo: latenza, jitter, Hz, costo/tick, perdita tollerata, con data, sha, macchina.
- [ ] F6.2 Copertura: ogni funzione di `math3d`, `protocol`, `filters`, `takes` ha un test con risposta nota e un
      contrasto; killer rosso documentato per F1.3 e F3.2.
- [ ] F6.3 README e manuale operatore (come si calibra sul set, in 10 righe).
- [ ] F6.4 Release `v2.0.0`: tag, `.ipa` dell'Action, `pip install`.

---

## 8. Regole di lavoro di questo progetto

1. **Prima la prova, poi la frase.** Ogni difetto di questo documento ha la sua etichetta [D]/[L]/[NM]; chi lo chiude
   scrive la misura, non «sistemato».
2. **L'atteso si scrive prima del dato** (tabelle di F1.3, F3.2): chi lo ritocca dopo lo dice.
3. **Un killer si prova rosso revertendo la cura**, mai con checkout/stash/reset.
4. **La farm e il lavoro dell'utente vengono prima**: niente Maya/mayapy senza il suo si'; soglie lette subito prima
   (≥5 GB su C:, ≥6 GB di commit liberi); una misura alla volta.
5. **Push**: li fa l'utente o li autorizza; mai force, nemmeno sui rami. Verde locale sul commit finale prima di chiedere.
6. **Niente cancellazioni definitive dal codice** (take, preferenze, log): si sposta in `_cestino/`.
7. **CHANGELOG** in testa, una voce per commit che cambia comportamento: cosa, perche', cosa misurato, cosa resta aperto.
8. **Un file ≤ 400 righe, una funzione ≤ 40**, mypy strict, ruff; `except Exception` solo con log e rilancio o
   stato d'errore visibile.

---

## 9. Decisioni che restano all'utente

1. Cartella della copia di lavoro (proposta `C:\Users\alexg\Documents\MagiCAM`).
2. Mac disponibile? (no → XcodeGen + Actions + AltStore; si' → anche firma e TestFlight).
3. Versione/i di Maya da supportare (2024 = Py 3.10, 2025 = Py 3.11, 2026?).
4. Priorita' fra: camera dal vivo (F1-F2) · take (F3) · drone (F5.1) · monitor di set (F5.2).
5. Licenza del repo (oggi assente; e' pubblico).
6. Quando posso usare Maya per F1.1/F1.8/F1.9 (farm ferma).
