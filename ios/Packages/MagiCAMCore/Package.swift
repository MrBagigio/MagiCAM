// swift-tools-version:5.7
// MagiCAMCore: il protocollo (docs/PROTOCOL.md) in Swift puro, senza ARKit ne' UIKit, cosi' si prova con
// `swift test` su macOS in CI, senza simulatore. L'app iOS lo usa come pacchetto locale (ios/project.yml).
import PackageDescription

let package = Package(
    name: "MagiCAMCore",
    platforms: [.iOS(.v15), .macOS(.v12)],
    products: [
        .library(name: "MagiCAMCore", targets: ["MagiCAMCore"])
    ],
    targets: [
        .target(name: "MagiCAMCore", path: "Sources/MagiCAMCore"),
        .testTarget(name: "MagiCAMCoreTests", dependencies: ["MagiCAMCore"], path: "Tests/MagiCAMCoreTests"),
    ]
)
