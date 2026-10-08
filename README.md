# AC6 Stamp

ARMORED CORE VI の対戦録画から、**対戦開始のタイムスタンプ**と**対戦相手の名前**を読み取り、
YouTube のコメント欄にそのまま貼れる一覧を作る Windows 用ツールです。

```txt
0:08 vs ALL MIND
6:42 vs Ayre
```

- ダウンロードと使い方: GitHub Pages のページ（`https://<owner>.github.io/<repo>/`）
- 利用者向けの説明: [docs/使い方.txt](docs/使い方.txt)

## しくみ

1. ffmpeg で録画を1秒に1コマずつ取り出す
2. 画面下部を Windows 標準OCR で読み、「UNIT ALPHA / UNIT BETA」の文字を探す
3. 見つかったラベルの位置から名前欄の位置を割り出し、パイロット名・AC名・IDを読む
4. 近い時刻の検出をまとめて1試合とし、最初の検出時刻をタイムスタンプにする
5. 自分の名前（設定値、または7割以上の試合に出てくる名前）を除いた名前を対戦相手とする

自動で位置を割り出せない環境向けに、位置を手動で指定するモードもあります（画面の「読み取り位置の調整…」）。

ffmpeg は**同梱していません**（よく使われる配布用ビルドが GPLv3 のため）。
利用者が入れた ffmpeg を `PATH` →`AC6Stamp.exe` と同じフォルダ→`imageio-ffmpeg`（開発環境）の順に探します。
案内は `winget install Gyan.FFmpeg`。詳細は [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## OBS 連携

  OBS の「ツール」→「スクリプト」→「＋」で"ac6stamp_obs.lua"ファイルを追加し、
 「AC6Stamp.exe の場所」を指定してください。

## ローカルの動画ファイルのみ解析対象

YouTube の URL からは解析できません。
YouTube の利用規約 5.1(H) は、再生ページ・埋め込みプレーヤー・YouTube が明示的に許可した手段
以外でのコンテンツ取得を禁止しています。

アップロード済みの自分の動画を解析したい場合は、公式のダウンロード経路でファイルを取得してから
本ツールに渡してください。

| 経路 | 画質 | 制限 |
| --- | --- | --- |
| [Google Takeout](https://takeout.google.com/) | アップロードした元ファイルそのまま（無変換、または H264/AAC の MP4） | 書き出しに時間がかかる・チャンネル一括 |
| [YouTube Studio](https://studio.youtube.com/) の「ダウンロード」 | **720p または 360p のみ** | 1本につき24時間で5回まで |

OCR 精度の点では Takeout を推奨します。解像度が足りないと、うまく読み取れないことがあります。

| ファイル | 内容 |
| --- | --- |
| `app.py` | 起動用 |
| `gui.py` | メイン画面・読み取り位置の調整画面・`--selftest` |
| `core.py` | 動画の読み込み、パネル検出、集計 |
| `ocr.py` | OCRエンジン（Windows OCR / 予備として RapidOCR・EasyOCR） |
| `config.py` | 設定（`%APPDATA%\AC6Stamp\config.json`） |
| `obs/ac6stamp_obs.lua` | OBS 連携スクリプト（録画停止で自動解析） |
| `docs/` | GitHub Pages のダウンロードページ |
| `THIRD-PARTY-NOTICES.md` | 同梱している第三者ソフトウェアのライセンス表示 |

## 開発

```bash
pip install -r requirements.txt
python app.py
```

Windows 以外では Windows OCR が使えないため、`pip install rapidocr_onnxruntime` を入れると代わりに使われます。

コマンドライン引数:

- `AC6Stamp.exe 動画1 動画2 ...` … 動画を追加した状態で起動
- `--auto-run` … 起動後すぐ解析（OBS 連携で使用）
- `--selftest 結果.txt` … OCR と ffmpeg の動作確認だけして終了（CI で使用）

## リリース

GitHub Actions（`.github/workflows/build.yml`）が Windows 上で exe を作り、`--selftest` で動作確認します。

- `main` への push … ビルドと確認のみ（Actions の Artifacts から zip を取得可）
- `v1.0.0` のようなタグを push … Release を作成し `AC6Stamp-win64.zip` を添付

```bash
git tag v1.0.0
git push origin v1.0.0
```

ダウンロードページは `docs/` を `.github/workflows/pages.yml` が GitHub Pages に公開します。
ページのボタンは常に最新の Release の zip を指します。

## ライセンス

MIT License（[LICENSE](LICENSE)）。同梱物の表示は [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) です。

---

非公式のファンメイドツールです。株式会社フロム・ソフトウェア、株式会社バンダイナムコエンターテインメントとは関係ありません。
ARMORED CORE VI 関連の名称・画面・意匠の権利は両社に帰属し、MIT License は及びません。
