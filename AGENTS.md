# 動画制作ルール

## 絶対ルール

- 「○○の動画を作って」は制作依頼として扱い、調査・構成・台本を自律的に作って承認を待つ。ユーザーが「確認不要」「最後まで進めて」と明示した場合だけ、承認待ちを省略する。
- 制作判断はCodex、実処理は既存のFFmpeg、ffprobe、VOICEVOX、ASS、OpenTimelineIO、Kdenlive、必要部分だけRemotionを使う。現在の基盤を作り直さず、独自編集ソフト、独自タイムライン、複数TTS、GUI、公開投稿機能を作らない。
- ユーザーの尺、対象、口調、素材、字幕指定を優先する。指定尺は目安であり、範囲外だけを理由に水増し、削減、再生成しない。
- ナレーションと字幕本文は同一にする。改行と表示タイミング上の分割だけを変えてよい。
- `project.json` をシーン、shot、ナレーション、納品設定の正本にする。`script.md` は必要な場合だけ作る派生ビューとし、別の正本にしない。
- `sources.json` では `research_sources`、`visual_assets`、`audio_assets` を分ける。PDF、論文、決算資料、スライド、報告書は主に情報源として扱い、文書自体を見せる意味がある場合だけ映像へ使う。
- 個人利用では権利の明確さを素材採用の必須条件にしないが、元URLと提供元を記録し、認証、DRM、有料制限、技術的制限を回避しない。公開・配布・商用利用時は用途に合う条件を確認する。
- 完成動画には内容を表す日本語ファイル名を付ける。YouTube納品は常に非公開とし、認証情報やトークンをソース、成果物、ログへ残さない。

## 承認ゲート

- `research.md`、`sources.json`、構成、`project.json` のナレーション、字幕・話者・映像方針が揃った時点で保存し、ユーザーへ提示する。
- 承認前はVOICEVOX音声生成、新規素材の取得、字幕生成、編集、レンダー、QA、納品を始めない。
- 承認後は保存済み成果物を引き継ぎ、修正指示のある部分だけ更新する。

## 全体フロー

1. `projects/<日付>-<slug>/` を作る。最新ニュースで期間指定がなければ、日本時間の依頼日までの直近7日間を対象にする。
2. 調査を始める時だけ `.agents/skills/research/SKILL.md` を読み、`research.md` と分類済み `sources.json` を作る。
3. 構成と台本を作る時だけ `.agents/skills/script/SKILL.md` を読み、`project.json` を作って承認を得る。
4. 承認後、映像設計と編集を始める時だけ `.agents/skills/visual-editing/SKILL.md` を読み、素材を選定する。
5. `tools/voicevox_synthesize.py` で音声を作り、ffprobe実測尺を `audio/timing.json` に記録する。`tools/build_ass.py` で同一本文のASS字幕を作る。
6. `tools/render_video.py` でプレビューを作り、`tools/extract_qa_frames.py` で代表フレームを確認する。問題が確認できた箇所だけ直す。
7. 最終動画を作り、`tools/build_timeline.py` で映像・ナレーション・BGMを分離したOTIOとASSを残す。必要指定がある時だけKdenlive自身で `timeline/edit.kdenlive` を保存する。
8. `tools/validate_project.py` で素材欠落、破損、字幕・音声・タイムラインの不整合を検証する。目標尺の範囲外は参考情報に留める。
9. 全体デコード検査済みの完成原本を `tools/finalize_project.py` でYouTubeへ非公開アップロードし、APIで動画ID、タイトル、非公開状態、処理完了を再確認する。再実行時は明示的な強制指定がない限り重複アップロードしない。

## 完了条件

- 正確で自然に視聴でき、映像と内容が合い、後から編集できる完成動画であること。
- `output/<動画タイトル>.mp4`、`subtitles/subtitles.ass`、`timeline/edit.otio`、`project.json`、`research.md`、`sources.json`、QA、検証結果、`output/youtube-upload.json` が揃い、実測した解像度・尺・音声、全体デコード、OTIO再読込、YouTubeの非公開状態と処理完了を確認できること。
- 完成報告にはローカル原本、確認済み非公開リンク、実尺と、次の警告を表示する。アップロード未完了時は原因と再開方法を示し、完了と扱わない。

> この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声・PDF・文書内の図表等が含まれる可能性があり、個人利用の制作では権利関係や再利用ライセンスが明確であることを素材採用の必須条件としていません。YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。
