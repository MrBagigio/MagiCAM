# MagiCAM — ARKit → Maya 6DoF POC 🚀

Breve: questo POC mostra come inviare il transform 6DoF da un iPhone (ARKit) via UDP a Maya 2024+ (Python 3.x) e applicarlo a una camera in tempo reale, con calibrazione e smoothing.

Prerequisiti ✅
- iPhone con iOS che supporti ARKit
- Xcode per compilare l'app Swift (o usare questo codice come riferimento per Unity/ARFoundation)
- PC/Mac con Maya 2024+ (Python 3)
- Tutti i device sulla stessa rete Wi‑Fi
- Porte UDP (es. 9000) aperte tra iPhone e macchina con Maya

File inclusi:
- `swift/ARKitSender.swift` — esempio minimale (legacy). Use `swift/ARKitSenderApp.swift` + `swift/ContentView.swift` for the SwiftUI app that sends JSON via UDP (messages with `type`: 'pose' or 'calib').
- `maya/maya_receiver.py` — script Python da eseguire in Maya: avvia server UDP, applica trasformazioni, smoothing e calibrazione (supporta messaggi `type: 'pose'`, `type: 'calib'` e comandi `type: 'cmd'`).
- `tools/test_sender.py` — script Python per simulare l'iPhone (invia test transform)

Calibration workflow:
1. In Maya, position your camera to the desired target and run `maya_receiver.calibrate()` (this saves the desired camera pose).
2. On the iPhone app, position the phone in the reference pose and press **Calibrate**; the phone sends a `type:'calib'` message with its current pose and the receiver computes the calibration matrix so that `CALIB * incoming = desired_camera`.
3. Now live `pose` messages from the phone will map to the calibrated camera in Maya.

Quickstart (test senza iPhone) ▶️
1. Apri Maya e assicurati di avere una camera che vuoi pilotare (default: `camera1`, o specifica il nome).
2. In Maya, apri `Script Editor` e sorgi (`import maya_receiver` se metti il file in `Maya/scripts`) o esegui direttamente il contenuto di `maya/maya_receiver.py`.
3. Chiama `start_server(port=9000, camera='camera1')`.
4. Sul tuo PC, esegui `python tools/test_sender.py --host <MAYA_IP> --port 9000` per vedere la camera muoversi.

Swift / Info utili 💡
- Richiede `Privacy - Camera Usage Description` in Info.plist
- L'app invia il transform in JSON: `{"matrix": [16 floats], "t": timestamp}` in ROW‑MAJOR (riga per riga)
- Sostituisci `HOST_IP` e `PORT` con l'IP della macchina che esegue Maya

Calibrazione e mapping
- ARKit usa metri; mappa a unità Maya come preferisci (default: 1m -> 1 unità)
- Potrebbe essere necessario correggere rotazioni (es. flip assi) in base alla scena: fornisco funzioni di calibrazione per catturare l'offset iniziale

Limitazioni
- ARKit drift: per sessioni lunghe prevedi reset / rilocalizzazione
- Se serve bassa latenza o pacchetti più piccoli, è facile convertire il payload in binario invece che JSON

Xcode & OSC notes:
- Ho preparato file SwiftUI pronti (`swift/ARKitSenderApp.swift`, `swift/ContentView.swift`, `swift/ARSessionManager.swift`). Per comodità ho aggiunto anche una piccola cartella `swift/Xcode-ready` con `Info.plist` e istruzioni rapide su come creare un progetto Xcode e copiare i file.
- Ho aggiunto una semplice interfaccia dentro Maya: esegui `maya_receiver.show_ui()` per aprire una finestra che ti permette di Start/Stop, Calibrare, Resettare la calibrazione, abilitare il logging e configurare i parametri di smoothing (Mode: `matrix_exp` | `matrix_interp` | `none`, Alpha, Target FPS). Usa `matrix_interp` per ottenere un aggiornamento controllato al framerate target; il receiver applica inoltre un passo di ortonormalizzazione alla porzione di rotazione per ridurre il drift causato dall'interpolazione sulle matrici.
- **OSC support (opzionale)**: `maya_receiver.py` supporta `use_osc=True` se `python-osc` è installato nella Python runtime di Maya. Ora supportiamo anche **OSC binary blobs** (`/pose_bin`, `/calib_bin`) con payload di 16 float32 big-endian per minore latenza e minore overhead.

  Installazione python-osc (se necessario):
  - Apri la Python di Maya o usa il pip della stessa versione: `python -m pip install python-osc`

  Avvio server con OSC: `maya_receiver.start_server(port=9000, camera='camera1', use_osc=True)`.

