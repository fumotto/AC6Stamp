# AC6 Stamp

ARMORED CORE VI の対戦録画から、**対戦開始のタイムスタンプ**と**対戦相手の名前**を読み取り、
YouTube のコメント欄にそのまま貼れる一覧を作る Windows 用ツールです。

```
0:08 vs barracuda
6:42 vs esKen32
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

| ファイル | 内容 |
|---|---|
| `app.py` | 起動用 |
| `gui.py` | メイン画面・読み取り位置の調整画面・`--selftest` |
| `core.py` | 動画の読み込み、パネル検出、集計 |
| `ocr.py` | OCRエンジン（Windows OCR / 予備として RapidOCR・EasyOCR） |
| `config.py` | 設定（`%APPDATA%\AC6Stamp\config.json`） |
| `obs/ac6stamp_obs.lua` | OBS 連携スクリプト（録画停止で自動解析） |
| `docs/` | GitHub Pages のダウンロードページ |

## 開発

```
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

```
git tag v1.0.0
git push origin v1.0.0
```

ダウンロードページは `docs/` を `.github/workflows/pages.yml` が GitHub Pages に公開します。
ページのボタンは常に最新の Release の zip を指します。

初回のみ、リポジトリの Settings → Pages → Source を「GitHub Actions」にしてください。

---

非公式のファンメイドツールです。株式会社フロム・ソフトウェア、株式会社バンダイナムコエンターテインメントとは関係ありません。
