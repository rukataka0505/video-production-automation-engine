# YouTube解説動画制作環境

Codexへ短い自然言語で依頼し、調査、台本、VOICEVOXナレーション、素材選定、ASS字幕、FFmpeg編集、簡易QA、完成動画、Kdenlive用OTIO、YouTubeへの非公開アップロードまで行うローカル作業環境です。制作判断はCodex、実処理は既存ツールが担当します。一般公開・限定公開への自動投稿機能とGUIはありません。

## 使い方

このフォルダをCodexで開き、例えば次のように依頼します。

```text
SpaceXの直近7日間の重要ニュースで動画作って
```

尺や表現を変えたい時だけ「3分で」「ニュース番組っぽく」「Starship中心」「字幕を大きめに」などを加えてください。リポジトリ直下の `AGENTS.md` をCodexが読み、必要な工程を最後まで進めます。

ずんだもんが解説し、四国めたんが視聴者目線で合いの手を入れる形式は、「掛け合いの動画」と指定します。ずんだもんの発言が続くことも、めたんが入らないシーンも許し、機械的な交互発話にはしません。字幕はずんだもんが緑、四国めたんが紫です。

```text
量子コンピューターについて、3分の掛け合いの動画を作って
```

PDF、スライド、報告書、論文、決算資料は主に情報源として調べます。文書や図表そのものを見せる意味がある場合だけ映像素材として採用します。個人利用の案件では権利関係や再利用ライセンスの明確さを採用の必須条件にしませんが、出典は記録し、公開・配布・商用利用時は別途確認します。

## 必要なソフト

- FFmpeg / ffprobe
- Kdenlive 26.04以降（OpenTimelineIOインポート対応、MLT `melt` 同梱）
- VOICEVOX 0.25系
- Python 3.13 と OpenTimelineIO 0.18.1
- Node.js（Remotionが必要な動画だけ）

Windowsでは次の構成を検証済みです。

```powershell
winget install --id Gyan.FFmpeg --exact
winget install --id KDE.Kdenlive --exact
winget install --id HiroshibaKazuyuki.VOICEVOX --exact
winget install --id Python.Python.3.13 --exact

py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\tools\start_voicevox.ps1
.\.venv\Scripts\python.exe .\tools\check_env.py
```

新しいPATHが反映されていないシェルでも、補助スクリプトはwingetの標準インストール先を探索します。VOICEVOX APIの既定URLは `http://127.0.0.1:50021` です。別URLは `VOICEVOX_URL`、実行ファイルは `VIDEO_FFMPEG`、`VIDEO_FFPROBE`、`KDENLIVE_PATH`、`MLT_MELT`、`VOICEVOX_ENGINE` で上書きできます。

`BRAVE_SEARCH_API_KEY` は任意です。未設定やエラー時は、Codex自身のWeb検索で制作を続けます。

## YouTube非公開アップロードの準備

Google CloudでYouTube Data API v3を有効にし、OAuthクライアントの種類を「テレビと入力が限られたデバイス」にします。ダウンロードしたJSONは、次のコマンドでリポジトリ外のローカル設定へコピーします。JSONやトークンをこのリポジトリへ置かないでください。

```powershell
.\.venv\Scripts\python.exe .\tools\upload_youtube.py --install-client-secrets "$env:USERPROFILE\Downloads\client_secret_....json" --auth-only
```

初回とrefresh token失効時には、端末に認証URLとコードが表示されます。スマホでURLを開いてコードを入力すると、処理が自動的に再開します。Google Auth Platformを「外部」「テスト中」で運用する場合、refresh tokenが約7日で失効する前提で構いません。新しい認証後のrefresh tokenはWindows DPAPIで現在のWindowsユーザーだけが復号できる形にして、既定では `%LOCALAPPDATA%\VideoAutomationEngine\youtube-oauth-token.json` に保存します。

クライアント情報をファイルに保存しない場合は、`YOUTUBE_CLIENT_ID` と `YOUTUBE_CLIENT_SECRET` の両方を環境変数で渡せます。JSONの別パスを使う場合は `YOUTUBE_CLIENT_SECRETS_FILE`、トークンの別パスは `YOUTUBE_TOKEN_FILE` で指定できます。秘密値やトークンはソースコード、`project.json`、アップロード結果へ記録しません。

完成動画には `final.mp4` を使わず、`project.json` の `delivery.filename` に案件ごとの内容が分かるタイトルを設定します。YouTubeのタイトル、概要、タグ、カテゴリ、子ども向け設定を変える場合は、プロジェクトに次を追加します。`privacyStatus` は設定を受け付けず、アップローダーが常に `private` に固定します。

