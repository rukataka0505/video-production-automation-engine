import Foundation
import ObserverCore

guard CommandLine.arguments.count == 2 else { fatalError("Output directory required") }
let writer = try CaptureWriter(directory: URL(fileURLWithPath: CommandLine.arguments[1]),
                               context: ["data_kind": "synthetic", "fixture": "swift-writer-v1"])
try writer.append(Data([0x00, 0x55, 0xff]), at: 100)
try writer.append(Data([0x80, 0x01, 0x02, 0x03]), at: 200)
try writer.finish(reason: "fixture", at: 300, transportClosed: true)
print("Synthetic fixture written; no device IO")
