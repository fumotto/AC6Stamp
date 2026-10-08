# -*- coding: utf-8 -*-
"""動画の読み込み・対戦開始パネルの検出・結果の集計"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np

import config
from ocr import Line

# 解析用の横幅。縮小しすぎると小さい文字がつぶれてOCRが化けるので、
# 1080p はそのまま、それより大きい動画だけここまで縮小する
WORK_W = 1920
# 1080p のとき何倍に拡大してOCRに渡すか（高さに応じて自動調整する）
OCR_SCALE = 4.0
# 自動モードでパネルの場所を探すときの倍率。画面下部をまるごと読むため、
# 大きくしすぎると薄い模様まで拾って名前に混ざるので控えめにする
FIND_SCALE = 0.75
NO_WINDOW = 0x08000000 if os.name == "nt" else 0   # ffmpegの黒い窓を出さない


# ================= ffmpeg =================

_ffmpeg = None


FFMPEG_NOT_FOUND = (
    "ffmpeg が見つかりません。\n\n"
    "録画を読むには ffmpeg が必要です（ライセンスの都合で同梱していません）。\n"
    "次のどれかで用意してください。\n\n"
    "・コマンドプロンプトで  winget install Gyan.FFmpeg\n"
    "・https://www.gyan.dev/ffmpeg/builds/ から入手し、\n"
    "  ffmpeg.exe を AC6Stamp.exe と同じフォルダに置く\n"
)


def ffmpeg_exe():
    """ffmpeg.exe を探す。PATH → exe と同じフォルダ → imageio-ffmpeg（開発環境）の順。"""
    global _ffmpeg
    if _ffmpeg:
        return _ffmpeg
    _ffmpeg = shutil.which("ffmpeg")
    if not _ffmpeg:
        here = Path(sys.executable if getattr(sys, "frozen", False) else __file__).parent
        cand = here / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if cand.is_file():
            _ffmpeg = str(cand)
    if not _ffmpeg:
        try:
            import imageio_ffmpeg
            _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    if not _ffmpeg:
        raise RuntimeError(FFMPEG_NOT_FOUND)
    return _ffmpeg


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, **kw)


@dataclass
class VideoInfo:
    duration: float
    width: int
    height: int

    @property
    def work_size(self):
        w = int(round(min(self.width, WORK_W) / 2) * 2)
        h = int(round(w * self.height / self.width / 2) * 2)
        return w, h


def probe(path) -> VideoInfo:
    err = _run([ffmpeg_exe(), "-hide_banner", "-i", str(path)]).stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    if not m:
        raise RuntimeError(f"動画として読み込めません: {path}")
    return VideoInfo(dur, int(m.group(1)), int(m.group(2)))


def iter_frames(path, info: VideoInfo, fps=1.0, start=0.0):
    w, h = info.work_size
    cmd = [ffmpeg_exe(), "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(path), "-vf", f"fps={fps},scale={w}:{h}",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    size = w * h * 3
    n = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield start + n / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            n += 1
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def grab_frame(path, info: VideoInfo, t):
    w, h = info.work_size
    out = _run([ffmpeg_exe(), "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(path),
                "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]).stdout
    if len(out) < w * h * 3:
        return None
    return np.frombuffer(out[:w * h * 3], np.uint8).reshape(h, w, 3)


# ================= 文字の比較 =================

def norm(s):
    return "".join(s.lower().split())


def similar(a, b, th=0.75):
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and SequenceMatcher(None, a, b).ratio() >= th


# OCRが読み違えやすい字を寄せる。見るのが UNIT / ALPHA / BETA だけなので強めでよい
# （'UNIT' はよく 'LJ NーT' や '凵NーT' と読まれる）
_FOLD = str.maketrans({"凵": "U", "日": "B", "口": "O", "ロ": "O",
                       "ー": "I", "一": "I", "|": "I", "l": "I", "!": "I", "0": "O"})


def label_text(text):
    """ラベルのOCR結果をA〜Zだけに整える（'LJ NーT ALPHA' -> 'UNITALPHA'）"""
    return re.sub(r"[^A-Z]", "", text.translate(_FOLD).upper().replace("LJ", "U"))


def looks_like_unit(text):
    """パネル上の「UNIT」かどうか"""
    t = label_text(text)
    return t == "UNIT" or (len(t) <= 6 and SequenceMatcher(None, t, "UNIT").ratio() >= 0.6)


def side_of_label(text, strict=False):
    """「UNIT ALPHA」「BETA」などのOCR結果からどちら側かを判定（1〜2文字の読み違いは許容）"""
    t = label_text(text).replace("UNIT", "")
    if not t:
        return None
    for side in ("ALPHA", "BETA"):
        if side in t:
            return side
    if len(t) > 7:
        return None
    sa = SequenceMatcher(None, t, "ALPHA").ratio()
    sb = SequenceMatcher(None, t, "BETA").ratio()
    th = 0.75 if strict else 0.6
    if max(sa, sb) < th or sa == sb:
        return None
    return "ALPHA" if sa > sb else "BETA"


def clean_line(text):
    """行頭のアイコン由来の1文字ゴミ（例: 'A LandWhale-002'）を除く"""
    parts = text.split()
    if len(parts) >= 2 and len(parts[0]) == 1:
        parts = parts[1:]
    return " ".join(parts).strip()


# ================= パネル検出 =================

@dataclass
class Panel:
    side: str
    pilot: str
    ac: str = ""
    pid: str = ""
    label_box: tuple = ()      # 作業画像上のピクセル座標 (x0, y0, x1, y1)
    info_box: tuple = ()


def _union(lines):
    return (min(l.x0 for l in lines), min(l.y0 for l in lines),
            max(l.x1 for l in lines), max(l.y1 for l in lines))


# 同じ行でもこれ以上離れていれば別の欄とみなす（字高に対する倍率）。
# 実測では名前欄の断片は離れず、戦績欄など別の欄は2.3倍以上あいている
COL_GAP = 1.5


def _same_column(row):
    """1つの欄だけを残す。枠が広すぎて右の戦績欄まで入ったときに名前と混ざらないように"""
    cols = [[row[0]]]
    for prev, ln in zip(row, row[1:]):
        if ln.x0 - prev.x1 > COL_GAP * max(ln.h, prev.h, 1):
            cols.append([ln])
        else:
            cols[-1].append(ln)
    # 左端はアイコン由来の1文字ゴミのことがあるので、中身のある最初の欄を採る
    for c in cols:
        if len("".join(l.text for l in c)) >= 2:
            return c
    return cols[0]


def _merge_rows(lines):
    """同じ高さにある断片を1行にまとめ、上から順に並べる"""
    rows = []
    for ln in sorted(lines, key=lambda l: l.cy):
        if rows and abs(ln.cy - rows[-1][-1].cy) < max(ln.h, rows[-1][-1].h) * 0.6:
            rows[-1].append(ln)
        else:
            rows.append([ln])
    out = []
    for r in rows:
        r.sort(key=lambda l: l.x0)
        r = _same_column(r)
        text = clean_line(" ".join(l.text for l in r))
        if len(text) >= 2:
            out.append((text, r))
    return out


def _panel_from_rows(side, rows, label_box):
    if not rows:
        return None
    texts = [t for t, _ in rows]
    all_lines = [l for _, r in rows for l in r]
    return Panel(side=side, pilot=texts[0],
                 ac=texts[1] if len(texts) > 1 else "",
                 pid=texts[-1] if len(texts) > 2 else "",
                 label_box=tuple(label_box), info_box=_union(all_lines))


def parse_panels(lines):
    """画面下部のOCR結果から ALPHA/BETA パネルを探す（自動モード）"""
    panels = []
    for lab in lines:
        side = side_of_label(lab.text, strict=True)
        if not side:
            continue
        h = max(lab.h, 4)
        # ラベルの「UNIT」（同じ行か、すぐ上の行）
        has_unit = "UNIT" in label_text(lab.text)
        unit_top = lab.y0 - 1.3 * h
        for u in lines:
            if u is lab:
                continue
            if looks_like_unit(u.text) and lab.y0 - 2.5 * h <= u.y0 <= lab.y0 \
                    and abs((u.x0 + u.x1) / 2 - (lab.x0 + lab.x1) / 2) < (lab.x1 - lab.x0):
                has_unit = True
                unit_top = u.y0
        top, bottom = unit_top - 0.6 * h, lab.y1 + 0.6 * h
        if side == "BETA":      # 左下のパネル: 名前はラベルの右側
            xmin, xmax = lab.x1 + 1.5 * h, lab.x1 + 30 * h
        else:                   # 右下のパネル: 名前はラベルの左側
            xmin, xmax = lab.x0 - 30 * h, lab.x0 - 0.5 * h
        cand = [l for l in lines
                if l is not lab and not looks_like_unit(l.text)
                and l.cy >= top and l.cy <= bottom and l.x0 >= xmin and l.x1 <= xmax]
        rows = _merge_rows(cand)
        # 「UNIT」が読めなかったときは、名前と機体名が2行そろっていれば本物とみなす
        if not has_unit and len(rows) < 2:
            continue
        p = _panel_from_rows(side, rows, (lab.x0, unit_top, lab.x1, lab.y1))
        if p:
            panels.append(p)
    return panels


def _px_box(frame, rel):
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = rel
    return int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)


def looks_like_panel(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark, white = (g < 90).mean(), (g > 180).mean()
    return dark > 0.20 and 0.005 < white < 0.50


class Detector:
    def __init__(self, cfg, engine):
        self.cfg = cfg
        self.ocr = engine

    def _scale(self, frame):
        """1080p のとき OCR_SCALE 倍になる拡大率。映像が小さいほど大きく引き伸ばす"""
        return max(1.0, OCR_SCALE * 1080 / max(frame.shape[0], 1))

    def _ocr(self, img, k):
        k = min(k, self.ocr.max_dim / max(img.shape[:2]))
        if k <= 1:
            return self.ocr.recognize(img)
        # 文字の輪郭を保つため LANCZOS4（CUBIC より誤読が減ることを実測で確認）
        big = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4)
        return [l.scaled(1 / k) for l in self.ocr.recognize(big)]

    def detect(self, frame):
        if self.cfg.get("mode") == "manual":
            return self._detect_manual(frame)
        return self._detect_auto(frame)

    def _detect_auto(self, frame):
        h = frame.shape[0]
        y0, y1 = int(self.cfg["band"][0] * h), int(self.cfg["band"][1] * h)
        w = frame.shape[1]
        # パネルは左下と右下にあるので、左右の半分ずつを拡大して読む
        panels = {}
        for xa, xb in ((0, int(w * 0.55)), (int(w * 0.45), w)):
            part = frame[y0:y1, xa:xb]
            lines = [l.scaled(1, xa, y0) for l in self._ocr(part, self._scale(frame) * FIND_SCALE)]
            for p in parse_panels(lines):
                panels.setdefault(p.side, p)
        return [self._reread(frame, p) for p in panels.values()]

    def _reread(self, frame, panel):
        """見つかった名前のところだけを狭く切り直し、手動モードと同じ倍率で読み直す"""
        h, w = frame.shape[:2]
        x0, y0, x1, y1 = panel.info_box
        m = 0.3 * max(y1 - y0, 1)
        box = (max(0, int(x0 - m)), max(0, int(y0 - m)),
               min(w, int(x1 + m)), min(h, int(y1 + m)))
        crop = frame[box[1]:box[3], box[0]:box[2]]
        if not crop.size:
            return panel
        lines = [l.scaled(1, box[0], box[1]) for l in self._ocr(crop, self._scale(frame))]
        return _panel_from_rows(panel.side, _merge_rows(lines), panel.label_box) or panel

    def _detect_manual(self, frame, skip_gate=False):
        panels = []
        for side, reg in self.cfg["regions"].items():
            lx0, ly0, lx1, ly1 = _px_box(frame, reg["label"])
            lab = frame[ly0:ly1, lx0:lx1]
            if lab.size == 0 or (not skip_gate and not looks_like_panel(lab)):
                continue
            text = " ".join(l.text for l in self._ocr(lab, self._scale(frame)))
            if side_of_label(text) != side:
                continue
            ix0, iy0, ix1, iy1 = _px_box(frame, reg["info"])
            info = frame[iy0:iy1, ix0:ix1]
            if info.size == 0:
                continue
            lines = [l.scaled(1, ix0, iy0) for l in self._ocr(info, self._scale(frame))]
            p = _panel_from_rows(side, _merge_rows(lines), (lx0, ly0, lx1, ly1))
            if p:
                p.info_box = (ix0, iy0, ix1, iy1)
                panels.append(p)
        return panels

    def test_regions(self, frame):
        """位置調整画面用: 手動枠のOCR結果をそのまま返す"""
        out = {}
        for side, reg in self.cfg["regions"].items():
            res = {}
            for kind in ("label", "info"):
                x0, y0, x1, y1 = _px_box(frame, reg[kind])
                img = frame[y0:y1, x0:x1]
                res[kind] = [l.text for l in self._ocr(img, self._scale(frame))] if img.size else []
            out[side] = res
        return out


# ================= 1本の動画を解析 =================

# 解析方法を変えたら上げる（古いキャッシュを読み直させる）
SCAN_VERSION = 2


def cache_key(path, cfg):
    st = Path(path).stat()
    basis = {"p": str(Path(path).resolve()), "s": st.st_size, "m": int(st.st_mtime),
             "v": SCAN_VERSION, "mode": cfg["mode"], "fps": cfg["fps"],
             "pos": cfg["band"] if cfg["mode"] == "auto" else cfg["regions"]}
    return hashlib.sha1(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]


def scan_video(path, cfg, engine, progress=None, cancel=None, use_cache=True):
    """戻り値: 検出結果のリスト [{t, side, pilot, ac, pid}]"""
    cdir = config.app_dir() / "cache"
    cdir.mkdir(exist_ok=True)
    cfile = cdir / f"{cache_key(path, cfg)}.json"
    if use_cache and cfile.exists():
        return json.loads(cfile.read_text(encoding="utf-8"))

    info = probe(path)
    det = Detector(cfg, engine)
    gap = cfg["group_gap"]
    found = []
    reads = Counter()
    last_hit = -1e9
    for t, frame in iter_frames(path, info, cfg["fps"]):
        if cancel is not None and cancel.is_set():
            return None
        if progress:
            progress(t, info.duration, None)
        if t - last_hit > gap:
            reads.clear()
        # 同じ試合の両側を十分読めたら、次の試合まで読み飛ばす
        if reads["ALPHA"] >= 3 and reads["BETA"] >= 3:
            continue
        for p in det.detect(frame):
            if reads[p.side] >= 3:
                continue
            reads[p.side] += 1
            last_hit = t
            d = {"t": t, "side": p.side, "pilot": p.pilot, "ac": p.ac, "pid": p.pid}
            found.append(d)
            if progress:
                progress(t, info.duration, d)
    cfile.write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
    return found


def find_next_panel(path, info, cfg, engine, start, limit=900, cancel=None):
    """位置調整画面用: start 以降で最初にパネルが出る時刻を探す"""
    det = Detector(cfg, engine)
    for t, frame in iter_frames(path, info, 1.0, start):
        if cancel is not None and cancel.is_set():
            return None
        if t - start > limit:
            return None
        if det.detect(frame):
            return t
    return None


# ================= 集計 =================

def cluster(names):
    clusters = []
    for n in names:
        if not n:
            continue
        for c in clusters:
            if similar(n, c[0]):
                c.append(n)
                break
        else:
            clusters.append([n])
    out = [(Counter(c).most_common(1)[0][0], len(c)) for c in clusters]
    return sorted(out, key=lambda x: -x[1])


def group_matches(dets, gap):
    groups = []
    for d in sorted(dets, key=lambda d: d["t"]):
        if groups and d["t"] - groups[-1][-1]["t"] <= gap:
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def fmt_time(sec):
    sec = max(0, int(sec))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def guess_me(all_groups):
    """最も多く出てくる名前が7割以上の試合にあれば自分とみなす（3試合以上あるときだけ）
    ランクマッチでは同じ相手と何度も当たるので、1人だけに絞る"""
    sets = [{rep for rep, _ in cluster([d["pilot"] for d in g])} for g in all_groups]
    if len(sets) < 3:
        return []
    flat = cluster([n for s in sets for n in s])
    if flat and flat[0][1] >= len(sets) * 0.7 and (len(flat) == 1 or flat[0][1] > flat[1][1]):
        return [flat[0][0]]
    return []


def own_side(group, me):
    """その試合で自分がいた側（ALPHA/BETA）。分からなければ None"""
    for side in ("ALPHA", "BETA"):
        names = [d["pilot"] for d in group if d["side"] == side]
        if any(similar(n, m) for n in names for m in me):
            return side
    return None


def build_comment(dets, cfg, me):
    lines = []
    for g in group_matches(dets, cfg["group_gap"]):
        # 自分の側が分かれば反対側がそのまま相手。名前が化けても取り違えない
        own = own_side(g, me)
        pool = [d for d in g if d["side"] != own] if own else g
        cands = [rep for rep, _ in cluster([d["pilot"] for d in pool])
                 if not any(similar(rep, m) for m in me)]
        name = cands[0] if cands else "（読み取れず）"
        lines.append(f"{fmt_time(g[0]['t'] - cfg['lead_seconds'])} vs {name}")
    return "\n".join(lines)


def output_path(video):
    p = Path(video)
    return p.with_name(p.stem + "_対戦リスト.txt")
