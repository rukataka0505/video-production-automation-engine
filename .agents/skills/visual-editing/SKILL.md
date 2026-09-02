---
name: visual-editing
description: 承認済み動画のshot設計、素材選定、FFmpeg編集、OTIO/Kdenliveタイムライン、字幕、QAに使う。
---

# Visual Editing

内容に合う視覚変化を作り、後からKdenliveで編集できる成果物を残す。

## Shot設計

- `scene.shots` を使い、一つのシーン内で必要なだけshotを切り替える。各shotの `visual_intent` は、その画で何を理解させるかを短く書く。
- `duration_seconds` を省略したshotには、VOICEVOX実測のシーン尺から残りを均等配分する。カット位置を指定する場合は最後のshotを省略して残りを受け持たせる。
- 実写動画はループしない。`source_start` 以降の素材尺が足りなければ、同じ素材を繰り返さず別shotへ切り替える。
- 同じ素材の長時間表示、連続使用、過剰な使い回しは、プレビューとコンタクトシートを見て減らす。秒数閾値だけで機械判定しない。

```json
"shots": [
  {
    "visual_intent": "発表会場で実車の外観を見せる",
    "path": "assets/selected/unveil.mp4",
    "type": "video",
    "source_start": 12.5,
    "duration_seconds": 4.0,
    "source_id": "visual-unveil"
  },
  {
    "visual_intent": "車内の二人乗り設計へ視点を移す",
    "path": "assets/selected/interior.jpg",
    "type": "image",
    "motion": "none",
    "source_id": "visual-interior"
  }
]
```

## 素材と編集

- 動画、静止画、図表に固定の優先順位を設けず、内容との一致、資料価値、構図、画質、権利条件で選ぶ。
- PDF等の文書は通常のB-rollにしない。原文、ページ、図表を見せること自体が説明になる時だけ、必要領域を読みやすく採用して `visual_assets` にページ番号と用途を記録する。
- 採用素材だけを `assets/selected` 等へ置く。候補画像、PDFページ画像、QA画像、`work` 以下の中間物は再生成可能としてGitへ追加しない。
- 静止画は固定を基本にし、必要な時だけKdenlive/MLTのTransformを控えめに使う。FFmpeg `zoompan` は使わない。
- FFmpegでプレビューと最終動画、ASSで同一本文の字幕、OpenTimelineIOで複数clipの映像トラックと分離音声を作る。ネイティブKdenlive成果物は指定時だけKdenlive自身で保存する。

## QA

代表フレームとシーンのコンタクトシートを実見し、黒画面、欠損、字幕切れ、読みにくさ、無関係素材、単調さ、不自然なモーション、使い回しを確認する。確認できた問題だけ直し、目標尺のためには編集し直さない。