```json
"youtube": {
  "title": "動画タイトル",
  "description": "概要欄",
  "tags": ["解説", "ニュース"],
  "category_id": "22",
  "made_for_kids": false
}
```

## プロジェクトの中身

各動画は `projects/<日付>-<slug>/` に保存します。

```text
project.json              シーン、shot、ナレーション、納品設定の正本
brief.md                  依頼と狙い
research.md               事実確認メモ
sources.json              research_sources / visual_assets / audio_assets
script.md                 必要な場合だけ作るproject.jsonの承認用ビュー
assets/selected/          採用素材
audio/segments/           句単位のVOICEVOX音声
audio/narration.wav       全体ナレーション
audio/timing.json         ffprobe実測タイミング
subtitles/subtitles.ass   編集可能な字幕
graphics/                 Remotion等のソースと完成クリップ
timeline/edit.otio        Kdenliveへ渡す編集タイムライン
timeline/edit.kdenlive    Kdenlive自身で保存したネイティブ編集プロジェクト（作成時）
timeline/edit.kdenlive.ass ネイティブプロジェクトの編集可能字幕（作成時）
output/preview.mp4        QA用プレビュー
output/<動画タイトル>.mp4  内容が分かる名前を付けた完成動画
output/youtube-upload.json YouTube側の動画ID・非公開状態・処理結果
work/scene-rendering.json 各シーンのレンダー方式とキャッシュ検証情報
qa/                       代表フレームと検証結果
```

新規プロジェクトは `scene.visual` ではなく `scene.shots` を使います。各shotに短い `visual_intent` を持たせ、必要なshotだけ `duration_seconds` を指定します。未指定分はVOICEVOXの実測シーン尺から配分されます。

## 補助コマンド

```powershell
.\.venv\Scripts\python.exe .\tools\voicevox_synthesize.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\build_ass.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\render_video.py .\projects\<project> --quality preview
.\.venv\Scripts\python.exe .\tools\extract_qa_frames.py .\projects\<project>\output\preview.mp4
.\.venv\Scripts\python.exe .\tools\build_timeline.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\render_video.py .\projects\<project> --quality final
.\.venv\Scripts\python.exe .\tools\validate_project.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\finalize_project.py .\projects\<project>
```

`finalize_project.py` は完成条件を再検証し、合格した `output/<動画タイトル>.mp4` だけを変換せずYouTubeへ非公開アップロードします。validatorは目標尺を参考情報として記録し、範囲外だけでは失敗させません。素材欠落、破損、音声・字幕・タイムラインの不整合を失敗条件にします。送信は再開可能なチャンク方式で、再実行時は既存のYouTube動画を再確認します。

Remotionは図解やオープニングが必要な時だけ準備します。

静止画は既定では動かしません。内容上必要なshotだけ `motion` に `zoom_in`、`zoom_out`、`pan_left`、`pan_right`、`pan_up`、`pan_down` を指定できます。動きはKdenliveと同じMLT `qtblend` Transformで処理し、FFmpeg `zoompan` は使用しません。実写動画は自動ループせず、素材尺が足りなければ別shotへ切り替えます。

```powershell
Set-Location .\remotion
npm install
npm run render -- NewsIntro ..\projects\<project>\graphics\intro.mp4 --props=..\projects\<project>\graphics\intro-props.json
```

## Kdenliveで編集する

`timeline/edit.kdenlive` があるプロジェクトは、そのファイルをKdenliveで直接開けます。ない場合は「ファイル → OpenTimelineIOをインポート」から `timeline/edit.otio` を読み込み、字幕メニューから `subtitles/subtitles.ass` をインポートします。映像、句単位のナレーション、BGMは別トラックになっているため、素材差し替え、カットと尺、字幕テキスト・色・位置、BGM、音量、シーン順を通常の編集操作で変更できます。読み込み後はKdenlive自身で `.kdenlive` として保存してください。

最初のSpaceX PoCはKdenlive 26.04.3でOTIOとASSを実際に読み込み、`timeline/edit.kdenlive` として保存後、直接開き直して素材・3トラック・字幕を確認済みです。

## 公開前の注意

この動画は個人利用を前提として生成されています。Web上から取得した画像・動画・音声等が含まれる可能性があります。YouTube、SNS、Web等で公開・配布・商用利用する場合は、使用素材の著作権・ライセンス・利用条件を確認してください。

## GitHubバックアップ

`projects/` はGit管理から完全に除外します。Codexが制作システムを改善したときは、検証後にシステム変更だけを `origin/main` へコミット・pushします。動画制作だけを行ったときはGitHubへpushしません。