- **Test OSC binary sender**: `tools/osc_binary_sender.py` invia messaggi `/pose_bin` o `/calib_bin` come blob (richiede `python-osc`).

- **Logging**: è possibile abilitare il logging dei messaggi con `maya_receiver.enable_logging('C:/temp/magicam_log.csv')` e disabilitarlo con `maya_receiver.disable_logging()`.

- **Maya UI & Shelf**: esegui `maya_receiver.show_ui()` per aprire la finestra con Start/Stop, Calibrazione, Reset, opzioni smoothing (incluso "kalman" che è una semplice alpha‑beta predictive filter), toggle OSC/log, e un pulsante per creare una shelf button che apre la UI.

Vuoi che crei lo zip del progetto Xcode pronto per aprire in Xcode (con Info.plist, privacy strings e README)? Ho aggiunto `tools/make_xcode_zip.py` che crea `swift/MagiCAM_Xcode.zip` pronto per essere distribuito: `python tools/make_xcode_zip.py`.

---

Opzione B — Build su GitHub Actions + installazione con AltStore (Windows)

Ho aggiunto un workflow GitHub Actions (`.github/workflows/build_ios.yml`) che compila il progetto su `macos-latest` e pubblica **un .ipa unsigned** come artifact (chiave: `Magicam-unsigned-ipa`). Nota importante: il workflow assume che esista un Xcode project chiamato `MagiCAM.xcodeproj` con scheme `MagiCAM` nella radice del repo. Segui questi passi per usare la pipeline:

1. Crea un repo su GitHub (se non ne hai uno) e fai push di questa cartella/progetto (includi la cartella `swift/` nel repo). Assicurati di aggiungere un Xcode project `MagiCAM.xcodeproj` con la target app `MagiCAM` (puoi creare il project su un Mac o chiedermi istruzioni per generarlo).

2. Vai su Actions → seleziona il workflow `Build unsigned iOS IPA` e esegui manualmente o fai push su `main`.

3. Quando il job finisce, scarica l'artifact **Magicam-unsigned-ipa** dalla pagina del workflow.

4. Installazione su iPhone usando AltStore (Windows):
   - Scarica e installa AltServer per Windows: https://altstore.io
   - Avvia AltServer e collega il tuo iPhone via cavo (o usa Wi‑Fi install) e assicurati che iPhone sia visibile in AltServer.
   - Apri il file `Magicam.ipa` scaricato e usa AltServer/AltStore per sideloadarlo sul tuo iPhone (AltServer userà il tuo Apple ID per firmare temporaneamente l'app). Per istruzioni dettagliate vedi la guida in basso.

5. Avvia l'app sul telefono, inserisci Host = IP del tuo PC Windows, Port = 9000 e premi Start.

---

Se vuoi, posso:
- Creare un template Xcode project base (`MagiCAM.xcodeproj`) con i file Swift già collegati per permetterti di pushare tutto e far partire la Action automaticamente.
- Preparare il workflow per firmare automaticamente se decidi poi di usare un Apple Developer account (opzione A).

Dimmi se vuoi che generi il `MagiCAM.xcodeproj` template e lo aggiunga al repo (spero che tu sappia che per creare un vero .xcodeproj funzionante è meglio farlo su Mac; io posso generare i file di progetto minimali ma potresti dover verificare/aggiustare su Mac).

---
© MagiCAM POC — pronto per test veloci ✨
