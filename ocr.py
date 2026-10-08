# -*- coding: utf-8 -*-
"""OCRエンジン

優先順:
  1. Windows 標準OCR（Windows.Media.Ocr）… 軽量・高速・日本語対応。配布版はこれを使う
  2. RapidOCR / EasyOCR … Windows OCR が使えない環境向けの予備（開発・検証用）

どのエンジンも recognize(画像BGR) -> [Line] を返す。座標は渡した画像の座標系。
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def h(self):
        return self.y1 - self.y0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2

    def scaled(self, k, dx=0.0, dy=0.0):
        return Line(self.text, self.x0 * k + dx, self.y0 * k + dy, self.x1 * k + dx, self.y1 * k + dy)


# 本当の空白か、OCRが1語を割っただけかの境目。
# 実測では本物の空白が字高の0.39〜0.78倍、誤分割は0.20倍以下で分かれる
SPACE_GAP = 0.30


def _join_words(words):
    """単語をつないで1行にする。

    英数字どうしでも、字の間隔が狭ければ空白を入れない。
    Windows OCR は小さい文字で不自然な割り方をすることがあり、そのまま空白を入れると名前が変わってしまうため。
    """
    out = ""
    prev = None
    for w in words:
        r = w.bounding_rect
        if out and out[-1].isascii() and w.text[:1].isascii():
            gap = r.x - (prev.x + prev.width)
            if gap > SPACE_GAP * max(prev.height, r.height, 1):
                out += " "
        out += w.text
        prev = r
    return out


class WindowsOcr:
    name = "Windows OCR"

    def __init__(self, lang="ja"):
        import asyncio
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        engine = None
        if OcrEngine.is_language_supported(Language(lang)):
            engine = OcrEngine.try_create_from_language(Language(lang))
        if engine is None:
            engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise RuntimeError("Windows OCR の言語データが見つかりません")
        self.engine = engine
        self.max_dim = int(OcrEngine.max_image_dimension or 2600)
        self.loop = asyncio.new_event_loop()

    def _bitmap(self, bgra):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        h, w = bgra.shape[:2]
        dw = DataWriter()
        data = np.ascontiguousarray(bgra).tobytes()
        try:
            dw.write_bytes(data)
        except TypeError:
            dw.write_bytes(list(data))
        return SoftwareBitmap.create_copy_from_buffer(dw.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)

    async def _recognize(self, bmp):
        return await self.engine.recognize_async(bmp)

    def recognize(self, img):
        h, w = img.shape[:2]
        k = 1.0
        if max(h, w) > self.max_dim:
            k = self.max_dim / max(h, w)
            img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        bmp = self._bitmap(cv2.cvtColor(img, cv2.COLOR_BGR2BGRA))
        result = self.loop.run_until_complete(self._recognize(bmp))
        lines = []
        for ln in result.lines:
            words = list(ln.words)
            if not words:
                continue
            rects = [wd.bounding_rect for wd in words]
            x0 = min(r.x for r in rects)
            y0 = min(r.y for r in rects)
            x1 = max(r.x + r.width for r in rects)
            y1 = max(r.y + r.height for r in rects)
            text = _join_words(words)
            lines.append(Line(text, x0 / k, y0 / k, x1 / k, y1 / k))
        return lines


class _BoxOcr:
    """四角形の枠を返す系エンジン（RapidOCR / EasyOCR）の共通処理"""
    max_dim = 4000

    @staticmethod
    def _to_lines(items):
        lines = []
        for box, text, conf in items:
            text = (text or "").strip()
            if not text or conf < 0.3:
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            lines.append(Line(text, min(xs), min(ys), max(xs), max(ys)))
        return lines


class RapidOcr(_BoxOcr):
    name = "RapidOCR"

    def __init__(self):
        from rapidocr_onnxruntime import RapidOCR
        self.engine = RapidOCR()

    def recognize(self, img):
        res, _ = self.engine(img)
        return self._to_lines([(b, t, float(c)) for b, t, c in (res or [])])


class EasyOcr(_BoxOcr):
    name = "EasyOCR"

    def __init__(self):
        import easyocr
        self.engine = easyocr.Reader(["ja", "en"], gpu=True, verbose=False)

    def recognize(self, img):
        return self._to_lines(self.engine.readtext(img, detail=1))


def create_engine():
    errors = []
    for cls in (WindowsOcr, RapidOcr, EasyOcr):
        try:
            return cls()
        except Exception as e:
            errors.append(f"{cls.name}: {e}")
    raise RuntimeError("使えるOCRエンジンがありません\n" + "\n".join(errors))
