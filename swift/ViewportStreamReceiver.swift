import Foundation
import Network
import UIKit

/// Receives JPEG frames from Maya viewport streaming over TCP
class ViewportStreamReceiver: NSObject, ObservableObject {
    @Published var isConnected: Bool = false
    @Published var currentFrame: UIImage? = nil
    @Published var fps: Int = 0
    
    private var connection: NWConnection?
    private var host: String = ""
    private var port: UInt16 = 9001
    
    private var receiveBuffer = Data()
    private var expectedLength: UInt32 = 0
    private var isReadingHeader = true
    
    private var frameCount: Int = 0
    private var lastFpsUpdate: TimeInterval = 0
    
    func start(host: String, port: UInt16) {
        self.host = host
        self.port = port
        
        let nwHost = NWEndpoint.Host(host)
        guard let nwPort = NWEndpoint.Port(rawValue: port) else {
            print("[ViewportStream] Invalid port")
            return
        }
        
        connection = NWConnection(host: nwHost, port: nwPort, using: .tcp)
        
        connection?.stateUpdateHandler = { [weak self] state in
            switch state {
            case .ready:
                print("[ViewportStream] Connected to \(host):\(port)")
                DispatchQueue.main.async {
                    self?.isConnected = true
                }
                self?.receiveData()
            case .failed(let error):
                print("[ViewportStream] Connection failed: \(error)")
                DispatchQueue.main.async {
                    self?.isConnected = false
                }
            case .cancelled:
                print("[ViewportStream] Connection cancelled")
                DispatchQueue.main.async {
                    self?.isConnected = false
                }
            default:
                break
            }
        }
        
        connection?.start(queue: .global(qos: .userInteractive))
    }
    
    func stop() {
        connection?.cancel()
        connection = nil
        receiveBuffer.removeAll()
        expectedLength = 0
        isReadingHeader = true
        frameCount = 0
        
        DispatchQueue.main.async { [weak self] in
            self?.isConnected = false
            self?.currentFrame = nil
            self?.fps = 0
        }
    }
    
    private func receiveData() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            
            if let error = error {
                print("[ViewportStream] Receive error: \(error)")
                self.stop()
                return
            }
            
            if let data = data, !data.isEmpty {
                self.processData(data)
            }
            
            if isComplete {
                self.stop()
                return
            }
            
            // Continue receiving
            self.receiveData()
        }
    }
    
    private func processData(_ data: Data) {
        receiveBuffer.append(data)
        
        while true {
            if isReadingHeader {
                // Need at least 4 bytes for the length header
                if receiveBuffer.count >= 4 {
                    // Read big-endian UInt32 length
                    let lengthData = receiveBuffer.prefix(4)
                    expectedLength = lengthData.withUnsafeBytes { $0.load(as: UInt32.self).bigEndian }
                    receiveBuffer.removeFirst(4)
                    isReadingHeader = false
                } else {
                    break
                }
            } else {
                // Reading frame data
                if receiveBuffer.count >= Int(expectedLength) {
                    let frameData = receiveBuffer.prefix(Int(expectedLength))
                    receiveBuffer.removeFirst(Int(expectedLength))
                    isReadingHeader = true
                    
                    // Decode JPEG
                    if let image = UIImage(data: frameData) {
                        DispatchQueue.main.async { [weak self] in
                            self?.currentFrame = image
                        }
                        
                        // Update FPS counter
                        frameCount += 1
                        let now = Date().timeIntervalSince1970
                        if now - lastFpsUpdate >= 1.0 {
                            DispatchQueue.main.async { [weak self] in
                                self?.fps = self?.frameCount ?? 0
                            }
                            frameCount = 0
                            lastFpsUpdate = now
                        }
                    }
                } else {
                    break
                }
            }
        }
    }
}
