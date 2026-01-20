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
        // Flatten to row-major array [r0c0, r0c1, ... r3c3]
        var arr: [Float] = []
        for r in 0..<4 {
            for c in 0..<4 {
                let value = mat[c][r] // simd uses columns, so access as [column][row]
                arr.append(value)
            }
        }
        let payload: [String: Any] = ["matrix": arr, "t": Date().timeIntervalSince1970]
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
