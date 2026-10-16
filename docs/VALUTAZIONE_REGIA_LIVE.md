# Valutazione per la regia dal vivo — 2026-10-16

Domanda dell'utente: MagiCAM funziona, ma va valutata per bene perche' serve a fare **regia dal vivo**
(l'operatore muove l'iPhone, il regista guarda e registra le take in Maya, anche sopra un'animazione che scorre).

Metodo: riletto tutto il percorso di una ripresa (ricevitore, sessione, filtro, ponte con Maya, take, pannello, app
iOS) e dimostrato in Maya 2026 i rischi che toccano una ripresa, con il simulatore a 60 Hz su una camera di prova
(`mgc_bench_cam`, porta 9101, poi cancellata). Codice al commit `76eb98a`. Ogni voce dice se e' **misurata** o
**letta nel codice** (in quel caso: da misurare prima di curarla).

## Cosa regge gia' (misurato, docs/MISURE.md)

- Rete di casa: 0 pose perse su 630 in 20 s dall'iPhone; abbinamento col codice.
- Costo in Maya: tick ≤ 2 ms; le pose dal vivo non riempiono la coda di undo.
- Calibra, Freeze/Rilascia, scala e ripresa del tracking senza salto (simulatore, posa per posa).
- Bake in blocco: 14354 chiavi in 0,17 s, annullabile se le curve sono nuove.

## Bloccanti per la regia (misurati il 2026-10-16)

1. **La take non e' agganciata alla timeline.** Rec al fotogramma 1, testina portata a 100 durante la take, Stop:
   le chiavi vanno da **100 a 167**. Il bake parte da dove sta la testina allo Stop, e il tempo della take e' quello
   del telefono, senza legame con i fotogrammi che il regista stava guardando. Registrare sopra un'animazione
   che scorre oggi non e' possibile.
2. **Dopo una take la camera «combatte» il dal vivo.** La camera ha le curve della take: avanzando di un solo
   fotogramma la camera salta di **32,9 cm** dalla posa dal vivo alla posa della curva. In playback il telefono
   non comanda piu'.
3. **La seconda take si mescola alla prima.** Seconda take da 25 chiavi (1-25) sulla stessa camera: la curva ha
   **93 chiavi da 1 a 167**, cioe' la coda della prima take (100-167) resta. Su curve gia' esistenti, in piu', le
   chiavi aggiunte non si annullano con undo (scritto nel codice e nel log).
4. **Camera cancellata o scena nuova a collegamento attivo: nessuno lo dice.** Dopo `delete` della camera:
   **59 errori in 1 s** (uno per tick) nel log, pose ancora contate come ricevute, stato della sessione «ok».
   Il pannello mostrerebbe «dal vivo».

## Alti (letti nel codice, da misurare)

5. **L'iPhone va in blocco schermo durante la ripresa.** L'app non disattiva il blocco automatico
   (`isIdleTimerDisabled` non compare nel codice). Senza toccare lo schermo, allo scadere del blocco automatico
   l'app va in sottofondo e ARKit si ferma.
6. **L'obiettivo lo decide il telefono.** Con `drive_lens=True` (predefinito, nessun comando nel pannello) ogni
   tick riscrive la focale della camera dalla focale di ARKit: il regista non puo' scegliere l'obiettivo in Maya.
   Il sensore e' 4:3 (1920×1440), il dorso della camera di Maya di solito no.
7. **Chiudere il pannello durante una take la perde.** La chiusura ferma il ponte; i campioni restano in memoria
   e il pannello nuovo crea un registratore vuoto.
8. **Errori della take avviata dal telefono restano nel log.** Se salvataggio o bake falliscono dopo uno Stop dal
   telefono, l'operatore non lo vede; il registratore e' gia' fermo.
9. **Abbinamento fragile sulle raffiche.** L'abbinamento dura 3 s e il telefono manda un PING al secondo: una
   raffica che perde 3 PING (il 2026-10-16 se ne sono perse 78 pose in 10 s) scarta le pose come «non abbinate»
   anche se arrivano.

## Medi

10. **30 Hz invece di 60** — corretto nell'app (commit `95e4773`), non ancora provato sul telefono.
11. **Latenza telefono → vista non misurata**: serve un riferimento comune (es. lo schermo del telefono e il monitor
    di Maya filmati insieme da una terza camera ad alta frequenza).
12. **Nessun mirino sul telefono**: l'operatore guarda il monitor di Maya. Per la regia serve almeno lo stato grande
    (Rec, collegamento) sul telefono, poi l'immagine della vista.
13. **Bonjour spento in Maya** (manca zeroconf nel Python di Maya): IP a mano; il pannello ora lo mostra.

## Proposta di lavoro, in ordine

| # | cosa | chiude |
|---|---|---|
| R1 | **Take agganciata alla timeline**: Rec fa partire il playback da un punto d'ingresso (con pre-roll), ogni posa registra il fotogramma di Maya, il bake usa quei fotogrammi | 1 |
| R2 | **Camera dal vivo separata dalle camere delle take**: il telefono muove sempre `magicam_live`; ogni take si cuoce su una camera nuova (`take_001_cam`, …) o su un layer, mai sulla camera dal vivo | 2, 3 |
| R3 | **Tick che si accorge**: camera sparita, scena nuova o aperta → ponte fermo, spia rossa, take salvata | 4, 7, 8 |
| R4 | **iPhone da ripresa**: blocco schermo spento mentre trasmette, Rec e collegamento grandi sul telefono, avviso di surriscaldamento | 5, 12 |
| R5 | **Obiettivo**: scelta «dal telefono / da Maya» nel pannello, predefinito da Maya; zoom dal telefono dopo | 6 |
| R6 | **Abbinamento tollerante**: un mittente abbinato resta tale finche' non cambia indirizzo o codice | 9 |
| R7 | **Misure sul telefono**: fps del formato nuovo, latenza con riferimento comune, rumore da fermo per il filtro | 10, 11 |

R1, R2 e R3 insieme sono il minimo per una sessione di regia vera.

## Stato

- **R1, R2, R3 fatti il 2026-10-16** e rimisurati con lo stesso banco: chiavi sui fotogrammi visti (0-74), testina
  spostata a mano → a tempo dal Rec, camera dal vivo senza curve (0,0 cm), camera con chiavi rifiutata, camera
  cancellata → 1 errore invece di 59 al secondo (docs/MISURE.md, CHANGELOG). Resta da provare la scena nuova in una
  scena vuota e tutto col telefono vero sopra un'animazione.
- R4-R7 da fare.
