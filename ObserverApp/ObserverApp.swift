import ExternalAccessory
import SwiftUI

@main
struct ObserverApp: App {
    @StateObject private var controller = ObserverController()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            NavigationStack {
                List {
                    Section("受信のみ・30秒／32MiB") {
                        Text(controller.message)
                        Text("受信: \(controller.received) byte")
                        Text("開始するとDJI Flyの接続に影響する可能性があります。受信0 byteでも機体のモード拒否とは判定しません。")
                            .font(.footnote)
                    }
                    Section("接続先") {
                        Picker("アクセサリ", selection: $controller.selection) {
                            Text("未選択").tag(Optional<String>.none)
                            ForEach(controller.accessories, id: \.connectionID) { accessory in
                                Text("\(accessory.manufacturer) / \(accessory.modelNumber)")
                                    .tag(Optional(String(accessory.connectionID)))
                            }
                        }
                        .disabled(controller.capturing)
                        Button("一覧を更新") { controller.refresh() }.disabled(controller.capturing)
                    }
                    Section {
                        Button("30秒の受信を開始") { controller.start() }
                            .disabled(controller.capturing || controller.selection == nil)
                        Button("記録を終了") { controller.stop() }.disabled(!controller.capturing)
                    }
                    if let folder = controller.folder, !controller.capturing {
                        Section("保存したファイル") {
                            ShareLink("受信byteを保存", item: folder.appendingPathComponent("capture.n2rx"))
                            ShareLink("記録情報を保存", item: folder.appendingPathComponent("manifest.json"))
                            Text("Appleデバイスのファイル共有、またはファイルAppからCapturesフォルダ全体を回収できます。")
                                .font(.footnote)
                        }
                    }
                }
                .navigationTitle("Neo2 RX Observer")
                .onChange(of: scenePhase) { _, phase in
                    if phase != .active { controller.stop("app_not_active") }
                }
            }
        }
    }
}
