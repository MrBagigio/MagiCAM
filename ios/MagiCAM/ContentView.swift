// Vista operatore: host/porta/codice, Avvia, Calibra, Ricentra, Freeze, Rec, scala del moto, e i numeri VERI che
// arrivano dal PC. Freeze e Rec a video seguono i FLAG del PC quando le stats sono fresche: un interruttore locale che
// dice «freeze» mentre Maya non lo e' sarebbe un canale che mente (il v1 contava i frame con un timer).

import ARKit
import MagiCAMCore
import SwiftUI

struct ContentView: View {
    @StateObject private var manager = ARSessionManager()
    @AppStorage("magicam.host") private var host = "192.168.1.100"
    @AppStorage("magicam.port") private var port = 9000
    @AppStorage("magicam.token") private var tokenText = ""
    @AppStorage("magicam.scale") private var scale = 1.0
    @StateObject private var browser = PCBrowser()
    // ultimo stato CHIESTO dal telefono: vale solo finche' il PC non risponde con i suoi flag
    @State private var frozenRequested = false
    @State private var recordingRequested = false

    private let haptic = UIImpactFeedbackGenerator(style: .medium)

    var body: some View {
        NavigationView {
            Form {
                connectionSection
                cameraSection
                statusSection
            }
            .navigationTitle("MagiCAM")
        }
        .navigationViewStyle(.stack)
        .onAppear { browser.start() }
        .onDisappear { browser.stop() }
    }

    // MARK: - sezioni

    private var connectionSection: some View {
        Section("Collegamento") {
            TextField("Host (IP del PC con Maya)", text: $host)
                .keyboardType(.numbersAndPunctuation)
                .textInputAutocapitalization(.never)
                .disableAutocorrection(true)
                .disabled(manager.isRunning)
            TextField("Porta UDP", value: $port, format: .number)
                .keyboardType(.numberPad)
                .disabled(manager.isRunning)
            TextField("Codice sul pannello MagiCAM (vuoto = nessuno)", text: $tokenText)
                .keyboardType(.numberPad)
                .disabled(manager.isRunning)
            if !browser.found.isEmpty {
                Picker("PC trovati (Bonjour)", selection: $browser.selected) {
                    Text("— IP a mano —").tag(Optional<String>.none)
                    ForEach(browser.found, id: \.name) { pc in
                        Text(pc.name).tag(Optional(pc.name))
                    }
                }
                .disabled(manager.isRunning)
            } else {
                Text(browser.status).font(.footnote).foregroundColor(.secondary)
            }
            Button(manager.isRunning ? "Ferma" : "Avvia") {
                haptic.impactOccurred()
                if manager.isRunning {
                    manager.stop()
                } else {
                    manager.token = UInt32(tokenText.trimmingCharacters(in: .whitespaces)) ?? 0
                    frozenRequested = false
                    recordingRequested = false
                    if let pc = browser.selectedService {
                        manager.start(endpoint: pc.endpoint)
                    } else {
                        manager.start(host: host, port: UInt16(clamping: port))
                    }
                }
            }
            .buttonStyle(.borderedProminent)
            .tint(manager.isRunning ? .red : .green)
        }
    }

    private var cameraSection: some View {
        Section("Camera") {
            HStack {
                Button("Calibra") { command(.calibrate) }
                Spacer()
                Button("Ricentra") { command(.recenter) }
                Spacer()
                Button(frozen ? "Rilascia" : "Freeze") {
                    frozenRequested = !frozen
                    command(frozenRequested ? .freeze : .unfreeze)
                }
                .tint(frozen ? .orange : .accentColor)
            }
            .buttonStyle(.bordered)
            .disabled(!manager.isRunning)

            Button(recording ? "Stop take" : "Rec take") {
                recordingRequested = !recording
                command(recordingRequested ? .recStart : .recStop)
            }
            .buttonStyle(.bordered)
            .tint(recording ? .red : .accentColor)
            .disabled(!manager.isRunning)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text("Scala del moto")
                    Spacer()
                    Text(scaleLabel).font(.system(.body, design: .monospaced)).foregroundColor(.secondary)
                }
                // 0,1x (miniatura) … 10x (gru): scala logaritmica; il PC ri-ancora senza salto a ogni cambio
                Slider(value: $scale.logarithmic, in: log10(0.1)...log10(10.0), step: 0.05) { editing in
                    if !editing {
                        command(.scaleSet, value: Float(scale))
                    }
                }
                .disabled(!manager.isRunning)
            }
        }
    }

    private var statusSection: some View {
        Section("Stato") {
            row("Rete", linkText)
            row("Tracking ARKit", ARSessionManager.describe(manager.tracking))
            row("Formato video", manager.videoFormat)
            if !manager.videoFormatsAvailable.isEmpty {
                Text("Disponibili: \(manager.videoFormatsAvailable)").font(.footnote).foregroundColor(.secondary)
            }
            row("Pacchetti spediti", "\(manager.framesSent)")
            if let s = freshStats {
                row("Ricevuti dal PC", "\(s.received)")
                row("Persi", "\(s.lost)")
                row("Latenza (stima PC)", String(format: "%.0f ms", s.latencyMs))
                row("Maya", mayaText(s.flags))
            } else {
                row("Dal PC", manager.isRunning ? "nessuna risposta (freeze/rec a video = richiesti, non confermati)" : "—")
            }
            if let n = manager.notice {
                Text(n).font(.footnote).foregroundColor(.orange)
            }
        }
    }

    // MARK: - stato derivato

    /// Le stats del PC valgono per 3 s: dopo, il PC e' «muto» e si mostra solo cio' che il telefono ha chiesto.
    private var freshStats: StatsMessage? {
        guard let s = manager.stats, manager.statsAge < 3 else { return nil }
        return s
    }

    private var frozen: Bool {
        freshStats?.flags.contains(.frozen) ?? frozenRequested
    }

    private var recording: Bool {
        freshStats?.flags.contains(.recording) ?? recordingRequested
    }

    private var scaleLabel: String {
        scale >= 1 ? String(format: "%.1fx", scale) : String(format: "1:%.0f", 1.0 / scale)
    }

    private var linkText: String {
        switch manager.linkState {
        case .idle: return "fermo"
        case .connecting: return "connessione…"
        case .ready: return "pronto"
        case .failed(let why): return "errore: \(why)"
        }
    }

    private func command(_ c: CommandCode, value: Float = 0) {
        haptic.impactOccurred()
        manager.send(c, value: value)
    }

    private func mayaText(_ f: StatsFlags) -> String {
        var parts: [String] = []
        parts.append(f.contains(.calibrated) ? "calibrata" : "NON calibrata")
        if f.contains(.frozen) { parts.append("freeze") }
        if f.contains(.recording) { parts.append("in take") }
        if f.contains(.trackingBad) { parts.append("tracking fermo") }
        return parts.joined(separator: " · ")
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack {
            Text(label)
            Spacer()
            Text(value).foregroundColor(.secondary).font(.system(.body, design: .monospaced))
        }
    }
}

private extension Binding where Value == Double {
    /// Slider in log10: il valore salvato resta lineare (la scala vera), il cursore si muove in decadi.
    var logarithmic: Binding<Double> {
        Binding<Double>(
            get: { log10(Swift.max(self.wrappedValue, 1e-6)) },  // `max` nudo = membro dinamico del Binding
            set: { self.wrappedValue = pow(10.0, $0) }
        )
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
