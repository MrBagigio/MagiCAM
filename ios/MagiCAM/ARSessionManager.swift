// ARKit -> pacchetti MagiCAM. OGNI frame viene inviato (nessuna soglia che zittisce il telefono da fermo),
// con il timestamp del sensore, lo stato del tracking e le intrinseche. Le statistiche a video sono SOLO
// quelle che il PC rimanda (StatsMessage): il telefono conta solo quanti pacchetti ha spedito.

import ARKit
import Combine
import Foundation
import MagiCAMCore
import Network

final class ARSessionManager: NSObject, ObservableObject, ARSessionDelegate {
    @Published var isRunning = false
    @Published var linkState: UDPLink.State = .idle
    @Published var framesSent: UInt32 = 0
    @Published var tracking: ARCamera.TrackingState = .notAvailable
    @Published var stats: StatsMessage?
    @Published var statsAge: TimeInterval = .infinity
    @Published var notice: String?

    /// Token di pairing (F4.1). 0 = nessuno; il PC puo' rifiutare i comandi senza token.
    var token: UInt32 = 0

    private let session = ARSession()
    private let link = UDPLink()
    private var poseSeq: UInt32 = 0
    private var commandSeq: UInt32 = 0
    private var lastStatsUptime: TimeInterval = 0
    private var wasRelocalizing = false
    private var uiFrameCounter = 0
    private var framesSinceLastPing = 0

    override init() {
        super.init()
        session.delegate = self
        link.onState = { [weak self] st in
            DispatchQueue.main.async { self?.linkState = st }
        }
        link.onReceive = { [weak self] data in
            self?.handleIncoming(data)
        }
    }

    // MARK: - ciclo di vita

    func start(host: String, port: UInt16) {
        start(connecting: { $0.connect(host: host, port: port) })
    }

    func start(endpoint: NWEndpoint) {
        start(connecting: { $0.connect(to: endpoint) })
    }

    private func start(connecting: (UDPLink) -> Void) {
        poseSeq = 0
        framesSinceLastPing = 0
        connecting(link)
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        session.run(config, options: [.resetTracking, .removeExistingAnchors])
        isRunning = true
        notice = nil
        send(.ping) // primo abbinamento subito, prima delle pose
    }

    func stop() {
        session.pause()
        link.disconnect()
        isRunning = false
    }

    // MARK: - comandi

    func send(_ command: CommandCode, value: Float = 0) {
        commandSeq &+= 1
        let m = CommandMessage(
            seq: commandSeq,
            tSensor: ProcessInfo.processInfo.systemUptime,
            command: command,
            token: token,
            value: value
        )
        link.send(PoseEncoder.encode(m))
    }

    // MARK: - ARSessionDelegate

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        let camera = frame.camera
        let (state, reason) = Self.code(for: camera.trackingState)
        let t = camera.transform
        let position = SIMD3<Float>(t.columns.3.x, t.columns.3.y, t.columns.3.z)
        let q = simd_quatf(t) // rotazione della 4x4 (nessuna scala in ARKit), (ix, iy, iz, r) = (x, y, z, w)
        let resolution = camera.imageResolution
        let message = PoseMessage(
            seq: poseSeq,
            tSensor: frame.timestamp,
            trackingState: state,
            trackingReason: reason,
            position: position,
            quaternion: q.vector,
            focalPx: camera.intrinsics.columns.0.x,
            imageWidth: UInt16(clamping: Int(resolution.width)),
            imageHeight: UInt16(clamping: Int(resolution.height)),
            exposureOffset: camera.exposureOffset
        )
        poseSeq &+= 1
        link.send(PoseEncoder.encode(message))

        // PING col codice ogni secondo: e' cosi' che il PC abbina questo telefono (F4.1) e tiene vivo l'abbinamento
        framesSinceLastPing += 1
        if framesSinceLastPing >= 60 {
            framesSinceLastPing = 0
            send(.ping)
        }

        uiFrameCounter += 1
        if uiFrameCounter % 15 == 0 { // 4 Hz di aggiornamento della UI: non il flusso dei pacchetti
            let sent = poseSeq
            let age = ProcessInfo.processInfo.systemUptime - lastStatsUptime
            DispatchQueue.main.async {
                self.framesSent = sent
                self.statsAge = age
            }
        }
    }

    func session(_ session: ARSession, cameraDidChangeTrackingState camera: ARCamera) {
        let st = camera.trackingState
        DispatchQueue.main.async { self.tracking = st }
        switch st {
        case .limited(.relocalizing):
            wasRelocalizing = true
        case .normal:
            if wasRelocalizing {
                // Il mondo ARKit puo' essersi spostato: ricentra, cosi' la camera di Maya non salta.
                wasRelocalizing = false
                send(.recenter)
                DispatchQueue.main.async { self.notice = "Tracking ripreso: camera ricentrata" }
            }
        default:
            break
        }
    }

    func session(_ session: ARSession, didFailWithError error: Error) {
        DispatchQueue.main.async {
            self.notice = "ARKit: \(error.localizedDescription)"
            self.isRunning = false
        }
    }

    func sessionWasInterrupted(_ session: ARSession) {
        DispatchQueue.main.async { self.notice = "Sessione AR interrotta" }
    }

    func sessionInterruptionEnded(_ session: ARSession) {
        wasRelocalizing = true // al ritorno il tracking rilocalizza: trattato come sopra
        DispatchQueue.main.async { self.notice = "Sessione AR ripresa" }
    }

    func sessionShouldAttemptRelocalization(_ session: ARSession) -> Bool {
        true
    }

    // MARK: - dal PC

    private func handleIncoming(_ data: Data) {
        guard let s = try? PoseEncoder.decodeStats(data) else { return }
        lastStatsUptime = ProcessInfo.processInfo.systemUptime
        DispatchQueue.main.async {
            self.stats = s
            self.statsAge = 0
        }
    }

    // MARK: - mappe

    static func code(for state: ARCamera.TrackingState) -> (TrackingStateCode, TrackingReasonCode) {
        switch state {
        case .normal:
            return (.normal, .none)
        case .notAvailable:
            return (.notAvailable, .none)
        case .limited(let reason):
            switch reason {
            case .initializing: return (.limited, .initializing)
            case .relocalizing: return (.limited, .relocalizing)
            case .excessiveMotion: return (.limited, .excessiveMotion)
            case .insufficientFeatures: return (.limited, .insufficientFeatures)
            @unknown default: return (.limited, .none)
            }
        }
    }

    static func describe(_ state: ARCamera.TrackingState) -> String {
        switch state {
        case .normal: return "normale"
        case .notAvailable: return "non disponibile"
        case .limited(.initializing): return "limitato: inizializzazione"
        case .limited(.relocalizing): return "limitato: rilocalizzazione"
        case .limited(.excessiveMotion): return "limitato: movimento eccessivo"
        case .limited(.insufficientFeatures): return "limitato: pochi riferimenti"
        case .limited: return "limitato"
        }
    }
}
