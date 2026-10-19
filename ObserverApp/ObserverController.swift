import Combine
import CryptoKit
import ExternalAccessory
import Foundation
import ObserverCore

/// All transport lifecycle and file writes run on the main run loop.
/// No output stream is opened, retained or written. No command API exists.
final class ObserverController: NSObject, ObservableObject, StreamDelegate {
    static let protocolName = "com.dji.logiclink"
    @Published private(set) var accessories: [EAAccessory] = []
    @Published var selection: String?
    @Published private(set) var capturing = false
    @Published private(set) var message = "接続先を確認してから受信を開始してください。"
    @Published private(set) var received = 0
    @Published private(set) var folder: URL?
    private var session: EASession?
    private var input: InputStream?
    private var writer: CaptureWriter?
    private var timer: Timer?
    private var startTime: UInt64 = 0
    private var connection: String?
    private var notificationTokens: [NSObjectProtocol] = []
    private var readScheduled = false

    override init() {
        super.init()
        let center = NotificationCenter.default
        notificationTokens.append(center.addObserver(forName: .EAAccessoryDidConnect,
                                                      object: nil, queue: .main) { [weak self] _ in self?.refresh() })
        notificationTokens.append(center.addObserver(forName: .EAAccessoryDidDisconnect,
                                                      object: nil, queue: .main) { [weak self] note in
            guard let self else { return }
            if let accessory = note.userInfo?[EAAccessoryKey] as? EAAccessory,
               String(accessory.connectionID) == self.connection {
                self.stop("accessory_disconnected")
            }
            self.refresh()
        })
        EAAccessoryManager.shared().registerForLocalNotifications()
        refresh() // Enumeration only. Never opens a session automatically.
    }

    func refresh() {
        precondition(Thread.isMainThread)
        accessories = EAAccessoryManager.shared().connectedAccessories.filter {
            $0.protocolStrings.contains(Self.protocolName)
        }
        if !accessories.contains(where: { String($0.connectionID) == selection }) {
            selection = accessories.count == 1 ? String(accessories[0].connectionID) : nil
        }
    }

    private var elapsed: UInt64 { DispatchTime.now().uptimeNanoseconds - startTime }

    func start() {
        precondition(Thread.isMainThread)
        guard !capturing else { return }
        refresh()
        guard let accessory = accessories.first(where: { String($0.connectionID) == selection }),
              accessory.isConnected else {
            message = "接続先が未選択、または接続されていません。"
            return
        }
        folder = nil
        received = 0
        do {
            let base = try FileManager.default.url(for: .documentDirectory, in: .userDomainMask,
                                                   appropriateFor: nil, create: true)
            let location = base.appendingPathComponent("Captures").appendingPathComponent(UUID().uuidString)
            let identity = [accessory.manufacturer, accessory.modelNumber, accessory.serialNumber].joined(separator: "\u{0}")
            let digest = SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
            let context: [String: Any] = [
                "data_kind": "measured", "protocol": Self.protocolName,
                "manufacturer": accessory.manufacturer, "model": accessory.modelNumber,
                "firmware": accessory.firmwareRevision, "identity_sha256": digest,
                "serial_present": !accessory.serialNumber.isEmpty,
                "source_commit": Bundle.main.object(forInfoDictionaryKey: "ObserverSourceCommit") as? String ?? "unverified",
                "application_configuration": "RX_ONLY_1",
                "created_at_utc": ISO8601DateFormatter().string(from: Date())
            ]
            startTime = DispatchTime.now().uptimeNanoseconds
            writer = try CaptureWriter(directory: location, context: context)
            folder = location
            received = 0
            connection = String(accessory.connectionID)
            guard let newSession = EASession(accessory: accessory, forProtocol: Self.protocolName),
                  let stream = newSession.inputStream else {
                stop("session_unavailable", successful: false)
                return
            }
            session = newSession
            input = stream
            capturing = true
            stream.delegate = self
            stream.schedule(in: .main, forMode: .common)
            stream.open()
            guard capturing, input === stream else { return }
            let deadlineTimer = Timer(timeInterval: 0.05, repeats: true) { [weak self] _ in
                guard let self else { return }
                if self.elapsed >= CaptureWriter.maximumNanoseconds { self.stop("duration_limit") }
            }
            timer = deadlineTimer
            RunLoop.main.add(deadlineTimer, forMode: .common)
            message = "受信中。30秒または32MiBで終了します。"
        } catch {
            stop("start_error", successful: false)
            message = "記録を開始できませんでした。機体状態は未判定です。"
        }
    }

    func stream(_ aStream: Stream, handle eventCode: Stream.Event) {
        precondition(Thread.isMainThread)
        guard aStream === input, capturing else { return }
        if eventCode.contains(.errorOccurred) { stop("stream_error", successful: false); return }
        if eventCode.contains(.endEncountered) {
            drain()
            if capturing { stop("stream_end", successful: !(input?.hasBytesAvailable ?? false)) }
            return
        }
        if eventCode.contains(.openCompleted) { writer?.event("stream_opened", at: elapsed) }
        if eventCode.contains(.hasBytesAvailable) { drain() }
    }

    private func drain() {
        precondition(Thread.isMainThread)
        guard capturing, let stream = input, let writer else { return }
        var buffer = [UInt8](repeating: 0, count: 16_384)
        for _ in 0..<16 { // Yield to the main run loop; never starve Stop/timer.
            guard capturing, stream.hasBytesAvailable else { return }
            guard elapsed < CaptureWriter.maximumNanoseconds else { stop("duration_limit"); return }
            guard writer.remaining > 0 else { stop("byte_limit"); return }
            guard writer.chunks < CaptureWriter.maximumChunks else { stop("chunk_limit"); return }
            let stamp = elapsed
            guard stamp < CaptureWriter.maximumNanoseconds else { stop("duration_limit"); return }
            let size = min(buffer.count, writer.remaining)
            let count = stream.read(&buffer, maxLength: size)
            if count < 0 { stop("read_error", successful: false); return }
            if count == 0 { return }
            do {
                try writer.append(Data(buffer.prefix(count)), at: stamp)
                received = writer.rxBytes
            } catch { stop("capture_write_error", successful: false); return }
            if writer.remaining == 0 { stop("byte_limit"); return }
        }
        if !readScheduled, stream.hasBytesAvailable {
            readScheduled = true
            let current = stream
            DispatchQueue.main.async { [weak self] in
                guard let self else { return }
                self.readScheduled = false
                if self.input === current { self.drain() }
            }
        }
    }

    func stop(_ reason: String = "owner_stop", successful: Bool = true) {
        precondition(Thread.isMainThread)
        guard writer != nil || session != nil else { return }
        let stamp = elapsed
        capturing = false
        timer?.invalidate()
        timer = nil
        input?.delegate = nil
        input?.close()
        input?.remove(from: .main, forMode: .common)
        input = nil
        session = nil
        connection = nil
        readScheduled = false
        do {
            try writer?.finish(reason: reason, at: stamp, transportClosed: true, successful: successful)
            message = successful
                ? (received == 0 ? "受信0 byte。接続・初期化は未判定です。" : "記録終了。機体状態はまだ解析していません。")
                : "記録は不完全です。終了理由をmanifestで確認してください。"
        } catch { message = "保存の確定に失敗しました。完全な記録として扱えません。" }
        writer = nil
    }

    deinit {
        notificationTokens.forEach { NotificationCenter.default.removeObserver($0) }
    }
}
