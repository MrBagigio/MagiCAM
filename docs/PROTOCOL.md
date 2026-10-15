# Protocollo MagiCAM v2 (UDP, binario, little-endian)

Versione del protocollo: **2**. Un datagramma = un messaggio. Il codice di riferimento e' `magicam/protocol.py`;
l'encoder Swift e' `ios/Packages/MagiCAMCore` (`PoseEncoder.swift`) e riproduce byte per byte i tre vettori di
`tests/test_protocol.py` (`VETTORI_NOTI`: pose, command, stats) in `PoseEncoderTests.swift`. Chi cambia un campo
cambia i vettori in TUTTI E DUE i test, nello stesso commit.

## Header (20 byte, comune)

| offset | campo | tipo | valore |
|---|---|---|---|
| 0 | magic | 4 byte | `b"MGC2"` |
| 4 | version | u16 | 2 |
| 6 | type | u16 | 1 pose · 2 command · 3 stats |
| 8 | seq | u32 | progressivo per tipo e per mittente; riparte da 0 a ogni avvio |
| 12 | t_sensor | f64 | secondi, orologio monotono del mittente (`ARFrame.timestamp` per le pose) |

## 1 — pose (telefono → PC), corpo 42 byte, totale 62

| offset | campo | tipo | note |
|---|---|---|---|
| 20 | tracking_state | u8 | 0 normal · 1 limited · 2 notAvailable |
| 21 | tracking_reason | u8 | 0 none · 1 initializing · 2 relocalizing · 3 excessiveMotion · 4 insufficientFeatures |
| 22 | pos | 3 × f32 | metri, mondo ARKit (`.gravity`) |
| 34 | quat | 4 × f32 | x, y, z, w, unitario |
| 50 | focal_px | f32 | `intrinsics[0][0]`; 0 se ignota |
| 54 | image_w | u16 | `imageResolution.width`; 0 se ignota |
| 56 | image_h | u16 | |
| 58 | exposure_offset | f32 | EV, informativo |

Il ricevitore **rifiuta** (eccezione tipizzata, conteggiata): magic o versione diversi, lunghezza diversa, NaN/inf,
quaternione con norma fuori da [0.99, 1.01]. Non c'e' matrice: un quaternione non puo' portare taglio ne' scala.

## Pairing (F4.1)

Le pose NON portano il token (62 byte restano 62). Il PC mostra un codice a 6 cifre; il telefono lo manda nel
campo `token` di ogni comando e di un `ping` al secondo. Il PC «abbina» l'indirizzo (IP, porta) del mittente per
`PAIR_TTL_S` = 3 s dall'ultimo comando col token giusto; le pose di un mittente non abbinato si scartano e si
contano (`unpaired`), un comando col token sbagliato si conta in `rejected`. Con il codice spento sul pannello
(`expected_token = None`) chiunque sulla LAN muove la camera, come nel v1.

## 2 — command (telefono → PC, o PC → telefono), corpo 10 byte, totale 30

| offset | campo | tipo | note |
|---|---|---|---|
| 20 | cmd | u16 | 1 calibrate · 2 recenter · 3 freeze · 4 unfreeze · 5 rec_start · 6 rec_stop · 7 scale_set · 8 ping |
| 22 | token | u32 | pairing (F4.1); 0 = nessuno |
| 26 | value | f32 | argomento (per `scale_set` la scala) |

## 3 — stats (PC → telefono, 2 Hz), corpo 13 byte, totale 33

| offset | campo | tipo | note |
|---|---|---|---|
| 20 | received | u32 | pose ricevute dall'avvio |
| 24 | lost | u32 | buchi di `seq` |
| 28 | latency_ms | f32 | stima (vedi `receiver.py`) |
| 32 | flags | u8 | bit0 calibrato · bit1 freeze · bit2 in take · bit3 tracking non normale |

Il telefono mostra SOLO questi numeri: niente contatori locali che somigliano a statistiche.

## Perche' non JSON, non OSC

Il v1 aveva tre formati (JSON, OSC float, OSC blob) senza versione; il telefono ne usava uno; `t` era mandato e mai
letto; nessun `seq`, nessuno stato del tracking. 62 byte contro ~450, parse in `struct.unpack` senza allocazioni
intermedie, e ogni campo con un significato misurabile.
