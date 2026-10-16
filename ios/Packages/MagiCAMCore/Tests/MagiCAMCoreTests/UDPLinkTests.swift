// Il saluto (PING) a .ready, provato su un socket UDP vero in loopback. Il difetto misurato dal vivo il 2026-10-16:
// 31 pose al PC «non abbinate» all'avvio, perche' il PING partiva subito dopo `connect`, a link non pronto, e
// `send` lo scartava. Il CONTRASTO riproduce quel modo (PING subito, niente greeting) nello stesso banco e pretende
// che le pose arrivino senza PING davanti: se anche il contrasto fosse verde, il banco non distinguerebbe i due casi.

import Foundation
import Network
import XCTest
@testable import MagiCAMCore

/// Ricevitore UDP in loopback: un elenco di datagrammi per ogni mittente (ogni `connect` del link e' una porta nuova).
private final class Receiver {
    let listener: NWListener
    private let queue = DispatchQueue(label: "test.receiver")
    private let lock = NSLock()
    private var byPeer: [[Data]] = []
    private var conns: [NWConnection] = []

    init() throws {
        let params = NWParameters.udp
        params.requiredInterfaceType = .loopback
        listener = try NWListener(using: params, on: .any)
    }

    func start() -> UInt16 {
        let ready = DispatchSemaphore(value: 0)
        listener.stateUpdateHandler = { st in
            if case .ready = st { ready.signal() }
        }
        listener.newConnectionHandler = { [weak self] conn in
            guard let self = self else { return }
            self.lock.lock()
            let idx = self.byPeer.count
            self.byPeer.append([])
            self.conns.append(conn)
            self.lock.unlock()
            conn.start(queue: self.queue)
            self.receive(conn, idx)
        }
        listener.start(queue: queue)
        XCTAssertEqual(ready.wait(timeout: .now() + 5), .success, "il ricevitore in loopback non e' partito")
        return listener.port!.rawValue
    }

    private func receive(_ conn: NWConnection, _ idx: Int) {
        conn.receiveMessage { [weak self] data, _, _, error in
            guard let self = self else { return }
            if let d = data, !d.isEmpty {
                self.lock.lock()
                self.byPeer[idx].append(d)
                self.lock.unlock()
            }
            if error == nil { self.receive(conn, idx) }
        }
    }

    var peers: [[Data]] {
        lock.lock()
        defer { lock.unlock() }
        return byPeer
    }

    func stop() {
        lock.lock()
        conns.forEach { $0.cancel() }
        lock.unlock()
        listener.cancel()
    }
}

final class UDPLinkTests: XCTestCase {
    private static func command(_ c: CommandCode, seq: UInt32) -> Data {
        PoseEncoder.encode(CommandMessage(seq: seq, tSensor: 1, command: c, token: 491_514, value: 0))
    }

    private static func pose(_ seq: UInt32) -> Data {
        PoseEncoder.encode(PoseMessage(
            seq: seq, tSensor: Double(seq) / 60, trackingState: .normal, trackingReason: .none,
            position: SIMD3<Float>(0, 0, 0), quaternion: SIMD4<Float>(0, 0, 0, 1),
            focalPx: 1500, imageWidth: 1920, imageHeight: 1440, exposureOffset: 0
        ))
    }

    private static func isPing(_ d: Data) -> Bool {
        d.count == MagiCAMProtocol.commandSize && d == command(.ping, seq: 1)
    }

    /// Spedisce pose come ARKit (una ogni ~2 ms) da PRIMA che il link sia pronto, finche' il ricevitore ne ha `want`.
    private func streamPoses(_ link: UDPLink, _ rx: Receiver, peer: Int, want: Int) {
        var seq: UInt32 = 0
        let deadline = Date().addingTimeInterval(5)
        while Date() < deadline {
            link.send(Self.pose(seq))
            seq &+= 1
            let peers = rx.peers
            if peers.count > peer, peers[peer].count >= want { return }
            usleep(2000)
        }
        XCTFail("il ricevitore non ha avuto \(want) datagrammi in 5 s")
    }

    func testGreetingIsTheFirstDatagramOfEveryReadyConnection() throws {
        let rx = try Receiver()
        let port = rx.start()
        defer { rx.stop() }
        let link = UDPLink()
        link.greeting = { Self.command(.ping, seq: 1) }

        link.connect(host: "127.0.0.1", port: port)
        streamPoses(link, rx, peer: 0, want: 20)
        // seconda connessione (Riavvia, o .waiting -> .ready): il saluto deve ripartire
        link.connect(host: "127.0.0.1", port: port)
        streamPoses(link, rx, peer: 1, want: 20)
        link.disconnect()

        for (i, got) in rx.peers.enumerated() {
            XCTAssertTrue(Self.isPing(got[0]), "connessione \(i): il primo datagramma non e' il PING")
            XCTAssertEqual(got.filter(Self.isPing).count, 1, "connessione \(i): un solo PING atteso")
            XCTAssertTrue(got.dropFirst().allSatisfy { $0.count == MagiCAMProtocol.poseSize })
        }
        XCTAssertEqual(rx.peers.count, 2)
    }

    /// Il modo di prima (PING subito dopo `connect`, nessun greeting): il PING e' scartato e le pose arrivano sole.
    func testContrastPingRightAfterConnectIsDropped() throws {
        let rx = try Receiver()
        let port = rx.start()
        defer { rx.stop() }
        let link = UDPLink()

        link.connect(host: "127.0.0.1", port: port)
        XCTAssertFalse(link.send(Self.command(.ping, seq: 1)), "a link non pronto il send deve scartare")
        streamPoses(link, rx, peer: 0, want: 20)
        link.disconnect()

        let got = rx.peers[0]
        XCTAssertFalse(Self.isPing(got[0]))
        XCTAssertEqual(got.filter(Self.isPing).count, 0, "il PING spedito prima di .ready non deve arrivare")
    }
}

final class VideoFormatPickerTests: XCTestCase {
    private func c(_ fps: Int, _ w: Int, _ h: Int) -> VideoFormatCandidate {
        VideoFormatCandidate(framesPerSecond: fps, width: w, height: h)
    }

    func testHighestFpsWinsOverResolutionAndOrder() {
        // in testa un 30 fps a risoluzione piena: il primo dell'elenco (e il piu' grande) NON e' la scelta
        let list = [c(30, 1920, 1440), c(60, 1280, 720), c(60, 1920, 1080), c(30, 3840, 2160)]
        XCTAssertEqual(VideoFormatPicker.bestIndex(list), 2)
        XCTAssertEqual(list[2].label, "60 fps · 1920×1080")
    }

    func testTieKeepsFirstAndEmptyKeepsDefault() {
        XCTAssertEqual(VideoFormatPicker.bestIndex([c(60, 1920, 1080), c(60, 1080, 1920)]), 0) // stessi pixel
        XCTAssertEqual(VideoFormatPicker.bestIndex([c(60, 1280, 720), c(60, 1920, 1080)]), 1) // piu' pixel
        XCTAssertEqual(VideoFormatPicker.bestIndex([c(30, 1920, 1440)]), 0)
        XCTAssertNil(VideoFormatPicker.bestIndex([]))
    }
}
