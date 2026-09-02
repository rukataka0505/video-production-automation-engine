# Kdenliveへの読み込み

このPoCはKdenlive 26.04.3で実インポート・保存・再オープン確認済み。通常は `edit.kdenlive` を直接開く。

OTIOから再作成する場合:

1. Kdenlive 26.04以降を起動する。
2. 「ファイル → OpenTimelineIOをインポート」で `edit.otio` を選ぶ。
3. 字幕メニューから `../subtitles/subtitles.ass` をインポートする。
4. 読み込み後、Kdenlive自身で `edit.kdenlive` として保存する。

V1はシーン素材、A1は句単位のVOICEVOXナレーション、A2はBGM。字幕はASSとして独立している。素材差し替え、カット、尺、字幕テキスト・色・位置、BGM、音量、順番を編集できる。
