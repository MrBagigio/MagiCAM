// Vista operatore: host/porta, Avvia, Calibra, Ricentra, Freeze, Rec, e i numeri VERI che arrivano dal PC.
// Nessun timer che finge di contare fotogrammi.

import ARKit
import MagiCAMCore
import SwiftUI

struct ContentView: View {
    @StateObject private var manager = ARSessionManager()
    @AppStorage("magicam.host") private var host = "192.168.1.100"
    @AppStorage("magicam.port") private var port = 9000
    @State private var frozen = false
    @State private var recording = false

    var body: some View {
        NavigationView {
            Form {
                Section("Collegamento") {
                    TextField("Host (IP del PC con Maya)", text: $host)
                        .keyboardType(.numbersAndPunctuation)
                        .textInputAutocapitalization(.never)
                        .disableAutocorrection(true)
                        .disabled(manager.isRunning)
                    TextField("Porta UDP", value: $port, format: .number)
                        .keyboardType(.numberPad)
                        .disabled(manager.isRunning)
                    Button(manager.isRunning ? "Ferma" : "Avvia") {
                        if manager.isRunning {
                            manager.stop()
                        } else {
                            manager.start(host: host, port: UInt16(clamping: port))
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(manager.isRunning ? .red : .green)
                }

                Section("Camera") {
                    HStack {
                        Button("Calibra") { manager.send(.calibrate) }
                        Spacer()
                        Button("Ricentra") { manager.send(.recenter) }
                        Spacer()
                        Button(frozen ? "Rilascia" : "Freeze") {
                            frozen.toggle()
                            manager.send(frozen ? .freeze : .unfreeze)
                        }
                        .tint(frozen ? .orange : .accentColor)
                    }
                    .buttonStyle(.bordered)
                    .disabled(!manager.isRunning)
                    Button(recording ? "Stop take" : "Rec take") {
                        recording.toggle()
                        manager.send(recording ? .recStart : .recStop)
                    }
                    .buttonStyle(.bordered)
                    .tint(recording ? .red : .accentColor)
                    .disabled(!manager.isRunning)
                }

                Section("Stato") {
                    row("Rete", linkText)
                    row("Tracking ARKit", ARSessionManager.describe(manager.tracking))
                    row("Pacchetti spediti", "\(manager.framesSent)")
                    if let s = manager.stats, manager.statsAge < 3 {
                        row("Ricevuti dal PC", "\(s.received)")
                        row("Persi", "\(s.lost)")
                        row("Latenza (stima PC)", String(format: "%.0f ms", s.latencyMs))
                        row("Maya", mayaText(s.flags))
                    } else {
                        row("Dal PC", manager.isRunning ? "nessuna risposta" : "—")
                    }
                    if let n = manager.notice {
                        Text(n).font(.footnote).foregroundColor(.orange)
                    }
                }
            }
            .navigationTitle("MagiCAM")
        }
        .navigationViewStyle(.stack)
    }

    private var linkText: String {
        switch manager.linkState {
        case .idle: return "fermo"
        case .connecting: return "connessione…"
        case .ready: return "pronto"
        case .failed(let why): return "errore: \(why)"
        }
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

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
