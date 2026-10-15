// Collegamento UDP col PC (Network.framework). Manda datagrammi e riceve le stats che il PC rimanda allo
// stesso mittente. Tutto su una coda propria; chi vuole la UI aggiorna sul main thread.

import Foundation
import Network

final class UDPLink {
    enum State: Equatable {
        case idle
        case connecting
        case ready
        case failed(String)
    }

    private let queue = DispatchQueue(label: "com.setpointstudio.magicam.udp", qos: .userInteractive)
    private var connection: NWConnection?
    private(set) var state: State = .idle

    var onReceive: ((Data) -> Void)?
    var onState: ((State) -> Void)?

    func connect(host: String, port: UInt16) {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            setState(.failed("porta non valida"))
            return
        }
        connect(to: .hostPort(host: NWEndpoint.Host(host), port: nwPort))
    }

    /// Anche un endpoint Bonjour (`.service`): Network.framework lo risolve da solo.
    func connect(to endpoint: NWEndpoint) {
        disconnect()
        let conn = NWConnection(to: endpoint, using: .udp)
        conn.stateUpdateHandler = { [weak self] st in
            guard let self = self else { return }
            switch st {
            case .setup, .preparing:
                self.setState(.connecting)
            case .ready:
                self.setState(.ready)
                self.receiveLoop()
            case .waiting(let err), .failed(let err):
                self.setState(.failed(err.localizedDescription))
            case .cancelled:
                self.setState(.idle)
            @unknown default:
                break
            }
        }
        connection = conn
        setState(.connecting)
        conn.start(queue: queue)
    }

    func disconnect() {
        connection?.cancel()
        connection = nil
        setState(.idle)
    }

    func send(_ data: Data) {
        guard let conn = connection, state == .ready else { return }
        conn.send(content: data, completion: .contentProcessed { _ in })
    }

    private func receiveLoop() {
        connection?.receiveMessage { [weak self] data, _, _, error in
            guard let self = self else { return }
            if let data = data, !data.isEmpty {
                self.onReceive?(data)
            }
            if error == nil, self.connection != nil {
                self.receiveLoop()
            }
        }
    }

    private func setState(_ s: State) {
        state = s
        onState?(s)
    }
}
