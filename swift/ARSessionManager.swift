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
    private let minInterval: TimeInterval = 1.0 / 60.0 // 60 Hz for smoother tracking
    private let transThreshold: Float = 0.001 // 1mm - more sensitive
    private let rotThreshold: Float = 0.001 // more sensitive rotation detection
    private var lastPos: SIMD3<Float>? = nil
    private var lastQuat: simd_quatf? = nil
    
    // Scale factor: ARKit uses meters, Maya default is cm (multiply by 100)
    // Set to 1.0 if Maya scene is in meters, 100.0 if in centimeters
    var translationScale: Float = 100.0

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

        // Build row-major 4x4 matrix for Maya
        // ARKit simd_float4x4 is column-major, we need row-major
        // Row-major format: [r0c0,r0c1,r0c2,r0c3, r1c0,r1c1,r1c2,r1c3, ...]
        // Translation goes in positions [3, 7, 11] (last element of each row except last row)
        let c0 = mat.columns.0
        let c1 = mat.columns.1
        let c2 = mat.columns.2
        let c3 = mat.columns.3
        
        // Scale translation from meters to Maya units
        let tx = c3.x * translationScale
        let ty = c3.y * translationScale
        let tz = c3.z * translationScale
        
        // Row-major: each row is [Xx, Xy, Xz, Tx] etc
        // But Maya expects: [r0c0, r0c1, r0c2, r0c3, r1c0, ...]
        // Which for a standard transform is:
        // [Xx, Yx, Zx, Tx,  Xy, Yy, Zy, Ty,  Xz, Yz, Zz, Tz,  0, 0, 0, 1]
        let arr: [Float] = [
            c0.x, c1.x, c2.x, tx,   // Row 0: X-axis + tx
            c0.y, c1.y, c2.y, ty,   // Row 1: Y-axis + ty  
            c0.z, c1.z, c2.z, tz,   // Row 2: Z-axis + tz
            0.0,  0.0,  0.0,  1.0   // Row 3: homogeneous
        ]
        
        let payload: [String: Any] = ["type":"pose", "matrix": arr, "t": now]
        sendPayload(payload)
    }

    func sendCalibrationOnce() {
        if let currentFrame = session.currentFrame {
            let mat = currentFrame.camera.transform
            let c0 = mat.columns.0
            let c1 = mat.columns.1
            let c2 = mat.columns.2
            let c3 = mat.columns.3
            
            let tx = c3.x * translationScale
            let ty = c3.y * translationScale
            let tz = c3.z * translationScale
            
            let arr: [Float] = [
                c0.x, c1.x, c2.x, tx,
                c0.y, c1.y, c2.y, ty,
                c0.z, c1.z, c2.z, tz,
                0.0,  0.0,  0.0,  1.0
            ]
            let payload: [String: Any] = ["type":"calib", "matrix": arr, "t": Date().timeIntervalSince1970]
            sendPayload(payload)
        }
    }
}
