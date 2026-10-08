# 第三者ソフトウェアのライセンス表示

AC6 Stamp 本体は MIT License です（[LICENSE](LICENSE)）。
配布版（`AC6Stamp-win64.zip`）には下記のソフトウェアが含まれています。
いずれも許諾的（permissive）なライセンスで、原文は各プロジェクトの配布物に含まれています。

| ソフトウェア | 著作権者 | ライセンス |
| --- | --- | --- |
| Python / tkinter | Python Software Foundation | PSF License 2.0 |
| NumPy | NumPy Developers | BSD 3-Clause |
| OpenCV | OpenCV team | Apache License 2.0 |
| opencv-python（パッケージ） | Olli-Pekka Heinisuo | MIT |
| imageio-ffmpeg | imageio contributors | BSD 2-Clause |
| tkinterdnd2 | Michael Lange, Philippe Gagné | MIT |
| tkdnd | Georgios Petasis | BSD 3-Clause |
| PyWinRT（`winrt-*`） | Dave Hall / pywinrt contributors | MIT |
| PyInstaller（ブートローダー部分） | PyInstaller Development Team | GPL 2.0 with bootloader exception |

Windows の文字認識は OS の API（Windows.Media.Ocr）を呼んでいるだけで、
再頒布しているものはありません。

## FFmpeg について

AC6 Stamp は録画からコマを取り出すために **ffmpeg を外部プログラムとして呼び出します**が、
ffmpeg 自体は配布版に含めていません。利用者が自分で用意した ffmpeg を使います。

同梱していない理由は、よく使われている配布用ビルド（imageio-ffmpeg が同梱しているもの等）が
`--enable-gpl --enable-version3` でビルドされた GPLv3 のバイナリで、再頒布すると
対応ソースコードの提供義務（GPLv3 §6）が生じるためです。
AC6 Stamp 本体は ffmpeg と一切リンクせず、別プロセスとしてコマンドラインで呼ぶだけなので、
本体のライセンス（MIT）には影響しません。

ffmpeg の入手方法は [docs/使い方.txt](docs/使い方.txt) を参照してください。

## ゲーム内の著作物について

MIT License が及ぶのは AC6 Stamp のソースコードと同梱素材だけです。
ARMORED CORE VI および関連する名称・画面・意匠の権利は
株式会社フロム・ソフトウェアおよび株式会社バンダイナムコエンターテインメントに帰属します。
本ツールは非公式のファンメイドツールであり、両社とは関係ありません。
