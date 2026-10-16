// R4: il banner da ripresa. Ogni stato si prova contro il suo opposto: il verde arriva SOLO con stats fresche,
// calibrata, tracking normale, senza freeze e senza caldo.

import XCTest
@testable import MagiCAMCore

final class LiveStatusTests: XCTestCase {
    private func stats(_ flags: StatsFlags) -> StatsMessage {
        StatsMessage(seq: 1, tSensor: 0, received: 300, lost: 2, latencyMs: 9, flags: flags)
    }

    private func eval(
        running: Bool = true, link: UDPLink.State = .ready, flags: StatsFlags? = [.calibrated],
        age: TimeInterval = 0.4, tracking: Bool = true, thermal: Int = 0
    ) -> LiveStatus {
        LiveStatus.evaluate(running: running, link: link, stats: flags.map(stats), statsAge: age,
                            trackingNormal: tracking, thermal: thermal)
    }

    func testGreenOnlyWhenThePCConfirms() {
        let ok = eval()
        XCTAssertEqual(ok.level, .ok)
        XCTAssertEqual(ok.title, "DAL VIVO")
        XCTAssertEqual(ok.detail, "ricevuti 300 · persi 2")
        // stesse condizioni, ma stats vecchie: rosso, non verde
        XCTAssertEqual(eval(age: 3.5).level, .bad)
        XCTAssertEqual(eval(age: 3.5).title, "MAYA NON RISPONDE")
        // mai arrivate
        let never = eval(flags: nil, age: .infinity)
        XCTAssertEqual(never.level, .bad)
        XCTAssertTrue(never.detail.contains("IP"))
    }

    func testStoppedAndNetworkError() {
        XCTAssertEqual(eval(running: false).level, .off)
        let e = eval(link: .failed("rete non raggiungibile"))
        XCTAssertEqual(e.level, .bad)
        XCTAssertEqual(e.detail, "rete non raggiungibile")
    }

    func testWarningsWhenTheCameraDoesNotMove() {
        XCTAssertEqual(eval(flags: []).title, "COLLEGATO · CALIBRA")
        XCTAssertEqual(eval(flags: [.calibrated, .frozen]).title, "FREEZE")
        XCTAssertEqual(eval(tracking: false).title, "TRACKING FERMO")
        XCTAssertEqual(eval(flags: [.calibrated, .trackingBad]).title, "TRACKING FERMO")
        for s in [eval(flags: []), eval(flags: [.calibrated, .frozen]), eval(tracking: false)] {
            XCTAssertEqual(s.level, .warn)
        }
    }

    func testThermal() {
        XCTAssertEqual(eval(thermal: 1).level, .ok) // «fair»: normale per un telefono che lavora
        XCTAssertEqual(eval(thermal: 2).level, .warn)
        XCTAssertEqual(eval(thermal: 2).title, "DAL VIVO · TELEFONO CALDO")
        XCTAssertEqual(eval(thermal: 3).level, .bad)
        // il caldo critico vince anche su stats fresche e tutto a posto
        XCTAssertEqual(eval(thermal: 3).title, "TELEFONO TROPPO CALDO")
    }
}
