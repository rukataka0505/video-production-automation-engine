# YouTube解説動画制作環境

Codexへの自然言語の依頼から、調査、構成、VOICEVOXナレーション、素材選定、ASS字幕、FFmpeg編集、完成動画、Kdenlive用OTIO、YouTubeへの非公開アップロードまで行うローカル作業環境です。制作判断はCodex、実処理は現在のOSS基盤と既存ツールが担当します。

## 使い方

このフォルダをCodexで開き、例えば次のように依頼します。

```text
SpaceXの直近7日間の重要ニュースで動画作って
```

尺や表現を変えたい時は「3分で」「ニュース番組っぽく」「Starship中心」「字幕を大きめに」などを加えます。掛け合い形式は次のように指定します。

```text
量子コンピューターについて、3分の掛け合いの動画を作って
```

Codexは構成、ナレーション、shot、納品設定を `project.json` に保存し、その内容をそのまま承認用に提示します。

個人利用の案件では素材の出典、権利、ライセンス記録を制作必須条件にしません。公開、配布、商用利用する場合は用途に合う利用条件を確認してください。

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

## YouTube非公開アップロードの準備

Google CloudでYouTube Data API v3を有効にし、OAuthクライアントの種類を「テレビと入力が限られたデバイス」にします。ダウンロードしたJSONは次のコマンドでリポジトリ外のローカル設定へコピーします。JSONやトークンをこのリポジトリへ置かないでください。

```powershell
.\.venv\Scripts\python.exe .\tools\upload_youtube.py --install-client-secrets "$env:USERPROFILE\Downloads\client_secret_....json" --auth-only
```

初回とrefresh token失効時には端末に認証URLとコードが表示されます。新しい認証後のrefresh tokenはWindows DPAPIで現在のWindowsユーザーだけが復号できる形にして、既定では `%LOCALAPPDATA%\VideoAutomationEngine\youtube-oauth-token.json` に保存します。

クライアント情報をファイルに保存しない場合は `YOUTUBE_CLIENT_ID` と `YOUTUBE_CLIENT_SECRET` の両方を環境変数で渡せます。JSONの別パスは `YOUTUBE_CLIENT_SECRETS_FILE`、トークンの別パスは `YOUTUBE_TOKEN_FILE` で指定できます。

完成動画名は `project.json` の `delivery.filename` で指定できます。未指定時はタイトルから生成します。YouTube設定を変える場合は次を追加します。公開状態はアップローダーが常に `private` に固定します。

```json
"youtube": {
  "title": "動画タイトル",
  "description": "概要欄",
  "tags": ["解説", "ニュース"],
  "category_id": "22",
  "made_for_kids": false
}
```

## プロジェクト成果物

各動画は `projects/<日付>-<slug>/` に保存します。

```text
project.json              構成、シーン、shot、ナレーション、納品設定の正本
assets/selected/          採用素材
audio/segments/           句単位のVOICEVOX音声
audio/narration.wav       全体ナレーション
audio/timing.json         ffprobe実測タイミング
subtitles/subtitles.ass   編集可能な字幕
graphics/                 必要時のRemotion等のソースと完成クリップ
timeline/edit.otio        Kdenliveへ渡す編集タイムライン
timeline/edit.kdenlive    明示的に要求された場合のネイティブ編集プロジェクト
output/preview.mp4        プレビュー
output/<納品ファイル名>.mp4 完成動画
output/youtube-upload.json YouTube側の動画ID、非公開状態、処理結果
```

`work/scene-rendering.json` と `work/scenes` はレンダー内部のキャッシュと再利用管理に使います。成果物や完成条件ではありません。

各sceneは `shots` を持ち、各shotに `path` と `type`、必要に応じて `source_start`、`duration_seconds`、`motion` を指定します。未指定のshot尺はVOICEVOXの実測シーン尺から配分されます。案件固有値は `project.json`、字幕、音声、映像、編集のグローバル既定値は `style.json` に置きます。

## 制作コマンド

```powershell
.\.venv\Scripts\python.exe .\tools\voicevox_synthesize.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\build_ass.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\render_video.py .\projects\<project> --quality preview
.\.venv\Scripts\python.exe .\tools\build_timeline.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\render_video.py .\projects\<project> --quality final
.\.venv\Scripts\python.exe .\tools\validate_project.py .\projects\<project>
.\.venv\Scripts\python.exe .\tools\finalize_project.py .\projects\<project>
```

映像確認に役立つ時だけ、次の任意ツールで代表フレームとコンタクトシートを作れます。

```powershell
.\.venv\Scripts\python.exe .\tools\extract_qa_frames.py .\projects\<project>\output\preview.mp4
```

validatorは、完成動画、`project.json`、必須shot素材、ASS字幕、`audio/timing.json` と参照WAV、OTIOが実際に利用できることを確認します。推奨値、任意メタデータ、QA画像、レンダーキャッシュは検証対象にしません。

静止画は既定では動かしません。必要なshotだけ `motion` に `zoom_in`、`zoom_out`、`pan_left`、`pan_right`、`pan_up`、`pan_down` を指定できます。動きはKdenliveと同じMLT `qtblend` Transformで処理します。実写動画は自動ループせず、素材尺が足りなければ別shotへ切り替えます。

Remotionは図解やオープニングが必要な時だけ使います。

## Kdenliveで編集する

「ファイル → OpenTimelineIOをインポート」から `timeline/edit.otio` を読み込み、字幕メニューから `subtitles/subtitles.ass` をインポートします。映像、句単位のナレーション、BGMは別トラックなので、素材差し替え、カット、字幕、BGM、音量、シーン順を編集できます。ネイティブプロジェクトが必要な場合はKdenlive自身で `.kdenlive` として保存してください。

## GitHubバックアップ

`projects/` はGit管理から完全に除外します。Codexが制作システムを改善した時は、検証後にシステム変更だけを `origin/main` へコミット、pushします。動画制作だけを行った時はGitHubへpushしません。
