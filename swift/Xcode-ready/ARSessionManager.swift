// Copy of ARSessionManager for Xcode-ready project
import Foundation
import ARKit
import Network

class ARSessionManager: NSObject, ObservableObject, ARSessionDelegate {
    private var session: ARSession = ARSession()
    private var connection: NWConnection?
    @Published var connected: Bool = false
    var host: String = "192.168.1.100"
    var port: UInt16 = 9000

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
        // send pose messages regularly
        let mat = frame.camera.transform
        var arr: [Float] = []
        for r in 0..<4 {
            for c in 0..<4 {
                let value = mat[c][r]
                arr.append(value)
            }
        }
        let payload: [String: Any] = ["type":"pose", "matrix": arr, "t": Date().timeIntervalSince1970]
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
