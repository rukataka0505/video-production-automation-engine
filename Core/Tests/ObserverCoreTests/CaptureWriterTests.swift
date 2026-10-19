import Foundation
import XCTest
@testable import ObserverCore

final class CaptureWriterTests: XCTestCase {
    private func path() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    }

    func testLimitAndClosedWriterCannotAppend() throws {
        let url = path()
        defer { try? FileManager.default.removeItem(at: url) }
        let writer = try CaptureWriter(directory: url, context: ["data_kind": "synthetic"], limit: 3)
        try writer.append(Data([0, 1]), at: 1)
        XCTAssertThrowsError(try writer.append(Data([2, 3]), at: 2))
        XCTAssertEqual(writer.rxBytes, 2)
        try writer.append(Data([2]), at: 2)
        try writer.finish(reason: "byte_limit", at: 3, transportClosed: true)
        XCTAssertThrowsError(try writer.append(Data([3]), at: 4))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url.appendingPathComponent("manifest.json"))) as? [String: Any])
        XCTAssertEqual(json["rx_bytes"] as? Int, 3)
        XCTAssertEqual(json["capture_complete"] as? Bool, true)
        XCTAssertEqual(json["tx_attempts"] as? Int, 0)
    }

    func testClockRegressionAndOvertimeAreRejectedBeforeWriting() throws {
        let url = path()
        defer { try? FileManager.default.removeItem(at: url) }
        let writer = try CaptureWriter(directory: url, context: ["data_kind": "synthetic"])
        try writer.append(Data([85]), at: 10)
        XCTAssertThrowsError(try writer.append(Data([1]), at: 9))
        XCTAssertThrowsError(try writer.append(Data([1]), at: CaptureWriter.maximumNanoseconds + 1))
        XCTAssertEqual(writer.rxBytes, 1)
        try writer.finish(reason: "test_error", at: 11, transportClosed: true, successful: false)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url.appendingPathComponent("manifest.json"))) as? [String: Any])
        XCTAssertEqual(json["capture_complete"] as? Bool, false)
    }

    func testExistingDirectoryIsNeverOverwritten() throws {
        let url = path()
        defer { try? FileManager.default.removeItem(at: url) }
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        XCTAssertThrowsError(try CaptureWriter(directory: url, context: [:]))
    }
}
