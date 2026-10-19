import Foundation

public enum CaptureFailure: Error {
    case invalidLimit, closed, emptyChunk, limit, timestamp, duplicateDirectory
}

/// Local files only. No accessory, network, packet builder or transmission API.
public final class CaptureWriter {
    public static let maximumBytes = 32 * 1024 * 1024
    public static let maximumNanoseconds: UInt64 = 30_000_000_000
    public static let maximumChunks = 65_536
    public static let magic = Data("N2RX0001".utf8)
    public let directory: URL
    public private(set) var rxBytes = 0
    public private(set) var chunks = 0
    public private(set) var lastNanoseconds: UInt64 = 0
    public var remaining: Int { limit - rxBytes }
    private let limit: Int
    private let context: [String: Any]
    private var file: FileHandle?
    private var events: [[String: Any]] = []
    private var finished = false

    public init(directory: URL, context: [String: Any], limit: Int = maximumBytes) throws {
        guard limit > 0, limit <= Self.maximumBytes else { throw CaptureFailure.invalidLimit }
        guard !FileManager.default.fileExists(atPath: directory.path) else {
            throw CaptureFailure.duplicateDirectory
        }
        self.directory = directory
        self.context = context
        self.limit = limit
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("capture.n2rx")
        guard FileManager.default.createFile(atPath: url.path, contents: Self.magic) else {
            throw CocoaError(.fileWriteUnknown)
        }
        file = try FileHandle(forWritingTo: url)
        do {
            try file?.seekToEnd()
            events = [["kind": "capture_created", "elapsed_ns": UInt64(0)]]
            try saveManifest(reason: "opening", complete: false, elapsed: 0,
                             transportClosed: false, flushed: false, fileClosed: false)
        } catch {
            try? file?.close()
            file = nil
            throw error
        }
    }

    public func event(_ kind: String, at nanoseconds: UInt64) {
        guard !finished, events.count < 64 else { return }
        events.append(["kind": String(kind.prefix(80)), "elapsed_ns": nanoseconds])
    }

    public func append(_ data: Data, at nanoseconds: UInt64) throws {
        guard !finished, let file else { throw CaptureFailure.closed }
        guard !data.isEmpty else { throw CaptureFailure.emptyChunk }
        guard data.count <= remaining, data.count <= 16_384,
              chunks < Self.maximumChunks else { throw CaptureFailure.limit }
        guard nanoseconds >= lastNanoseconds, nanoseconds <= Self.maximumNanoseconds else {
            throw CaptureFailure.timestamp
        }
        var record = Data()
        var time = nanoseconds.littleEndian
        var count = UInt32(data.count).littleEndian
        withUnsafeBytes(of: &time) { record.append(contentsOf: $0) }
        withUnsafeBytes(of: &count) { record.append(contentsOf: $0) }
        record.append(data)
        // A failed/partial disk write leaves an incomplete file and no success manifest.
        try file.write(contentsOf: record)
        rxBytes += data.count
        chunks += 1
        lastNanoseconds = nanoseconds
    }

    public func finish(reason: String, at nanoseconds: UInt64, transportClosed: Bool,
                       successful: Bool = true) throws {
        guard !finished else { return }
        finished = true
        var flushed = false
        var fileClosed = false
        if let handle = file {
            do { try handle.synchronize(); flushed = true } catch { flushed = false }
            do { try handle.close(); fileClosed = true } catch { fileClosed = false }
        }
        file = nil
        events.append(["kind": "capture_finished", "elapsed_ns": nanoseconds,
                       "reason": String(reason.prefix(80))])
        try saveManifest(reason: reason,
                         complete: successful && transportClosed && flushed && fileClosed,
                         elapsed: nanoseconds, transportClosed: transportClosed,
                         flushed: flushed, fileClosed: fileClosed)
        guard flushed, fileClosed else { throw CocoaError(.fileWriteUnknown) }
    }

    private func saveManifest(reason: String, complete: Bool, elapsed: UInt64,
                              transportClosed: Bool, flushed: Bool, fileClosed: Bool) throws {
        let manifest: [String: Any] = [
            "schema": "neo2-ios-rx-capture/1", "format": "N2RX0001",
            "direction": "rx_only", "context": context, "capture_complete": complete,
            "rx_bytes": rxBytes, "chunks": chunks, "tx_attempts": 0,
            "elapsed_ns": elapsed, "last_chunk_elapsed_ns": lastNanoseconds,
            "byte_limit": limit, "duration_limit_ns": Self.maximumNanoseconds,
            "chunk_limit": Self.maximumChunks,
            "transport_closed": transportClosed, "file_flushed": flushed,
            "file_closed": fileClosed, "stop_reason": String(reason.prefix(80)),
            "events": events, "manual_acceptance_verified": false,
            "time_basis": "host monotonic time immediately before read; not FC generation time"
        ]
        let bytes = try JSONSerialization.data(withJSONObject: manifest, options: [.sortedKeys, .prettyPrinted])
        try bytes.write(to: directory.appendingPathComponent("manifest.json"), options: .atomic)
    }

    deinit { try? file?.close() }
}
