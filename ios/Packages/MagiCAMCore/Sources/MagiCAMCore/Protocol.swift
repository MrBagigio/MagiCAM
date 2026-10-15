// Protocollo MagiCAM v2 (docs/PROTOCOL.md): tipi dei messaggi. Little-endian, 62/30/33 byte.
// Deve riprodurre BYTE PER BYTE i vettori di tests/test_protocol.py (VETTORI_NOTI): li prova
// Tests/MagiCAMCoreTests/PoseEncoderTests.swift.

import Foundation

public enum MagiCAMProtocol {
    public static let magic: [UInt8] = Array("MGC2".utf8)
    public static let version: UInt16 = 2
    public static let headerSize = 20
    public static let poseSize = 62
    public static let commandSize = 30
    public static let statsSize = 33
}

public enum MessageType: UInt16 {
    case pose = 1
    case command = 2
    case stats = 3
}

public enum TrackingStateCode: UInt8 {
    case normal = 0
    case limited = 1
    case notAvailable = 2
}

public enum TrackingReasonCode: UInt8 {
    case none = 0
    case initializing = 1
    case relocalizing = 2
    case excessiveMotion = 3
    case insufficientFeatures = 4
}

public enum CommandCode: UInt16 {
    case calibrate = 1
    case recenter = 2
    case freeze = 3
    case unfreeze = 4
    case recStart = 5
    case recStop = 6
    case scaleSet = 7
    case ping = 8
}

public struct StatsFlags: OptionSet, Equatable {
    public let rawValue: UInt8
    public init(rawValue: UInt8) { self.rawValue = rawValue }
    public static let calibrated = StatsFlags(rawValue: 1)
    public static let frozen = StatsFlags(rawValue: 2)
    public static let recording = StatsFlags(rawValue: 4)
    public static let trackingBad = StatsFlags(rawValue: 8)
}

/// Posa del telefono nel mondo ARKit: metri, quaternione (x, y, z, w) unitario.
public struct PoseMessage: Equatable {
    public var seq: UInt32
    public var tSensor: Double
    public var trackingState: TrackingStateCode
    public var trackingReason: TrackingReasonCode
    public var position: SIMD3<Float>
    public var quaternion: SIMD4<Float>
    public var focalPx: Float
    public var imageWidth: UInt16
    public var imageHeight: UInt16
    public var exposureOffset: Float

    public init(
        seq: UInt32,
        tSensor: Double,
        trackingState: TrackingStateCode,
        trackingReason: TrackingReasonCode,
        position: SIMD3<Float>,
        quaternion: SIMD4<Float>,
        focalPx: Float = 0,
        imageWidth: UInt16 = 0,
        imageHeight: UInt16 = 0,
        exposureOffset: Float = 0
    ) {
        self.seq = seq
        self.tSensor = tSensor
        self.trackingState = trackingState
        self.trackingReason = trackingReason
        self.position = position
        self.quaternion = quaternion
        self.focalPx = focalPx
        self.imageWidth = imageWidth
        self.imageHeight = imageHeight
        self.exposureOffset = exposureOffset
    }
}

public struct CommandMessage: Equatable {
    public var seq: UInt32
    public var tSensor: Double
    public var command: CommandCode
    public var token: UInt32
    public var value: Float

    public init(seq: UInt32, tSensor: Double, command: CommandCode, token: UInt32 = 0, value: Float = 0) {
        self.seq = seq
        self.tSensor = tSensor
        self.command = command
        self.token = token
        self.value = value
    }
}

/// Dal PC al telefono (2 Hz): gli UNICI numeri che l'app mostra come statistiche.
public struct StatsMessage: Equatable {
    public var seq: UInt32
    public var tSensor: Double
    public var received: UInt32
    public var lost: UInt32
    public var latencyMs: Float
    public var flags: StatsFlags

    public init(seq: UInt32, tSensor: Double, received: UInt32, lost: UInt32, latencyMs: Float, flags: StatsFlags) {
        self.seq = seq
        self.tSensor = tSensor
        self.received = received
        self.lost = lost
        self.latencyMs = latencyMs
        self.flags = flags
    }
}

public enum ProtocolError: Error, Equatable {
    case badLength(expected: Int, got: Int)
    case badMagic
    case badVersion(UInt16)
    case badType(UInt16)
}
