# 完成監査

監査日: 2026-09-01

対象: `projects/2026-09-01-spacex-weekly`

## 要件別の証拠

| 要件 | 現物証拠 | 判定 |
|---|---|---|
| 短い自然言語依頼を制作依頼として扱う | ルート `AGENTS.md` の役割・既定フロー、`README.md` の利用例 | 合格 |
| Webリサーチと事実確認 | `research.md`、17件の `sources.json`、一次情報・報道・素材URL | 合格 |
| 台本とシーン設計 | `script.md`、11シーンの `project.json` | 合格 |
| VOICEVOX日本語ナレーション | VOICEVOX 0.25.2、話者30、12個の句WAVと `audio/narration.wav` | 合格 |
| 実音声尺を使う | `audio/timing.json` にffprobe実測70.106667秒、句・シーン開始終了時刻 | 合格 |
| 素材探索・比較・選定 | `assets/candidates/`、候補コンタクトシート、`assets/selected/`、出典・用途記録 | 合格 |
| ASS字幕 | `subtitles/subtitles.ass` 12件、Yu Gothic UI Semibold、58px、色・位置・縁取り指定 | 合格 |
| 必要部分だけRemotion | オープニング、数値カード、結論のソースとレンダリングクリップ | 合格 |
| FFmpeg編集・プレビュー・完成動画 | `output/preview.mp4`、`output/final.mp4` | 合格 |
| 60〜90秒PoC | 完成MP4実測70.133333秒 | 合格 |
| 1080p完成版 | 1920x1080、30fps、H.264、AAC 48kHz | 合格 |
| 低負荷QAと必要時だけ修正 | 全11シーンの中間フレームと `qa/scene-contact-sheet.jpg`。重複図解、シーンずれを検出して各1回修正 | 合格 |
| 黒画面・欠損・無音確認 | FFmpegデコードエラー0、blackdetect 0件、silencedetect 0件 | 合格 |
| 音量確認 | -15.18 LUFS、true peak -1.29 dBTP | 合格 |
| OpenTimelineIO | `timeline/edit.otio`、V1/A1/A2、11マーカー、素材尺超過0、欠落0 | 合格 |
| Kdenlive編集可能性 | Kdenlive 26.04.3でOTIOとASSを実インポート。`edit.kdenlive` をKdenlive自身で保存し、直接再オープン確認 | 合格 |
| 字幕編集可能性 | Kdenlive生成 `edit.kdenlive.ass` に12件、フォント・サイズ・色・位置スタイル保持 | 合格 |
| 素材・音声・BGMの分離 | Kdenlive V1 Visuals、A1 Narration、A2 BGM。参照素材24件、欠落0 | 合格 |
| 公開警告 | `AGENTS.md`、`README.md`、レンダラー出力、`output/NOTICE.txt`、検証結果 | 合格 |
| Brave未設定でも継続 | `check_env.py` で未設定を許容し、Codex Web検索でPoCを完了 | 合格 |
| GUI・公開投稿・独自レンダラー等を作らない | 構成はAGENTS/style/薄い補助ツール/プロジェクト/必要部分のRemotionのみ。後日追加したYouTube納品も非公開固定 | 合格 |

## 監査中に検出して修正した問題

1. 8秒の結論クリップをOTIOで約9.96秒参照していた。素材尺内で分割・反復するよう修正し、全OTIOクリップを範囲検証するようにした。
2. 中間シーンクリップの再利用で、シーン分割後も古い12.1秒クリップが残り、後半映像が1シーンずれた。既定で全シーンを再生成し、中間尺も検証するようにした。
3. Kdenlive 26.04.3がOTIO内の `file:///` URIを相対文字列として扱い、画像を開けなかった。OTIOの素材参照をタイムライン基準の相対パスへ変更し、実インポートでエラー0を確認した。

## 最終ゲート

- `tools/check_env.py`: `ready: true`
- `tools/validate_project.py`: `passed: true`、`errors: []`
- Python compileall: 成功
- Remotion npm audit: 既知の脆弱性0件
- Kdenliveネイティブプロジェクト再オープン: エラー0件

結論: 最初のPoCと、その制作に必要な最小環境は完成条件を満たす。
