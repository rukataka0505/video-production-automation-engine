---
name: visual-editing
description: 承認済み動画のshot設計、素材選定、FFmpeg編集、OTIO/Kdenliveタイムライン、字幕、必要時のQAに使う。
---

# Visual Editing

内容に合う視覚変化を作り、後からKdenliveで編集できる成果物を残す。

## Shot設計

- `scene.shots` を使い、一つのシーン内で必要なだけshotを切り替える。
- `duration_seconds` を省略したshotには、VOICEVOX実測のシーン尺から残りを均等配分する。
- 実写動画はループしない。`source_start` 以降の素材尺が足りなければ別shotへ切り替える。

```json
"shots": [
  {
    "path": "assets/selected/unveil.mp4",
    "type": "video",
    "source_start": 12.5,
    "duration_seconds": 4.0
  },
  {
    "path": "assets/selected/interior.jpg",
    "type": "image",
    "motion": "none"
  }
]
```

## 素材と編集
- 視覚的にわかりやすく関連度の高い、動画や画像を優先的に採用する。
- PDF等の文書は基本的に採用しないが、それを見せること自体が説明になる時だけ必要な領域を読みやすく採用する。
- 採用した素材を `assets/selected` 等へ置き、実際に使うパスを `project.json` のshotへ記録する。
- 個人利用の制作では素材の出典、権利、ライセンス記録をしない。
- 静止画は必要に応じてKdenlive/MLTの `qtblend` Transformを使う。
- FFmpegでプレビューと最終動画、ASSで同一本文の字幕、OpenTimelineIOで映像、ナレーション、BGMを分離したタイムラインを作る。Kdenliveネイティブ成果物は明示的な指定がある時だけKdenlive自身で保存する。
- `work/scene-rendering.json` と `work/scenes` はレンダー内部のキャッシュと再利用管理に使い、納品成果物にはしない。
- Codexは `tools/render_job.py start` でレンダーをバックグラウンド起動し、`wait` または `status` の短い状態だけを読む。FFmpeg/MLTの進捗ログは読み続けず、失敗時の診断にだけ使う。
- 同一入力のシーンと完成出力は自動再利用する。再レンダー理由が明確な場合を除き `--force` を使わない。

## サムネイル

- 承認済みの `project.thumbnail` に従い、画像生成、既存素材、FFmpeg、ImageMagick等の利用可能な既存ツールを必要に応じて組み合わせる。独自の描画・レイアウト基盤は実装しない。
- 動画内容と一致する一つの主役を明確にし、文字は短く大きく、小さい表示でも主役と文言を判別できる構図にする。YouTubeタイトルと同じ文言を重ねない。
- 16:9、幅640px以上のJPEGを `output/thumbnail.jpg` に作り、縮小表示も目視確認する。

## QA

映像確認に役立つ場合だけ代表フレームやコンタクトシートを作る。黒画面、欠損、字幕切れ、読みにくさ、内容と合わない素材、不自然なモーションなど、実際に確認できた問題だけ直す。
