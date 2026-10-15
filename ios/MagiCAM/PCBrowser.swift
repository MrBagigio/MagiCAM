// Cerca i PC che annunciano `_magicam._udp` (Bonjour). L'endpoint `.service` va dato cosi' com'e' a NWConnection:
// la risoluzione dell'IP la fa Network.framework. Serve NSBonjourServices nell'Info.plist (ios/project.yml).

import Combine
import Foundation
import Network

struct FoundPC: Identifiable, Equatable {
    let name: String
    let endpoint: NWEndpoint
    var id: String { name }

    static func == (lhs: FoundPC, rhs: FoundPC) -> Bool {
        lhs.name == rhs.name
    }
}

final class PCBrowser: ObservableObject {
    @Published var found: [FoundPC] = []
    @Published var selected: String?
    @Published var status = "cerco PC MagiCAM sulla rete…"

    private var browser: NWBrowser?

    var selectedService: FoundPC? {
        guard let name = selected else { return nil }
        return found.first { $0.name == name }
    }

    func start() {
        guard browser == nil else { return }
        let params = NWParameters.udp
        params.includePeerToPeer = true
        let b = NWBrowser(for: .bonjour(type: "_magicam._udp", domain: nil), using: params)
        b.stateUpdateHandler = { [weak self] state in
            DispatchQueue.main.async {
                switch state {
                case .ready:
                    self?.status = "nessun PC MagiCAM trovato (scrivi l'IP)"
                case .failed(let err):
                    self?.status = "Bonjour: \(err.localizedDescription)"
                case .waiting(let err):
                    self?.status = "Bonjour in attesa: \(err.localizedDescription)"
                default:
                    break
                }
            }
        }
        b.browseResultsChangedHandler = { [weak self] results, _ in
            let pcs: [FoundPC] = results.compactMap { r in
                if case .service(let name, _, _, _) = r.endpoint {
                    return FoundPC(name: name, endpoint: r.endpoint)
                }
                return nil
            }
            .sorted { $0.name < $1.name }
            DispatchQueue.main.async {
                self?.found = pcs
                if let sel = self?.selected, !pcs.contains(where: { $0.name == sel }) {
                    self?.selected = nil
                }
                if pcs.count == 1, self?.selected == nil {
                    self?.selected = pcs[0].name
                }
            }
        }
        browser = b
        b.start(queue: .main)
    }

    func stop() {
        browser?.cancel()
        browser = nil
    }
}
