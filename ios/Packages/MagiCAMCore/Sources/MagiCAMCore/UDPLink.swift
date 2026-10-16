// Collegamento UDP col PC (Network.framework). Manda datagrammi e riceve le stats che il PC rimanda allo
// stesso mittente. Tutto su una coda propria; chi vuole la UI aggiorna sul main thread.
// Sta in MagiCAMCore (non nell'app) perche' l'ordine «saluto prima delle pose» si prova con `swift test`
// su un socket in loopback: Network.framework c'e' anche su macOS.

import Foundation
import Network

public final class UDPLink {
    public enum State: Equatable {
        case idle
        case connecting
        case ready
        case failed(String)
    }

    private let queue = DispatchQueue(label: "com.setpointstudio.magicam.udp", qos: .userInteractive)
    // `state` lo scrive la coda della connessione e lo legge chi spedisce (il delegate di ARKit): sotto lock,
    // e sotto lo STESSO lock il saluto a .ready e ogni send, cosi' nessuna posa entra in coda prima del saluto.
    private let lock = NSLock()
    private var connection: NWConnection?
    private var _state: State = .idle

    public var state: State {
        lock.lock()
        defer { lock.unlock() }
        return _state
    }

    public var onReceive: ((Data) -> Void)?
    public var onState: ((State) -> Void)?
    /// Il primo datagramma di ogni connessione pronta (il PING col codice, F4.1). Mandato a OGNI passaggio a
    /// .ready (anche dopo un .waiting), prima di qualunque altro: prima di .ready `send` scarta, quindi un PING
    /// spedito subito dopo `connect` andava perso e le pose arrivavano al PC «non abbinate» (31 il 2026-10-16).
    public var greeting: (() -> Data)?

    public init() {}

    public func connect(host: String, port: UInt16) {
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            setState(.failed("porta non valida"))
            return
        }
        connect(to: .hostPort(host: NWEndpoint.Host(host), port: nwPort))
    }

    /// Anche un endpoint Bonjour (`.service`): Network.framework lo risolve da solo.
    public func connect(to endpoint: NWEndpoint) {
        disconnect()
        let conn = NWConnection(to: endpoint, using: .udp)
        conn.stateUpdateHandler = { [weak self, weak conn] st in
            guard let self = self, let conn = conn else { return }
            switch st {
            case .setup, .preparing:
                self.setState(.connecting)
            case .ready:
                self.becomeReady(conn)
                self.receiveLoop()
            case .waiting(let err), .failed(let err):
                self.setState(.failed(err.localizedDescription))
            case .cancelled:
                self.setState(.idle)
            @unknown default:
                break
            }
        }
        lock.lock()
        connection = conn
        lock.unlock()
        setState(.connecting)
        conn.start(queue: queue)
    }

    public func disconnect() {
        lock.lock()
        let conn = connection
        connection = nil
        lock.unlock()
        conn?.cancel()
        setState(.idle)
    }

    /// Spedisce solo a connessione pronta e DOPO il saluto; prima scarta (e restituisce false).
    @discardableResult
    public func send(_ data: Data) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard let conn = connection, _state == .ready else { return false }
        conn.send(content: data, completion: .contentProcessed { _ in })
        return true
    }

    private func becomeReady(_ conn: NWConnection) {
        lock.lock()
        guard conn === connection else { // una connessione gia' sostituita da un connect successivo
            lock.unlock()
            return
        }
        if let hello = greeting?() {
            conn.send(content: hello, completion: .contentProcessed { _ in })
        }
        _state = .ready
        lock.unlock()
        onState?(.ready)
    }

    private func receiveLoop() {
        lock.lock()
        let conn = connection
        lock.unlock()
        conn?.receiveMessage { [weak self] data, _, _, error in
            guard let self = self else { return }
            if let data = data, !data.isEmpty {
                self.onReceive?(data)
            }
            if error == nil, self.state == .ready {
                self.receiveLoop()
            }
        }
    }

    private func setState(_ s: State) {
        lock.lock()
        _state = s
        lock.unlock()
        onState?(s)
    }
}
