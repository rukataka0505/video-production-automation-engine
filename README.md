# Codex動画制作エンジン

Codexが調査・脚本・素材・演出を判断し、ローカルのVOICEVOXとRemotionで動画にする。編集は台本や素材を修正して再生成する。

## セットアップ

必要なのはPython 3.13、Node.js、FFmpeg/ffprobe、VOICEVOX。Python側は標準ライブラリだけを使う。

```powershell
py -3.13 -m venv .venv
Push-Location remotion
npm.cmd ci
Pop-Location
powershell -ExecutionPolicy Bypass -File tools/start_voicevox.ps1
.\.venv\Scripts\python.exe tools/install_dialogue_characters.py
.\.venv\Scripts\python.exe tools/video.py check
```

実行ファイルがPATHにない場合も標準のWindowsインストール先を探索する。`VIDEO_FFMPEG`、`VIDEO_FFPROBE`、`VOICEVOX_ENGINE`、`VOICEVOX_URL`で接続先を指定できる。既定のVOICEVOXは`http://127.0.0.1:50021`。

## 制作の流れ

「○○の動画を作って」とCodexへ依頼する。調査・台本・映像方針・声・タイトル・サムネイル案を確認し、承認後に素材取得・音声生成・編集・検査・非公開納品へ進む。「確認不要」で承認待ちを省略できる。

声の指定がなければずんだもん。掛け合いで配役未指定なら、ずんだもんが説明、めたんが視聴者目線の疑問・反論を担当する。声の一覧は`video.py check --voices`で取得する。

ずんだもん・めたんの声は、一人語りでも発話中だけ固定の立ち絵を表示する。音声スタイルを変更してもキャラは同じ。それ以外の声と発話間の無音では表示しない。位置・サイズは`style.json`の共通設定で決まり、案件ごとに変更しない。

## コマンド

```powershell
.\.venv\Scripts\python.exe tools/video.py check projects/<案件>
.\.venv\Scripts\python.exe tools/video.py build projects/<案件> --quality preview
.\.venv\Scripts\python.exe tools/video.py wait projects/<案件> --timeout 55
.\.venv\Scripts\python.exe tools/video.py inspect projects/<案件> --at 5
.\.venv\Scripts\python.exe tools/video.py inspect projects/<案件> --at 5 --duration 3
.\.venv\Scripts\python.exe tools/video.py build projects/<案件> --quality final
.\.venv\Scripts\python.exe tools/video.py wait projects/<案件>
.\.venv\Scripts\python.exe tools/video.py deliver projects/<案件>
```

`build`はバックグラウンド実行。`status`/`wait`は短い状態だけを返す。実行中に同じ案件をbuildしても二重起動しない。中断や失敗後は原因を直して同じbuildを実行する。詳細ログは`work/job.log`にある。

音声は本文・声・音声設定・VOICEVOXバージョンで再利用する。映像は毎回全体をレンダーする。プレビューは半分の解像度、完成版は指定解像度。既定は1920×1080、30fps。対応画面比率は16:9と9:16。

## YouTube Shorts

「○○のShortsを作って」と依頼する。構成・編集の共通Skillに加えて [shorts Skill](.agents/skills/shorts/SKILL.md) を使う。通常動画の制作方針と承認手順は共通。

project.jsonに `"video": {"width": 1080, "height": 1920, "fps": 30}` を指定するだけで、同じRemotion・VOICEVOX・CLIを使い、完成版1080×1920、プレビュー540×960を出力する。省略時は従来の1920×1080。縦動画の字幕と立ち絵はstyle.jsonのportraitから共通設定を適用し、比較・図解を上下並びにする。縦のtextは図解と同じ安全領域内、media・focus・customは全画面。customは縦画面用の配置を案件内で設計する。

Shortsは完成実尺3分以内に構成する。縦レイアウト自体は長尺でも使用でき、尺で映像を自動カットしない。納品時のShorts分類はYouTube側が行う。thumbnail.jpgは通常1080×1920で作り、既存のサムネイルAPI結果まで確認する。

## 入力形式

案件は`projects/<日付>-<slug>/`に置く。`project.json`が台本・編集指定の正本。旧形式の読み込みや自動移行は行わない。

```json
{
  "title": "往復の平均速度は、なぜ45キロではない？",
  "voices": {"zunda": {"style_id": 3}, "metan": {"style_id": 2}},
  "thumbnail": {"concept": "平均の意外性", "text": "45じゃない！"},
  "beats": [{
    "id": "question",
    "title": "同じ距離を往復すると？",
    "lines": [
      {"id": "q1", "voice": "zunda", "text": "行きは時速六十キロ。帰りは三十キロなのだ。", "gap": 0.3},
      {"id": "q2", "voice": "metan", "text": "平均は四十五キロ、じゃないの？", "gap": 0.6}
    ],
    "visuals": [
      {"kind": "compare", "items": [{"label": "行き", "value": "60 km/h"}, {"label": "帰り", "value": "30 km/h"}]},
      {"kind": "focus", "text": "同じ距離", "from": {"line": "q2"}, "rect": [2, 10, 96, 70]}
    ]
  }]
}
```

