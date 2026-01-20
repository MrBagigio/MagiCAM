import Foundation
import ARKit
import Network

class ARSessionManager: NSObject, ObservableObject, ARSessionDelegate {
    private var session: ARSession = ARSession()
    private var connection: NWConnection?
    @Published var connected: Bool = false
    var host: String = "192.168.1.100"
    var port: UInt16 = 9000

    // Throttling and change detection
    private var lastSend: TimeInterval = 0
    private let minInterval: TimeInterval = 1.0 / 30.0 // 30 Hz
    private let transThreshold: Float = 0.01 // meters
    private let rotThreshold: Float = 0.01 // approx radians
    private var lastPos: SIMD3<Float>? = nil
    private var lastQuat: simd_quatf? = nil

    func start(host: String, port: UInt16) {
        self.host = host
        self.port = port
        let nwHost = NWEndpoint.Host(host)
        let nwPort = NWEndpoint.Port(rawValue: port) ?? .init(integerLiteral: 9000)
        connection = NWConnection(host: nwHost, port: nwPort, using: .udp)
        connection?.start(queue: .global())
        session.delegate = self
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        session.run(config)
        connected = true
    }

    func stop() {
        session.pause()
        connection?.cancel()
        connected = false
    }

    func sendPayload(_ dict: [String: Any]) {
        do {
            let data = try JSONSerialization.data(withJSONObject: dict, options: [])
            connection?.send(content: data, completion: .contentProcessed({ _ in }))
        } catch {
            print("JSON error: \(error)")
        }
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Throttle sending and only send on significant change
        let now = Date().timeIntervalSince1970
        if now - lastSend < minInterval { return }

        let mat = frame.camera.transform
        // extract translation and rotation quaternion
        let col3 = mat.columns.3
        let pos = SIMD3<Float>(col3.x, col3.y, col3.z)
        let rot = simd_quaternion(mat)

        var send = false
        if let lp = lastPos {
            let d = simd_length(pos - lp)
            if d > transThreshold { send = true }
        } else {
            send = true
        }
        if let lq = lastQuat {
            let dq = abs(simd_dot(rot.vector, lq.vector))
            // if rotation changed more than threshold (approx) send
            if dq < (1 - rotThreshold) { send = true }
        } else {
            send = true
        }

        if !send { return }
        lastPos = pos
        lastQuat = rot
        lastSend = now

        var arr: [Float] = []
        for r in 0..<4 {
            for c in 0..<4 {
                let value = mat[c][r]
                arr.append(value)
            }
        }
        let payload: [String: Any] = ["type":"pose", "matrix": arr, "t": now]
        sendPayload(payload)
    }

    func sendCalibrationOnce() {
        if let currentFrame = session.currentFrame {
            let mat = currentFrame.camera.transform
            var arr: [Float] = []
            for r in 0..<4 {
                for c in 0..<4 {
                    let value = mat[c][r]
                    arr.append(value)
                }
            }
            let payload: [String: Any] = ["type":"calib", "matrix": arr, "t": Date().timeIntervalSince1970]
            sendPayload(payload)
        }
    }
}
