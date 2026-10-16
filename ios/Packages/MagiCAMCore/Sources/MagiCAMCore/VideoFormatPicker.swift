// Scelta del formato video di ARKit. Il default di ARWorldTrackingConfiguration sull'iPhone dell'utente gira a
// 30 fps (2026-10-16: 327 frame in 10,90 s dal t_sensor, intrinseche 1920x1440): la camera di Maya riceveva meta'
// delle pose possibili. Qui la regola, in Swift puro (senza ARKit) per provarla con `swift test`:
// fps piu' alti prima, a parita' di fps piu' pixel, a parita' di tutto il primo dell'elenco di ARKit.

public struct VideoFormatCandidate: Equatable {
    public var framesPerSecond: Int
    public var width: Int
    public var height: Int

    public init(framesPerSecond: Int, width: Int, height: Int) {
        self.framesPerSecond = framesPerSecond
        self.width = width
        self.height = height
    }

    public var label: String { "\(framesPerSecond) fps · \(width)×\(height)" }
}

public enum VideoFormatPicker {
    /// Indice del formato da usare, `nil` se l'elenco e' vuoto (allora resta il default di ARKit).
    public static func bestIndex(_ candidates: [VideoFormatCandidate]) -> Int? {
        var best: Int?
        for (i, c) in candidates.enumerated() {
            guard let b = best else {
                best = i
                continue
            }
            let o = candidates[b]
            if c.framesPerSecond > o.framesPerSecond
                || (c.framesPerSecond == o.framesPerSecond && c.width * c.height > o.width * o.height)
            {
                best = i
            }
        }
        return best
    }
}