- `voices`省略時は`narrator: {style_id: 3}`。1音声なら発話の`voice`を省略できる。複数音声では各発話に指定する。
- `voices.<名前>.settings`と発話の`settings`はVOICEVOX AudioQueryの数値設定。共通設定→声設定→発話設定の順に適用する。例：`{"speedScale": 1.05, "intonationScale": 1.1}`。
- beatと発話の`id`は全体で一意の英数字・ハイフン・下線。台詞の修正時にIDを変える必要はない。
- `gap`は発話後の無音秒数。既定0.3秒。beatの尺は音声実尺＋間から確定する。`duration`を指定すれば余韻を延長でき、無言のbeatでは必須。
- `from`/`to`はbeat先頭からの秒数、または`{"line":"q2","edge":"end","offset":0.2}`。edgeはstart/end、offsetは秒数。参照できるのは同じbeatの発話。from省略はbeat先頭、to省略はbeat末尾。
- 全文字幕は発話本文から自動生成する。改行と表示区間の分割だけを変え、字幕原稿を別に書かない。長いセリフは字幕と理解のため短い発話へ分ける。
- `video`でwidth/height/fps、`delivery.filename`でMP4名を指定できる。未指定ファイル名はタイトルから生成する。

### 映像

visualsの順序が重なり順。表示時間内の要素だけを描画する。通常の画像・動画は横1920×1080、縦1080×1920全面を基準にcoverで表示し、見出し・字幕・立ち絵はその上へ重ねる。compareとdiagramは字幕・立ち絵を避けた安全領域へ配置する。縦動画ではtextも同じ領域を使う。

| kind | 指定 |
|---|---|
| media | `path`、任意の`source_start`（秒）、`fit: contain/cover`（既定cover）。動画音声はミュート。短い動画は自動ループしない |
| compare | `items`を2つ。各項目に`label`、`value`、任意の`detail`と画像`path` |
| diagram | `nodes`に`text`、任意の`detail`と`at`。atはfrom/toと同じ時刻形式。横動画は横並び、縦動画は上下並びと矢印で順に出す |
| text | `text`、任意の`size`と`color`。改行可能 |
| focus | `text`、任意の`rect: [左, 上, 幅, 高さ]`（映像領域の百分率）と`color` |
| custom | 案件直下の`visuals.tsx`を描画。任意の`props`を渡す |

特殊な図は案件内で標準のReact/SVG/Remotionを使う。`visuals.tsx`はdefault exportのReactコンポーネントとし、`frame`（当該演出の開始からのフレーム）、`fps`、`data`（props）、`lineTimes`（同じ演出開始を原点とする発話のfrom/toフレーム）、`asset(path)`（案件内素材URL）を受け取る。フレームだけで決まる描画にし、壁時計・非決定的乱数・レンダー中の外部取得は使わない。台詞と時間表を重複記載しない。

### 音

beatの`audio`に素材と区間を指定する。

```json
{"path":"assets/music.wav","volume":0.12,"loop":true,"duck":true,"fade_in":0.5,"fade_out":0.8}
```

from/toは映像と同じ。`source_start`、`fade_in`、`fade_out`は秒。`volume`は倍率。`loop`と`duck`は省略時false。duckは発話前後に滑らかにBGMを下げ、無音時に戻す。SEは必要な短い区間だけ置く。音の配置とミックスはRemotionが担当する。FFmpegは素材変換・ラウドネス補正・検査に使う。完成ミックスは約−16 LUFS、true peak −1.5 dBを目標に補正し、映像ストリームはコピーする。映像の再描画・別系統の音声ミックスは行わない。

## 保存するもの

- `project.json`、使用素材、必要な調査メモ、特殊図解のソース
- `output/<タイトル>.mp4`、`output/thumbnail.jpg`
- `output/final-validation.json`、納品時の`output/youtube-upload.json`

`work/`は発話音声・AudioQuery・時間表・バンドル・ジョブ状態などの再生成可能な作業データ。編集は上記のソースを直し、再buildする。OTIO、ASS、Kdenliveプロジェクトは作らない。

サムネイルは既存の画像生成・画像処理ツールで作り、横は幅640px以上・16:9、縦は高さ640px以上・9:16のJPEGを保存する。エンジン専用のサムネイル描画基盤は持たない。

## 非公開納品

認証情報はリポジトリ外、トークンはWindows DPAPIで保護する。既存の認証を継続利用できる。

```powershell
.\.venv\Scripts\python.exe tools/upload_youtube.py --install-client-secrets "<OAuthクライアントJSON>" --auth-only
```

deliverは現在の台本・完成動画と検証記録の一致、サムネイルを確認する。動画本体が同じなら再投稿せず、変更されたサムネイルだけを設定する。YouTubeのprivateとprocessingStatus=succeeded、サムネイルAPI成功を確認して納品完了とする。

## 検証とバックアップ

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
Push-Location remotion
npm.cmd run typecheck
npm.cmd test
Pop-Location
```

テストに加えて実動画をレンダーし、必要なフレームと短い区間で読みやすさ・同期・説明との一致を確認する。素材の権利台帳や視聴分析は制作必須条件にしない。

システム変更だけを検証後にmainへコミットし、origin/mainへpushする。`projects/`、生成素材、認証情報はGit管理しない。
