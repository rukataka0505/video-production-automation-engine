// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "ObserverCore",
    platforms: [.iOS(.v17), .macOS(.v13)],
    products: [.library(name: "ObserverCore", targets: ["ObserverCore"]),
               .executable(name: "CaptureFixture", targets: ["CaptureFixture"])],
    targets: [.target(name: "ObserverCore"),
              .executableTarget(name: "CaptureFixture", dependencies: ["ObserverCore"]),
              .testTarget(name: "ObserverCoreTests", dependencies: ["ObserverCore"])])
