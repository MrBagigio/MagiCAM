import Foundation
import ARKit
import Network

class ARSessionManager: NSObject, ObservableObject, ARSessionDelegate {
    private var session: ARSession = ARSession()
    private var connection: NWConnection?
    @Published var connected: Bool = false
    @Published var helicopterMode: Bool = false
    var host: String = "192.168.1.100"
    var port: UInt16 = 9000

    // Throttling and change detection
    private var lastSend: TimeInterval = 0
    private let minInterval: TimeInterval = 1.0 / 60.0 // 60 Hz for smoother tracking
    private let transThreshold: Float = 0.001 // 1mm - more sensitive
    private let rotThreshold: Float = 0.001 // more sensitive rotation detection
    private var lastPos: SIMD3<Float>? = nil
    private var lastQuat: simd_quatf? = nil
    
    // Joystick state for helicopter mode
    private var joystickTimer: Timer?
    private let joystickInterval: TimeInterval = 1.0 / 30.0 // 30 Hz for joystick
    
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
        // ARKit simd_float4x4 is COLUMN-major: columns.0 is the first column (X-axis vector)
        // Maya expects ROW-major: [row0, row1, row2, row3] where each row is [x,y,z,w]
        // 
        // Column-major (ARKit):        Row-major (Maya):
        // | c0.x c1.x c2.x c3.x |      | m[0]  m[1]  m[2]  m[3]  |   <- row 0
        // | c0.y c1.y c2.y c3.y |  =>  | m[4]  m[5]  m[6]  m[7]  |   <- row 1
        // | c0.z c1.z c2.z c3.z |      | m[8]  m[9]  m[10] m[11] |   <- row 2
        // | c0.w c1.w c2.w c3.w |      | m[12] m[13] m[14] m[15] |   <- row 3
        //
        // So row-major[i] = reading left-to-right, top-to-bottom from the column-major matrix
        let c0 = mat.columns.0
        let c1 = mat.columns.1
        let c2 = mat.columns.2
        let c3 = mat.columns.3
        
        // Scale translation from meters to Maya units
        let tx = c3.x * translationScale
        let ty = c3.y * translationScale
        let tz = c3.z * translationScale
        
        // Row-major: flatten the matrix reading row by row
        // Row 0: first row of the matrix = [c0.x, c1.x, c2.x, tx]
        // Row 1: second row = [c0.y, c1.y, c2.y, ty]
        // Row 2: third row = [c0.z, c1.z, c2.z, tz]
        // Row 3: [0, 0, 0, 1]
        let arr: [Float] = [
            c0.x, c1.x, c2.x, tx,   // Row 0
            c0.y, c1.y, c2.y, ty,   // Row 1
            c0.z, c1.z, c2.z, tz,   // Row 2
            0.0,  0.0,  0.0,  1.0   // Row 3
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
    
    // MARK: - Helicopter Mode
    
    func enableHelicopterMode() {
        helicopterMode = true
        // Pause ARKit tracking when in helicopter mode
        session.pause()
        // Send command to Maya
        let payload: [String: Any] = ["type": "cmd", "cmd": "heli_on"]
        sendPayload(payload)
    }
    
    func disableHelicopterMode() {
        helicopterMode = false
        // Resume ARKit tracking
        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity
        session.run(config)
        // Send command to Maya
        let payload: [String: Any] = ["type": "cmd", "cmd": "heli_off"]
        sendPayload(payload)
    }
    
    func sendJoystickInput(leftX: Float, leftY: Float, rightX: Float, rightY: Float, throttle: Float, roll: Float = 0) {
        guard helicopterMode else { return }
        
        let payload: [String: Any] = [
            "type": "joystick",
            "lx": leftX,    // strafe left/right
            "ly": leftY,    // forward/back
            "rx": rightX,   // yaw (turn)
            "ry": rightY,   // pitch (look up/down)
            "throttle": throttle, // 0.5 = hover
            "roll": roll
        ]
        sendPayload(payload)
    }
}
