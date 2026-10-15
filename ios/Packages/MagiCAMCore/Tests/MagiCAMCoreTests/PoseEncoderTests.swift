// Gli stessi vettori di tests/test_protocol.py (VETTORI_NOTI), generati da magicam.protocol:
// Python e Swift devono produrre gli stessi byte, altrimenti il telefono e Maya non si parlano.

import XCTest
@testable import MagiCAMCore

final class PoseEncoderTests: XCTestCase {
    // header 'MGC2', v2, pose, seq 7, t 1.5; normal/none; pos (0.1,0.2,0.3); quat (0,0,0,1); focal 1000; 1920x1080; ev 0
    static let poseHex =
        "4d4743320200010007000000000000000000f83f0000cdcccc3dcdcc4c3e9a99993e"
        + "0000000000000000000000000000803f00007a448007380400000000"
    // header seq 3, t 2.0; cmd scaleSet(7); token 0xDEADBEEF; value 0.1
    static let commandHex = "4d474332020002000300000000000000000000400700efbeaddecdcccc3d"
    // header seq 1, t 3.0; received 600; lost 12; latency 18.5; flags 0b1011
    static let statsHex = "4d47433202000300010000000000000000000840580200000c000000000094410b"

    static func data(_ hex: String) -> Data {
        var bytes: [UInt8] = []
        var i = hex.startIndex
        while i < hex.endIndex {
            let j = hex.index(i, offsetBy: 2)
            bytes.append(UInt8(hex[i..<j], radix: 16)!)
            i = j
        }
        return Data(bytes)
    }

    func testPoseMatchesPythonVector() {
        let m = PoseMessage(
            seq: 7, tSensor: 1.5, trackingState: .normal, trackingReason: .none,
            position: SIMD3<Float>(0.1, 0.2, 0.3), quaternion: SIMD4<Float>(0, 0, 0, 1),
            focalPx: 1000, imageWidth: 1920, imageHeight: 1080, exposureOffset: 0
        )
        let d = PoseEncoder.encode(m)
        XCTAssertEqual(d.count, MagiCAMProtocol.poseSize)
        XCTAssertEqual(d, Self.data(Self.poseHex))
    }

    func testCommandMatchesPythonVector() {
        let m = CommandMessage(seq: 3, tSensor: 2.0, command: .scaleSet, token: 0xDEAD_BEEF, value: 0.1)
        let d = PoseEncoder.encode(m)
        XCTAssertEqual(d.count, MagiCAMProtocol.commandSize)
        XCTAssertEqual(d, Self.data(Self.commandHex))
    }

    func testStatsRoundtripAgainstPythonVector() throws {
        let d = Self.data(Self.statsHex)
        let s = try PoseEncoder.decodeStats(d)
        XCTAssertEqual(s.seq, 1)
        XCTAssertEqual(s.tSensor, 3.0)
        XCTAssertEqual(s.received, 600)
        XCTAssertEqual(s.lost, 12)
        XCTAssertEqual(s.latencyMs, 18.5, accuracy: 1e-5)
        XCTAssertEqual(s.flags, [.calibrated, .frozen, .trackingBad])
        XCTAssertEqual(PoseEncoder.encode(s), d)
    }

    func testStatsRejectsWrongLengthMagicVersionType() {
        var d = Self.data(Self.statsHex)
        XCTAssertThrowsError(try PoseEncoder.decodeStats(d.dropLast()))
        d[0] = 0x58
        XCTAssertThrowsError(try PoseEncoder.decodeStats(d))
        d = Self.data(Self.statsHex)
        d[4] = 1
        XCTAssertThrowsError(try PoseEncoder.decodeStats(d))
        d = Self.data(Self.statsHex)
        d[6] = 1 // type = pose, lunghezza di stats
        XCTAssertThrowsError(try PoseEncoder.decodeStats(d))
    }

    func testTrackingCodesMatchProtocolTable() {
        XCTAssertEqual(TrackingStateCode.limited.rawValue, 1)
        XCTAssertEqual(TrackingReasonCode.insufficientFeatures.rawValue, 4)
        XCTAssertEqual(CommandCode.ping.rawValue, 8)
    }
}
