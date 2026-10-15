// Minimal ARKit sender (Swift 5, iOS 13+)
// Replace HOST_IP and PORT before running

import UIKit
import ARKit
import Network

class ViewController: UIViewController, ARSessionDelegate {
    var session = ARSession()
    var connection: NWConnection?
    let HOST = "192.168.1.100" // <- replace with your PC IP
    let PORT: UInt16 = 9000

    override func viewDidLoad() {
        super.viewDidLoad()
        session = ARSession()
        session.delegate = self
        startConnection()

        let config = ARWorldTrackingConfiguration()
        config.worldAlignment = .gravity // or .gravityAndHeading
        session.run(config)
    }

    func startConnection() {
        let host = NWEndpoint.Host(HOST)
        let port = NWEndpoint.Port(rawValue: PORT) ?? .init(integerLiteral: 9000)
        connection = NWConnection(host: host, port: port, using: .udp)
        connection?.start(queue: .global())
    }

    func session(_ session: ARSession, didUpdate frame: ARFrame) {
        // Get camera transform (simd_float4x4)
        let mat = frame.camera.transform
        
        // Build row-major 4x4 matrix for Maya
        // Translation at positions [3, 7, 11], scaled to cm (ARKit uses meters)
        let c0 = mat.columns.0
        let c1 = mat.columns.1
        let c2 = mat.columns.2
        let c3 = mat.columns.3
        let scale: Float = 100.0 // meters to cm
        
        let arr: [Float] = [
            c0.x, c1.x, c2.x, c3.x * scale,
            c0.y, c1.y, c2.y, c3.y * scale,
            c0.z, c1.z, c2.z, c3.z * scale,
            0.0,  0.0,  0.0,  1.0
        ]
        
        let payload: [String: Any] = ["type": "pose", "matrix": arr, "t": Date().timeIntervalSince1970]
        do {
            let data = try JSONSerialization.data(withJSONObject: payload, options: [])
            connection?.send(content: data, completion: .contentProcessed({ _ in }))
        } catch {
            print("JSON error: \(error)")
        }
    }

    deinit {
        connection?.cancel()
        session.pause()
    }
}
