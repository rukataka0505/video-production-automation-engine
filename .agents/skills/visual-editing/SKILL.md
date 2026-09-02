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

- 動画、静止画、図表に固定の優先順位を設けず、内容との一致、資料価値、構図、画質で選ぶ。
- PDF等の文書は、原文、ページ、図表を見せること自体が説明になる時だけ必要な領域を読みやすく採用する。
- 採用した素材を `assets/selected` 等へ置き、実際に使うパスを `project.json` のshotへ記録する。
- 個人利用の制作では素材の出典、権利、ライセンス記録を必須にしない。公開、配布、商用利用する場合は用途に合う利用条件を確認する。
- 静止画は固定を基本にし、必要な時だけKdenlive/MLTの `qtblend` Transformを控えめに使う。FFmpeg `zoompan` は使わない。
- FFmpegでプレビューと最終動画、ASSで同一本文の字幕、OpenTimelineIOで映像、ナレーション、BGMを分離したタイムラインを作る。Kdenliveネイティブ成果物は明示的な指定がある時だけKdenlive自身で保存する。
- `work/scene-rendering.json` と `work/scenes` はレンダー内部のキャッシュと再利用管理に使い、納品成果物にはしない。

## QA

映像確認に役立つ場合だけ代表フレームやコンタクトシートを作る。黒画面、欠損、字幕切れ、読みにくさ、内容と合わない素材、不自然なモーションなど、実際に確認できた問題だけ直す。
