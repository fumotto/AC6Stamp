# -*- coding: utf-8 -*-
"""AC6 Stamp の画面（tkinter）"""
import base64
import copy
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2

import config
import core
import ocr

VIDEO_TYPES = [("動画ファイル", "*.mp4 *.mkv *.mov *.flv *.ts *.webm"), ("すべて", "*.*")]
VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".flv", ".ts", ".webm"}

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False


# ---------------- OCRエンジン（スレッド間で共有、同時呼び出しは排他） ----------------

class SharedEngine:
    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if self._engine is None:
                self._engine = ocr.create_engine()
            return self

    @property
    def name(self):
        return self._engine.name if self._engine else "-"

    @property
    def max_dim(self):
        return self._engine.max_dim

    def recognize(self, img):
        with self._lock:
            return self._engine.recognize(img)


def frame_to_photo(frame, width):
    h, w = frame.shape[:2]
    disp = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, png = cv2.imencode(".png", disp)
    return tk.PhotoImage(data=base64.b64encode(png.tobytes())), disp.shape[1], disp.shape[0]


def open_folder(path):
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(Path(path).parent)])
    except Exception:
        pass


# ======================= メイン画面 =======================

class App:
    def __init__(self, root, files=(), auto_run=False):
        self.root = root
        self.cfg = config.load()
        self.engine = SharedEngine()
        self.q = queue.Queue()
        self.files = []          # 動画のパス
        self.state = {}          # パス -> 状態の文字列
        self.dets = {}           # パス -> 検出結果
        self.comments = {}       # パス -> コメント用テキスト
        self.cancel = threading.Event()
        self.worker = None

        root.title(f"{config.APP_TITLE} {config.VERSION}")
        root.geometry("760x640")
        root.minsize(620, 520)
        self._build()
        self.add_files(files)
        root.after(100, self._poll)
        if auto_run and self.files:
            root.after(300, self.start)

    # ---------- 画面の組み立て ----------
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="動画ファイル" + ("（ここにドラッグ&ドロップできます）" if HAS_DND else "")).pack(side="left")
        ttk.Button(top, text="削除", command=self.remove_selected).pack(side="right")
        ttk.Button(top, text="追加…", command=self.ask_files).pack(side="right", padx=4)

        lf = ttk.Frame(self.root)
        lf.pack(fill="x", **pad)
        self.listbox = tk.Listbox(lf, height=6, activestyle="none", selectmode="extended")
        self.listbox.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, command=self.listbox.yview)
        sb.pack(side="right", fill="y")
        self.listbox.config(yscrollcommand=sb.set)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.show_selected())
        if HAS_DND:
            for w in (self.listbox, self.root):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self._on_drop)

        me = ttk.Frame(self.root)
        me.pack(fill="x", **pad)
        ttk.Label(me, text="自分のパイロット名:").pack(side="left")
        self.me_var = tk.StringVar(value=", ".join(self.cfg["my_names"]))
        self.me_var.trace_add("write", lambda *a: self._schedule_refresh())
        ttk.Entry(me, textvariable=self.me_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Label(me, text="（複数はカンマ区切り。空欄なら自動判定）", foreground="#777").pack(side="left")

        opt = ttk.Frame(self.root)
        opt.pack(fill="x", **pad)
        self.save_var = tk.BooleanVar(value=self.cfg["save_txt"])
        ttk.Checkbutton(opt, text="動画と同じフォルダに「〜_対戦リスト.txt」を保存",
                        variable=self.save_var).pack(side="left")
        self.nocache_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="読み直す（前回の解析結果を使わない）",
                        variable=self.nocache_var).pack(side="left", padx=12)

        btn = ttk.Frame(self.root)
        btn.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btn, text="▶ 解析開始", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn, text="中止", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        ttk.Button(btn, text="読み取り位置の調整…", command=self.open_editor).pack(side="right")

        self.progress = ttk.Progressbar(self.root, mode="determinate", maximum=1000)
        self.progress.pack(fill="x", **pad)
        self.status = tk.StringVar(value="動画を追加して「解析開始」を押してください")
        ttk.Label(self.root, textvariable=self.status).pack(fill="x", padx=10)

        res_head = ttk.Frame(self.root)
        res_head.pack(fill="x", padx=10, pady=(10, 2))
        self.res_title = tk.StringVar(value="結果")
        ttk.Label(res_head, textvariable=self.res_title, font=("", 10, "bold")).pack(side="left")
        ttk.Button(res_head, text="保存先を開く", command=self.open_output).pack(side="right")
        ttk.Button(res_head, text="コピー", command=self.copy_result).pack(side="right", padx=4)

        rf = ttk.Frame(self.root)
        rf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.result = tk.Text(rf, wrap="none", font=("Consolas", 11), height=10)
        self.result.pack(side="left", fill="both", expand=True)
        rs = ttk.Scrollbar(rf, command=self.result.yview)
        rs.pack(side="right", fill="y")
        self.result.config(yscrollcommand=rs.set)

    # ---------- ファイル一覧 ----------
    def _on_drop(self, event):
        paths = []
        for p in self.root.tk.splitlist(event.data):
            p = Path(p)
            if p.is_dir():
                paths += sorted(f for f in p.iterdir() if f.suffix.lower() in VIDEO_EXTS)
            else:
                paths.append(p)
        self.add_files(paths)

    def ask_files(self):
        self.add_files(filedialog.askopenfilenames(title="動画を選択", filetypes=VIDEO_TYPES))

    def add_files(self, paths):
        for p in paths:
            p = str(Path(p))
            if p not in self.files and Path(p).is_file():
                self.files.append(p)
                self.state[p] = "待機"
        self.refresh_list()
        if self.files and not self.listbox.curselection():
            self.listbox.selection_set(len(self.files) - 1)
            self.show_selected()

    def remove_selected(self):
        if self.worker and self.worker.is_alive():
            return
        for i in reversed(self.listbox.curselection()):
            p = self.files.pop(i)
            for d in (self.state, self.dets, self.comments):
                d.pop(p, None)
        self.refresh_list()
        self.show_selected()

    def refresh_list(self):
        sel = self.listbox.curselection()
        self.listbox.delete(0, "end")
        for p in self.files:
            self.listbox.insert("end", f"[{self.state.get(p, '')}]  {Path(p).name}")
        for i in sel:
            if i < len(self.files):
                self.listbox.selection_set(i)

    def selected_path(self):
        sel = self.listbox.curselection()
        if sel:
            return self.files[sel[0]]
        return self.files[0] if self.files else None

    def show_selected(self):
        p = self.selected_path()
        self.result.delete("1.0", "end")
        if not p:
            self.res_title.set("結果")
            return
        self.res_title.set(f"結果: {Path(p).name}")
        self.result.insert("1.0", self.comments.get(p, ""))

    # ---------- 解析 ----------
    def _sync_cfg(self):
        self.cfg["my_names"] = [s.strip() for s in self.me_var.get().replace("、", ",").split(",") if s.strip()]
        self.cfg["save_txt"] = self.save_var.get()
        config.save(self.cfg)

    def _schedule_refresh(self):
        """自分の名前を書き換えたら、少し待ってから一覧を作り直す（再解析はしない）"""
        if getattr(self, "_refresh_job", None):
            self.root.after_cancel(self._refresh_job)
        self._refresh_job = self.root.after(600, self._refresh_comments)

    def _refresh_comments(self):
        self._refresh_job = None
        if self.worker and self.worker.is_alive():
            return
        self._sync_cfg()
        if self.dets:
            self._recompute()
            self.show_selected()

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        targets = [p for p in self.files if self.state.get(p) != "完了" or self.nocache_var.get()]
        if not targets:
            self.status.set("解析する動画がありません（再解析は「読み直す」にチェック）")
            return
        self._sync_cfg()
        self.cancel.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        cfg = copy.deepcopy(self.cfg)
        use_cache = not self.nocache_var.get()
        self.worker = threading.Thread(target=self._run, args=(targets, cfg, use_cache), daemon=True)
        self.worker.start()

    def stop(self):
        self.cancel.set()
        self.status.set("中止しています…")

    def _run(self, targets, cfg, use_cache):
        q = self.q
        try:
            q.put(("status", "OCRを準備中…"))
            engine = self.engine.get()
        except Exception as e:
            q.put(("fatal", str(e)))
            return
        for i, path in enumerate(targets, 1):
            name = Path(path).name
            q.put(("state", path, "解析中"))

            def prog(t, dur, det, i=i, name=name):
                frac = (t / dur) if dur else 0
                q.put(("progress", frac))
                if det:
                    q.put(("status", f"[{i}/{len(targets)}] {name}  {core.fmt_time(t)} {det['side']}: {det['pilot']}"))
                elif int(t) % 5 == 0:
                    q.put(("status", f"[{i}/{len(targets)}] {name}  {core.fmt_time(t)} / {core.fmt_time(dur)}"
                                     f"  （{engine.name}）"))
            try:
                dets = core.scan_video(path, cfg, engine, prog, self.cancel, use_cache)
            except Exception as e:
                traceback.print_exc()
                q.put(("state", path, "エラー"))
                q.put(("status", f"{name}: {e}"))
                continue
            if dets is None:
                q.put(("state", path, "中止"))
                break
            q.put(("done", path, dets))
        q.put(("finished",))

    def _recompute(self):
        """自分の名前が空欄なら、解析済みの全動画から自分を推定してコメントを作り直す"""
        me = list(self.cfg["my_names"])
        guessed = []
        if not me:
            groups = [g for d in self.dets.values() for g in core.group_matches(d, self.cfg["group_gap"])]
            guessed = me = core.guess_me(groups)
        for p, d in self.dets.items():
            text = core.build_comment(d, self.cfg, me) or "（対戦が見つかりませんでした）"
            self.comments[p] = text
            if self.cfg["save_txt"] and d:
                try:
                    core.output_path(p).write_text(text + "\n", encoding="utf-8")
                except Exception as e:
                    self.status.set(f"テキストを保存できませんでした: {e}")
        return guessed

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self.status.set(msg[1])
                elif kind == "progress":
                    self.progress["value"] = msg[1] * 1000
                elif kind == "state":
                    self.state[msg[1]] = msg[2]
                    self.refresh_list()
                elif kind == "done":
                    self.dets[msg[1]] = msg[2]
                    self.state[msg[1]] = "完了"
                    self._recompute()
                    self.refresh_list()
                    self.show_selected()
                elif kind == "fatal":
                    messagebox.showerror(config.APP_TITLE, msg[1])
                    self._finish("OCRを準備できませんでした")
                elif kind == "finished":
                    guessed = self._recompute()
                    self.show_selected()
                    note = ""
                    if not self.cfg["my_names"]:
                        note = (f"　自分と判定: {', '.join(guessed)}" if guessed
                                else "　※自分の名前を判定できませんでした。上の欄に入力すると相手名だけになります")
                    self._finish("完了しました" + note)
                    self._bring_to_front()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _finish(self, text):
        self.progress["value"] = 0 if "できません" in text else 1000
        self.status.set(text)
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _bring_to_front(self):
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(500, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    # ---------- 結果 ----------
    def copy_result(self):
        text = self.result.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status.set("コピーしました。YouTubeのコメント欄に貼り付けてください")

    def open_output(self):
        p = self.selected_path()
        if p:
            out = core.output_path(p)
            open_folder(out if out.exists() else p)

    def open_editor(self):
        p = self.selected_path() or filedialog.askopenfilename(title="調整に使う動画を選択", filetypes=VIDEO_TYPES)
        if not p:
            return
        self._sync_cfg()
        PositionEditor(self, p)


# ======================= 読み取り位置の調整 =======================

TARGETS = [("BETA", "label", "左下ラベル（UNIT BETA）"), ("BETA", "info", "左下の名前欄"),
           ("ALPHA", "label", "右下ラベル（UNIT ALPHA）"), ("ALPHA", "info", "右下の名前欄")]
COLORS = {"label": "#ff9a1f", "info": "#2fe36b"}
DISP_W = 900


class PositionEditor:
    def __init__(self, app: App, path):
        self.app = app
        self.path = path
        self.cfg = copy.deepcopy(app.cfg)
        self.frame = None
        self.photo = None
        self.disp = (DISP_W, 506)
        self.detected = []
        self.busy = False
        try:
            self.info = core.probe(path)
        except Exception as e:
            messagebox.showerror(config.APP_TITLE, str(e))
            return

        self.win = w = tk.Toplevel(app.root)
        w.title(f"読み取り位置の調整 - {Path(path).name}")
        w.transient(app.root)
        self._build()
        self.load_frame(0)

    def _build(self):
        w = self.win
        pad = {"padx": 10, "pady": 4}
        self.canvas = tk.Canvas(w, width=DISP_W, height=506, bg="black", highlightthickness=0)
        self.canvas.pack(**pad)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)

        nav = ttk.Frame(w)
        nav.pack(fill="x", **pad)
        self.t_var = tk.DoubleVar(value=0)
        self.scale = ttk.Scale(nav, from_=0, to=max(1, self.info.duration), variable=self.t_var,
                               command=lambda v: self.t_label.config(text=core.fmt_time(float(v))))
        self.scale.pack(side="left", fill="x", expand=True)
        self.scale.bind("<ButtonRelease-1>", lambda e: self.load_frame(self.t_var.get()))
        self.t_label = ttk.Label(nav, text="0:00", width=8)
        self.t_label.pack(side="left", padx=4)
        for d in (-10, -1, 1, 10):
            ttk.Button(nav, text=f"{d:+d}秒", width=6,
                       command=lambda d=d: self.load_frame(self.t_var.get() + d)).pack(side="left")
        ttk.Button(nav, text="次の対戦開始画面を探す ▶", command=self.find_next).pack(side="left", padx=6)

        self.mode_frame = mode = ttk.Frame(w)
        mode.pack(fill="x", **pad)
        ttk.Label(mode, text="読み取り方法:").pack(side="left")
        self.mode_var = tk.StringVar(value=self.cfg["mode"])
        ttk.Radiobutton(mode, text="自動（おすすめ）", value="auto", variable=self.mode_var,
                        command=self._mode_changed).pack(side="left", padx=4)
        ttk.Radiobutton(mode, text="手動で位置を指定", value="manual", variable=self.mode_var,
                        command=self._mode_changed).pack(side="left", padx=4)

        self.manual = ttk.Frame(w)
        ttk.Label(self.manual, text="ドラッグして枠を描く:").pack(side="left")
        self.target_var = tk.StringVar(value="BETA/label")
        for side, kind, label in TARGETS:
            ttk.Radiobutton(self.manual, text=label, value=f"{side}/{kind}",
                            variable=self.target_var).pack(side="left", padx=3)

        act = ttk.Frame(w)
        act.pack(fill="x", side="bottom", **pad)
        ttk.Button(act, text="保存して閉じる", command=self.save).pack(side="right")
        ttk.Button(act, text="閉じる", command=self.win.destroy).pack(side="right", padx=6)
        ttk.Button(act, text="手動枠を初期位置に戻す", command=self.reset).pack(side="left")
        ttk.Button(act, text="このコマで読み取りテスト", command=self.test).pack(side="left", padx=6)

        self.msg = tk.Text(w, height=6, font=("Consolas", 10), wrap="word")
        self.msg.pack(fill="x", side="bottom", **pad)
        self._mode_changed()

    def _say(self, text):
        self.msg.delete("1.0", "end")
        self.msg.insert("1.0", text)

    def _mode_changed(self):
        self.cfg["mode"] = self.mode_var.get()
        self.detected = []
        if self.cfg["mode"] == "manual":
            self.manual.pack(fill="x", padx=10, pady=4, after=self.mode_frame)
            self._say("1. 「次の対戦開始画面を探す」か時刻スライダーで、UNIT ALPHA / BETA が映っているコマを表示します。\n"
                      "2. 枠の種類を選び、画面上をドラッグして囲みます（ラベル＝UNIT○○の文字、名前欄＝名前3行）。\n"
                      "3. 「このコマで読み取りテスト」で確認し、「保存して閉じる」を押します。")
        else:
            self.manual.pack_forget()
            self._say("自動モードでは、画面下部から「UNIT ALPHA / BETA」の文字を探して名前の位置を割り出します。\n"
                      "「次の対戦開始画面を探す」で正しく読めるか確認できます。\n"
                      "うまく読めない場合だけ「手動で位置を指定」に切り替えてください。")
        self.redraw()

    # ---------- 画面表示 ----------
    def load_frame(self, t):
        t = min(max(0.0, float(t)), max(0.0, self.info.duration - 0.5))
        self.t_var.set(t)
        self.t_label.config(text=core.fmt_time(t))
        f = core.grab_frame(self.path, self.info, t)
        if f is None:
            return
        self.frame = f
        self.detected = []
        self.photo, dw, dh = frame_to_photo(f, DISP_W)
        self.disp = (dw, dh)
        self.canvas.config(width=dw, height=dh)
        self.redraw()

    def redraw(self):
        c = self.canvas
        c.delete("all")
        if self.photo:
            c.create_image(0, 0, image=self.photo, anchor="nw")
        dw, dh = self.disp
        if self.cfg["mode"] == "manual":
            for side, kind, label in TARGETS:
                x0, y0, x1, y1 = self.cfg["regions"][side][kind]
                c.create_rectangle(x0 * dw, y0 * dh, x1 * dw, y1 * dh, outline=COLORS[kind], width=2)
                right = x0 > 0.5
                c.create_text((x1 * dw - 3) if right else (x0 * dw + 3), y0 * dh - 2, text=label,
                              anchor="se" if right else "sw", fill=COLORS[kind], font=("", 9, "bold"))
        else:
            b0, b1 = self.cfg["band"]
            c.create_rectangle(1, b0 * dh, dw - 1, b1 * dh, outline="#5aa9ff", dash=(4, 4))
            c.create_text(6, b0 * dh - 2, text="自動で探す範囲", anchor="sw", fill="#5aa9ff")
        if self.frame is not None and self.detected:
            k = dw / self.frame.shape[1]
            for p in self.detected:
                for box, kind in ((p.label_box, "label"), (p.info_box, "info")):
                    if box:
                        x0, y0, x1, y1 = box
                        c.create_rectangle(x0 * k, y0 * k, x1 * k, y1 * k, outline=COLORS[kind], width=3)

    # ---------- 手動枠のドラッグ ----------
    def _press(self, e):
        if self.cfg["mode"] != "manual":
            return
        self._start = (e.x, e.y)
        self._tmp = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="white", dash=(3, 3), width=2)

    def _drag(self, e):
        if self.cfg["mode"] == "manual" and getattr(self, "_tmp", None):
            self.canvas.coords(self._tmp, self._start[0], self._start[1], e.x, e.y)

    def _release(self, e):
        if self.cfg["mode"] != "manual" or not getattr(self, "_tmp", None):
            return
        dw, dh = self.disp
        x0, x1 = sorted((self._start[0], e.x))
        y0, y1 = sorted((self._start[1], e.y))
        self._tmp = None
        if x1 - x0 < 5 or y1 - y0 < 5:
            self.redraw()
            return
        side, kind = self.target_var.get().split("/")
        self.cfg["regions"][side][kind] = [round(max(0, x0 / dw), 4), round(max(0, y0 / dh), 4),
                                           round(min(1, x1 / dw), 4), round(min(1, y1 / dh), 4)]
        # 次の枠へ自動で進める
        order = [f"{s}/{k}" for s, k, _ in TARGETS]
        i = order.index(self.target_var.get())
        self.target_var.set(order[(i + 1) % len(order)])
        self.redraw()

    def reset(self):
        self.cfg["regions"] = config.default_regions()
        self.redraw()

    # ---------- 読み取りテスト ----------
    def _bg(self, job, done):
        if self.busy:
            return
        self.busy = True
        self.win.config(cursor="watch")

        def run():
            try:
                engine = self.app.engine.get()
                res = job(engine)
                err = None
            except Exception as e:
                traceback.print_exc()
                res, err = None, e
            self.win.after(0, lambda: self._bg_done(done, res, err))
        threading.Thread(target=run, daemon=True).start()

    def _bg_done(self, done, res, err):
        self.busy = False
        try:
            self.win.config(cursor="")
        except tk.TclError:
            return
        if err:
            self._say(f"エラー: {err}")
        else:
            done(res)

    def test(self):
        if self.frame is None:
            return
        frame, cfg = self.frame, copy.deepcopy(self.cfg)

        def job(engine):
            det = core.Detector(cfg, engine)
            panels = det.detect(frame)
            raw = det.test_regions(frame) if cfg["mode"] == "manual" else None
            return panels, raw

        def done(res):
            panels, raw = res
            self.detected = panels
            self.redraw()
            lines = []
            for p in panels:
                lines.append(f"{p.side}: パイロット名「{p.pilot}」 AC名「{p.ac}」 ID「{p.pid}」")
            if not panels:
                lines.append("このコマでは対戦開始画面を検出できませんでした。")
            if raw:
                lines.append("")
                for side, r in raw.items():
                    lines.append(f"[{side}] ラベル枠の文字: {' / '.join(r['label']) or '（なし）'}")
                    lines.append(f"[{side}] 名前枠の文字: {' / '.join(r['info']) or '（なし）'}")
            self._say("\n".join(lines))
        self._say("読み取り中…")
        self._bg(job, done)

    def find_next(self):
        start = self.t_var.get() + 2
        cfg = copy.deepcopy(self.cfg)
        self._say("対戦開始画面を探しています…（最大15分先まで）")

        def job(engine):
            return core.find_next_panel(self.path, self.info, cfg, engine, start)

        def done(t):
            if t is None:
                self._say("見つかりませんでした。手動モードなら枠の位置を見直すか、スライダーで探してください。")
                return
            self.load_frame(t)
            self.test()
        self._bg(job, done)

    def save(self):
        self.app.cfg["mode"] = self.cfg["mode"]
        self.app.cfg["regions"] = self.cfg["regions"]
        config.save(self.app.cfg)
        self.app.status.set("読み取り位置を保存しました"
                            + ("（手動）" if self.cfg["mode"] == "manual" else "（自動）"))
        self.win.destroy()


