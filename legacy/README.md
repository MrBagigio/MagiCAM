# legacy — MagiCAM v1 (gennaio 2026)

Qui sta, intatto e con la sua storia (`git log --follow legacy/maya/maya_receiver.py`), il codice del POC del
20-21/01/2026: ramo `feature/stress-ci-and-receiver-tuning`, tag `legacy-2026-01`. Non si usa e non si mantiene.

Perche' e' stato messo da parte, con le prove: `docs/PIANO_DI_LAVORO.md`, sezione 2. In breve: la matrice
viaggiava in una convenzione e Maya la leggeva in un'altra (il moto del telefono arrivava invertito sulla camera),
la calibrazione perdeva la posizione della camera fuori dall'origine, dal telefono passava solo la posa (calibra e
drone non arrivavano mai a Maya), la registrazione legava il tempo alla rete.

Cosa e' stato ripreso in v2: l'idea, la via di build senza Mac (Actions -> .ipa non firmata -> AltStore), lo
scheletro SwiftUI, il `JoystickView`, il framing del `ViewportStreamReceiver`.
