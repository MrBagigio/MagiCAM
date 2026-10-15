// Pack/unpack dei datagrammi, little-endian esplicito (mai `withUnsafeBytes` della struct: il padding
// cambierebbe la lunghezza). Ogni intero si scrive byte per byte: nessuna dipendenza dall'allineamento.

import Foundation

public enum PoseEncoder {
    // MARK: - encode

    public static func encode(_ m: PoseMessage) -> Data {
        var w = ByteWriter(capacity: MagiCAMProtocol.poseSize)
        w.header(type: .pose, seq: m.seq, tSensor: m.tSensor)
        w.u8(m.trackingState.rawValue)
        w.u8(m.trackingReason.rawValue)
        w.f32(m.position.x)
        w.f32(m.position.y)
        w.f32(m.position.z)
        w.f32(m.quaternion.x)
        w.f32(m.quaternion.y)
        w.f32(m.quaternion.z)
        w.f32(m.quaternion.w)
        w.f32(m.focalPx)
        w.u16(m.imageWidth)
        w.u16(m.imageHeight)
        w.f32(m.exposureOffset)
        return w.data
    }

    public static func encode(_ m: CommandMessage) -> Data {
        var w = ByteWriter(capacity: MagiCAMProtocol.commandSize)
        w.header(type: .command, seq: m.seq, tSensor: m.tSensor)
        w.u16(m.command.rawValue)
        w.u32(m.token)
        w.f32(m.value)
        return w.data
    }

    public static func encode(_ m: StatsMessage) -> Data {
        var w = ByteWriter(capacity: MagiCAMProtocol.statsSize)
        w.header(type: .stats, seq: m.seq, tSensor: m.tSensor)
        w.u32(m.received)
        w.u32(m.lost)
        w.f32(m.latencyMs)
        w.u8(m.flags.rawValue)
        return w.data
    }

    // MARK: - decode (solo cio' che il telefono riceve: stats)

    public static func decodeStats(_ data: Data) throws -> StatsMessage {
        guard data.count == MagiCAMProtocol.statsSize else {
            throw ProtocolError.badLength(expected: MagiCAMProtocol.statsSize, got: data.count)
        }
        var r = ByteReader(data)
        let (type, seq, tSensor) = try r.header()
        guard type == .stats else { throw ProtocolError.badType(type.rawValue) }
        let received = r.u32()
        let lost = r.u32()
        let latency = r.f32()
        let flags = StatsFlags(rawValue: r.u8())
        return StatsMessage(seq: seq, tSensor: tSensor, received: received, lost: lost, latencyMs: latency, flags: flags)
    }
}

// MARK: - byte helpers

struct ByteWriter {
    private(set) var data: Data

    init(capacity: Int) {
        data = Data(capacity: capacity)
    }

    mutating func header(type: MessageType, seq: UInt32, tSensor: Double) {
        data.append(contentsOf: MagiCAMProtocol.magic)
        u16(MagiCAMProtocol.version)
        u16(type.rawValue)
        u32(seq)
        f64(tSensor)
    }

    mutating func u8(_ v: UInt8) {
        data.append(v)
    }

    mutating func u16(_ v: UInt16) {
        data.append(UInt8(truncatingIfNeeded: v))
        data.append(UInt8(truncatingIfNeeded: v >> 8))
    }

    mutating func u32(_ v: UInt32) {
        for shift in stride(from: 0, to: 32, by: 8) {
            data.append(UInt8(truncatingIfNeeded: v >> UInt32(shift)))
        }
    }

    mutating func u64(_ v: UInt64) {
        for shift in stride(from: 0, to: 64, by: 8) {
            data.append(UInt8(truncatingIfNeeded: v >> UInt64(shift)))
        }
    }

    mutating func f32(_ v: Float) {
        u32(v.bitPattern)
    }

    mutating func f64(_ v: Double) {
        u64(v.bitPattern)
    }
}

struct ByteReader {
    private let bytes: [UInt8]
    private var offset = 0

    init(_ data: Data) {
        bytes = [UInt8](data)
    }

    mutating func header() throws -> (MessageType, UInt32, Double) {
        let magic = Array(bytes[0..<4])
        offset = 4
        guard magic == MagiCAMProtocol.magic else { throw ProtocolError.badMagic }
        let version = u16()
        guard version == MagiCAMProtocol.version else { throw ProtocolError.badVersion(version) }
        let rawType = u16()
        guard let type = MessageType(rawValue: rawType) else { throw ProtocolError.badType(rawType) }
        let seq = u32()
        let t = f64()
        return (type, seq, t)
    }

    mutating func u8() -> UInt8 {
        let v = bytes[offset]
        offset += 1
        return v
    }

    mutating func u16() -> UInt16 {
        let lo = UInt16(u8())
        let hi = UInt16(u8())
        return lo | (hi << 8)
    }

    mutating func u32() -> UInt32 {
        var v: UInt32 = 0
        for shift in stride(from: 0, to: 32, by: 8) {
            v |= UInt32(u8()) << UInt32(shift)
        }
        return v
    }

    mutating func u64() -> UInt64 {
        var v: UInt64 = 0
        for shift in stride(from: 0, to: 64, by: 8) {
            v |= UInt64(u8()) << UInt64(shift)
        }
        return v
    }

    mutating func f32() -> Float {
        Float(bitPattern: u32())
    }

    mutating func f64() -> Double {
        Double(bitPattern: u64())
    }
}