# ======================= 起動 =======================

def selftest(out_file):
    """ffmpeg と OCR が配布版の中で動くかを確認する（GitHub Actions で使用）"""
    import numpy as np
    lines = []
    ok = True
    try:
        lines.append(f"ffmpeg: {core.ffmpeg_exe()}")
        img = np.zeros((200, 900, 3), np.uint8)
        cv2.putText(img, "UNIT BETA", (40, 90), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (255, 255, 255), 4)
        cv2.putText(img, "barracuda", (40, 170), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (255, 255, 255), 3)
        eng = ocr.create_engine()
        texts = [l.text for l in eng.recognize(img)]
        lines.append(f"engine: {eng.name}")
        lines.append(f"ocr: {texts}")
        joined = " ".join(texts).upper()
        if "BETA" not in joined or "BARRACUDA" not in joined:
            ok = False
            lines.append("NG: OCR結果が期待と異なります")
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    lines.append("RESULT: " + ("OK" if ok else "NG"))
    Path(out_file).write_text("\n".join(lines), encoding="utf-8")
    return 0 if ok else 1


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="AC6Stamp")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--auto-run", action="store_true", help="起動後すぐに解析を始める（OBS連携用）")
    ap.add_argument("--selftest", metavar="結果ファイル", help="OCRとffmpegの動作確認だけして終了（ビルド確認用）")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest(args.selftest)

    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    try:
        ttk.Style().theme_use("vista" if os.name == "nt" else "clam")
    except tk.TclError:
        pass
    if os.name == "nt":
        root.option_add("*Font", ("Yu Gothic UI", 10))
    App(root, args.files, args.auto_run)
    root.mainloop()
