// R4 (docs/VALUTAZIONE_REGIA_LIVE.md): lo stato da ripresa che l'operatore legge a colpo d'occhio, in un banner grande.
// Deciso qui, in Swift puro, cosi' le regole si provano con `swift test` in CI; l'app gli passa solo i fatti.
//
// Regola di fondo: si dice cio' che il PC CONFERMA (le stats che rimanda, con i loro flag). Senza stats fresche il
// telefono non sa se Maya lo riceve, e lo dice in rosso: un verde senza conferma sarebbe un canale che mente.

import Foundation

public enum LiveLevel: Equatable {
    case off // fermo: grigio
    case ok // dal vivo, confermato dal PC: verde
    case warn // collegato ma la camera non si muove (calibra, freeze, tracking, caldo): arancio
    case bad // non arriva niente o il telefono sta per fermarsi: rosso
}

public struct LiveStatus: Equatable {
    public let level: LiveLevel
    public let title: String
    public let detail: String

    public init(level: LiveLevel, title: String, detail: String) {
        self.level = level
        self.title = title
        self.detail = detail
    }

    /// Stats piu' vecchie di cosi' = il PC non risponde piu' (il PC le manda ogni 0,5 s).
    public static let statsFreshSeconds: TimeInterval = 3

    /// - Parameters:
    ///   - running: il telefono trasmette (ARKit acceso)
    ///   - link: stato della connessione UDP
    ///   - stats: ultime stats dal PC (nil = mai arrivate)
    ///   - statsAge: secondi dall'ultima stats
    ///   - trackingNormal: tracking ARKit «normale» sul telefono
    ///   - thermal: `ProcessInfo.ThermalState.rawValue` (0 nominale … 3 critico)
    public static func evaluate(
        running: Bool,
        link: UDPLink.State,
        stats: StatsMessage?,
        statsAge: TimeInterval,
        trackingNormal: Bool,
        thermal: Int
    ) -> LiveStatus {
        guard running else {
            return LiveStatus(level: .off, title: "FERMO", detail: "premi Avvia")
        }
        if case .failed(let why) = link {
            return LiveStatus(level: .bad, title: "RETE: ERRORE", detail: why)
        }
        if thermal >= 3 {
            return LiveStatus(level: .bad, title: "TELEFONO TROPPO CALDO",
                              detail: "iOS sta per rallentare ARKit: fermati e lascialo raffreddare")
        }
        guard let s = stats, statsAge < statsFreshSeconds else {
            let detail = stats == nil
                ? "Maya non ha mai risposto: controlla IP, porta e codice"
                : String(format: "nessuna risposta da %.0f s", statsAge)
            return LiveStatus(level: .bad, title: "MAYA NON RISPONDE", detail: detail)
        }
        let counts = "ricevuti \(s.received) · persi \(s.lost)"
        let hot = thermal == 2 ? " · telefono caldo" : ""
        if !s.flags.contains(.calibrated) {
            return LiveStatus(level: .warn, title: "COLLEGATO · CALIBRA", detail: counts + hot)
        }
        if !trackingNormal || s.flags.contains(.trackingBad) {
            return LiveStatus(level: .warn, title: "TRACKING FERMO",
                              detail: "inquadra qualcosa con dettagli e luce" + hot)
        }
        if s.flags.contains(.frozen) {
            return LiveStatus(level: .warn, title: "FREEZE", detail: counts + hot)
        }
        if thermal == 2 {
            return LiveStatus(level: .warn, title: "DAL VIVO · TELEFONO CALDO", detail: counts)
        }
        return LiveStatus(level: .ok, title: "DAL VIVO", detail: counts)
    }
}
