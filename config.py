# -*- coding: utf-8 -*-
"""設定の読み書き（%APPDATA%\\AC6Stamp\\config.json）"""
import copy
import json
import os
from pathlib import Path

APP_NAME = "AC6Stamp"
APP_TITLE = "AC6 Stamp"
VERSION = "1.0.0"

DEFAULT = {
    # auto: 画面下部から「UNIT ALPHA/BETA」を探して位置を自動で割り出す
    # manual: regions の固定位置を読む
    "mode": "auto",
    "my_names": [],          # 自分のパイロット名（相手名から除外）
    "fps": 1.0,              # 1秒あたり何コマ調べるか
    "lead_seconds": 2,       # タイムスタンプを何秒手前にずらすか
    "group_gap": 45,         # これ以上空いたら別の試合
    "save_txt": True,        # 動画の横に「〜_対戦リスト.txt」を保存
    "band": [0.66, 0.95],    # 自動モードで探す範囲（画面の上下位置の割合）
    "regions": {             # 手動モードの読み取り位置（画面に対する割合 x0, y0, x1, y1）
        "ALPHA": {"label": [0.850, 0.770, 0.980, 0.870], "info": [0.640, 0.765, 0.840, 0.870]},
        "BETA": {"label": [0.030, 0.770, 0.140, 0.870], "info": [0.205, 0.765, 0.415, 0.870]},
    },
}


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_dir() / "config.json"


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except Exception:
        data = {}
    return _merge(DEFAULT, data)


def save(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def default_regions() -> dict:
    return copy.deepcopy(DEFAULT["regions"])
