#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gui.py - 南昌航空大学图书馆座位预约 图形界面(tkinter, 零第三方依赖)

功能:
  * 导入抓包认证(文件选择)
  * 选楼层 → 选阅览室(标注室内/室外) → 选座位(标注插座)
  * 时间段: 开始时间 + 结束时间 两个下拉, 支持添加多个时间段
    约束: 开始 ≥ 开馆, 结束 ≤ 闭馆, 单次 1~6 小时
  * 预约次日(多时间段依次预约) / 即刻预约(今天, 校验开始时间早于当下则跳过)
  * 我的预约列表 + 取消
  * 通知设置(弹窗): 微信 Server酱 / 邮箱
  * 日志实时显示

直接运行: py gui.py
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main as M  # noqa: E402

# 配色方案(现代清爽蓝)
BG = "#f3f4f6"          # 页面背景(浅灰蓝)
CARD = "#ffffff"        # 卡片背景
FG = "#1f2937"          # 主文字(深灰)
ACCENT = "#2563eb"      # 主蓝
ACCENT_DARK = "#1d4ed8"
HEADER_BG = "#1e40af"   # 顶部 Header 深蓝
PANEL = "#eef2ff"       # 浅蓝(徽章/状态栏)
SUBTLE = "#6b7280"      # 次要文字
BORDER = "#e5e7eb"      # 边框
GREEN = "#16a34a"       # 成功
ORANGE = "#ea580c"      # 警告


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("昌航图书馆座位预约")
        self.geometry("780x720")
        self.minsize(720, 660)
        self.configure(bg=BG)

        self.cfg = M.load_config()
        self._ui_queue = queue.Queue()
        self.floors = []
        self.rooms = []
        self.seats = []
        self.time_segs = []  # 已添加的时间段 [("12:00","18:00"), ...]
        self.booking_log = []  # 本次会话的预约记录(内存, 退出自动清除, 不持久化)

        self._build_style()
        self._build_layout()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._poll_ui_queue()
        self.log("界面已启动。")
        self._refresh_auth_label()
        self._refresh_account_combo()
        self._load_floors()

    # -- 样式 -------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, fieldbackground=CARD,
                        font=("Microsoft YaHei UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL, foreground=ACCENT_DARK)
        style.configure("Subtle.TLabel", background=BG, foreground=SUBTLE)
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 13, "bold"),
                        background=BG, foreground=ACCENT_DARK)

        # 普通按钮(白底描边)
        style.configure("TButton", padding=(10, 6), background=CARD, foreground=FG,
                        bordercolor=BORDER, relief="flat", focusthickness=0)
        style.map("TButton",
                  background=[("active", "#e8f0fe"), ("pressed", "#dbeafe")],
                  foreground=[("active", ACCENT_DARK)])

        # 主按钮(实心蓝)
        style.configure("Accent.TButton", padding=(14, 7), background=ACCENT,
                        foreground="white", bordercolor=ACCENT, relief="flat",
                        focusthickness=0)
        style.map("Accent.TButton",
                  background=[("active", ACCENT_DARK), ("pressed", HEADER_BG)],
                  foreground=[("active", "white")])

        # 次要按钮(浅蓝底)
        style.configure("Ghost.TButton", padding=(10, 6), background=PANEL,
                        foreground=ACCENT_DARK, bordercolor="#c7d2fe", relief="flat",
                        focusthickness=0)
        style.map("Ghost.TButton", background=[("active", "#dbeafe")])

        # 下拉框
        style.configure("TCombobox", foreground=FG, fieldbackground=CARD,
                        background=CARD, arrowcolor=SUBTLE, bordercolor=BORDER,
                        lightcolor=CARD, darkcolor=CARD, padding=(4, 3))
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD)],
                  foreground=[("readonly", FG)],
                  selectbackground=[("readonly", CARD)],
                  selectforeground=[("readonly", FG)],
                  bordercolor=[("focus", ACCENT)])

        # 输入框
        style.configure("TEntry", fieldbackground=CARD, foreground=FG,
                        bordercolor=BORDER, lightcolor=CARD, darkcolor=CARD,
                        padding=(4, 3))

        # 表格
        style.configure("Treeview", background=CARD, fieldbackground=CARD,
                        foreground=FG, rowheight=26, bordercolor=BORDER,
                        font=("Microsoft YaHei UI", 9))
        style.configure("Treeview.Heading", background=PANEL, foreground=ACCENT_DARK,
                        font=("Microsoft YaHei UI", 9, "bold"), relief="flat")
        style.map("Treeview",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])
        style.map("Treeview.Heading", background=[("active", "#dbeafe")])

        style.configure("TListbox", background=CARD, foreground=FG)

        # 卡片式分区
        style.configure("TLabelframe", background=CARD, foreground=FG,
                        bordercolor=BORDER, relief="solid")
        style.configure("TLabelframe.Label", background=CARD, foreground=ACCENT_DARK,
                        font=("Microsoft YaHei UI", 10, "bold"))

        self.option_add("*TCombobox*Listbox.background", CARD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "white")

    # -- 布局 -------------------------------------------------------------
    def _build_layout(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_header()
        self._build_select()
        self._build_booking()
        self._build_my_list()
        self._build_log()

        self.status_var = tk.StringVar(value="就绪")
        tk.Label(self, textvariable=self.status_var, font=("Microsoft YaHei UI", 9),
                 bg=PANEL, fg=ACCENT_DARK, anchor="w", padx=12, pady=5).grid(
            row=5, column=0, sticky="ew")

    def _build_header(self):
        f = tk.Frame(self, bg=HEADER_BG)
        f.grid(row=0, column=0, sticky="ew")
        f.columnconfigure(0, weight=1)

        # 标题行 + 认证徽章
        row = tk.Frame(f, bg=HEADER_BG)
        row.grid(row=0, column=0, sticky="ew", padx=18, pady=(14, 2))
        row.columnconfigure(0, weight=1)
        tk.Label(row, text="昌航图书馆座位预约", font=("Microsoft YaHei UI", 16, "bold"),
                 bg=HEADER_BG, fg="white").grid(row=0, column=0, sticky="w")
        tk.Label(row, text="多账号 · 自动选座 · 定时抢座", font=("Microsoft YaHei UI", 9),
                 bg=HEADER_BG, fg="#c7d2fe").grid(row=1, column=0, sticky="w")
        self.auth_var = tk.StringVar(value="认证状态: 检测中...")
        tk.Label(row, textvariable=self.auth_var, font=("Microsoft YaHei UI", 9),
                 bg=PANEL, fg=ACCENT_DARK, padx=12, pady=4).grid(
            row=0, column=1, rowspan=2, sticky="e", padx=(0, 12))
        ttk.Button(row, text="导入抓包文件", command=self._on_import).grid(
            row=0, column=2, rowspan=2, sticky="e")

        # 用户 ID 行
        bar = tk.Frame(f, bg=HEADER_BG)
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 14))
        tk.Label(bar, text="用户ID", font=("Microsoft YaHei UI", 9),
                 bg=HEADER_BG, fg="#c7d2fe").pack(side="left")
        self.account_var = tk.StringVar()
        self.account_combo = ttk.Combobox(bar, textvariable=self.account_var,
                                          state="readonly", width=22)
        self.account_combo.pack(side="left", padx=(8, 12))
        self.account_combo.bind("<<ComboboxSelected>>", self._on_account_changed)
        ttk.Button(bar, text="清除预约信息", command=self._on_clear_reserve).pack(side="left")
        ttk.Button(bar, text="删除账号", command=self._on_clear_auth).pack(
            side="left", padx=(6, 0))

    def _build_select(self):
        f = ttk.LabelFrame(self, text=" 选择座位 ", padding=(10, 8))
        f.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 4))
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="楼层:").grid(row=0, column=0, sticky="w")
        self.floor_var = tk.StringVar()
        self.floor_combo = ttk.Combobox(f, textvariable=self.floor_var, state="readonly", width=18)
        self.floor_combo.grid(row=0, column=1, sticky="w", padx=(6, 14))
        self.floor_combo.bind("<<ComboboxSelected>>", self._on_floor_selected)

        ttk.Label(f, text="阅览室:").grid(row=0, column=2, sticky="w")
        self.room_var = tk.StringVar()
        self.room_combo = ttk.Combobox(f, textvariable=self.room_var, state="readonly", width=26)
        self.room_combo.grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.room_combo.bind("<<ComboboxSelected>>", self._on_room_selected)

        ttk.Label(f, text="座位号:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.seat_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.seat_var, width=18).grid(
            row=1, column=1, sticky="w", padx=(6, 0), pady=(8, 0))
        ttk.Label(f, text="(自己填写座位号, 如 211)", style="Subtle.TLabel").grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(f, text="习惯座位:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.memory_var = tk.StringVar()
        self.memory_combo = ttk.Combobox(f, textvariable=self.memory_var,
                                         state="readonly", width=42)
        self.memory_combo.grid(row=2, column=1, columnspan=3, sticky="w",
                               padx=(6, 0), pady=(8, 0))
        self.memory_combo.bind("<<ComboboxSelected>>", self._on_memory_selected)

    def _build_booking(self):
        f = ttk.LabelFrame(self, text=" 预约时间 ", padding=(10, 8))
        f.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 4))
        f.columnconfigure(2, weight=1)

        # 时间选择 + 添加
        ttk.Label(f, text="开始时间:").grid(row=0, column=0, sticky="w")
        self.start_var = tk.StringVar()
        self.start_combo = ttk.Combobox(f, textvariable=self.start_var, state="readonly", width=8)
        self.start_combo.grid(row=0, column=1, sticky="w", padx=(6, 10))
        ttk.Label(f, text="结束时间:").grid(row=0, column=2, sticky="w")
        self.end_var = tk.StringVar()
        self.end_combo = ttk.Combobox(f, textvariable=self.end_var, state="readonly", width=8)
        self.end_combo.grid(row=0, column=3, sticky="w", padx=(6, 10))
        ttk.Button(f, text="添加时间段", style="Ghost.TButton",
                   command=self._on_add_time).grid(row=0, column=4, sticky="w")
        ttk.Button(f, text="删除选中", command=self._on_remove_time).grid(
            row=0, column=5, sticky="w", padx=(6, 0))

        # 已添加的时间段列表
        self.time_list = tk.Listbox(f, height=3, bg=CARD, fg=FG, relief="solid",
                                    borderwidth=1, highlightthickness=0,
                                    selectbackground=ACCENT, selectforeground="white",
                                    exportselection=False, highlightcolor=BORDER)
        self.time_list.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(8, 0))
        ttk.Label(f, text="可添加多个时间段; 单次 1~6 小时, 预约次日时依次执行",
                  style="Subtle.TLabel").grid(row=2, column=0, columnspan=6,
                                              sticky="w", pady=(4, 0))

        # 预约按钮
        ttk.Button(f, text="预约次日(到22:00自动抢)", style="Accent.TButton",
                   command=lambda: self._on_book(days_ahead=1)).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Button(f, text="即刻预约(今天)", style="Ghost.TButton",
                   command=self._on_book_now).grid(
            row=3, column=3, columnspan=3, sticky="e", pady=(8, 0))

    def _build_my_list(self):
        f = ttk.LabelFrame(self, text=" 本次预约记录(退出后自动清除) ", padding=(6, 6))
        f.grid(row=3, column=0, sticky="nsew", padx=12, pady=(4, 4))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        bar = ttk.Frame(f)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Button(bar, text="取消选中", command=self._on_cancel).pack(side="left")
        ttk.Label(bar, text="同一任务只显示一行, 状态会更新", style="Subtle.TLabel").pack(
            side="left", padx=(10, 0))

        self.tree = ttk.Treeview(f, columns=("sid", "seat", "region", "time", "status", "at"),
                                 show="headings", height=6)
        for key, title, width in (("sid", "学号", 90), ("seat", "座位", 60),
                                  ("region", "区域", 140), ("time", "预约时间", 140),
                                  ("status", "状态", 110), ("at", "操作时间", 140)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width,
                             anchor="center" if key not in ("sid", "region", "status") else "w")
        self.tree.grid(row=1, column=0, sticky="nsew")

    def _build_log(self):
        f = ttk.LabelFrame(self, text=" 日志 ", padding=(6, 6))
        f.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 8))
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(f, height=7, bg="#1e293b", fg="#e2e8f0",
                                     insertbackground="white", wrap="word",
                                     font=("Consolas", 9), relief="flat",
                                     borderwidth=1, highlightthickness=0)
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.configure(state="disabled")

    # -- 日志 -------------------------------------------------------------
    def log(self, msg: str):
        # 只写底部日志框(内存), 不落盘, 程序退出自动清理
        line = "%s %s" % (M.time.strftime("%H:%M:%S"), msg)
        if threading.current_thread() is threading.main_thread():
            self._append_log(line)
        else:
            self._ui_queue.put(lambda: self._append_log(line))

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        n = int(self.log_text.index("end-1c").split(".")[0])
        if n > 500:
            self.log_text.delete("1.0", "150.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_ui_queue(self):
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        self.after(100, self._poll_ui_queue)

    def _run_async(self, work, done=None):
        def runner():
            result = None
            try:
                result = work()
            except Exception as exc:
                self.log("[错误] %s" % exc)
            if done:
                self._ui_queue.put(lambda: done(result))
        threading.Thread(target=runner, daemon=True).start()

    def _set_status(self, text):
        self.status_var.set(text)

    # -- 时间选项 ---------------------------------------------------------
    def _time_options(self):
        open_str = self.cfg.get("schedule", {}).get("open_time", "08:00")
        close_str = self.cfg.get("schedule", {}).get("close_time", "22:00")
        try:
            oh = int(open_str.split(":")[0])
            ch = int(close_str.split(":")[0])
        except ValueError:
            oh, ch = 8, 22
        return ["%02d:00" % h for h in range(oh, ch + 1)]

    def _refresh_time_options(self):
        opts = self._time_options()
        self.start_combo["values"] = opts[:-1]  # 开始不能是闭馆
        self.end_combo["values"] = opts[1:]     # 结束不能是开馆

    def _on_add_time(self):
        start = self.start_var.get().strip()
        end = self.end_var.get().strip()
        if not start or not end:
            messagebox.showinfo("提示", "请选择开始和结束时间")
            return
        s = M._to_min(start)
        e = M._to_min(end)
        if e <= s:
            messagebox.showwarning("提示", "结束时间必须晚于开始时间")
            return
        if e - s > 6 * 60:
            messagebox.showwarning("提示", "单次预约不能超过 6 小时")
            return
        if e - s < 60:
            messagebox.showwarning("提示", "单次预约不能少于 1 小时")
            return
        self.time_segs.append((start, end))
        self.time_list.insert("end", "%s - %s" % (start, end))
        self.log("已添加时间段: %s-%s" % (start, end))

    def _on_remove_time(self):
        sel = self.time_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中要删除的时间段")
            return
        idx = sel[0]
        self.time_list.delete(idx)
        removed = self.time_segs.pop(idx)
        self.log("已删除时间段: %s-%s" % removed)

    # -- 认证 -------------------------------------------------------------
    def _refresh_auth_label(self):
        a = M.active_account(self.cfg)
        sid = M.current_student_id(self.cfg)
        if not sid:
            self.auth_var.set("未导入认证")
        elif a.get("auth") and a.get("uid"):
            self.auth_var.set("学号 %s: 已导入" % sid)
        else:
            self.auth_var.set("学号 %s: 未导入" % sid)

    def _on_import(self):
        path = filedialog.askopenfilename(
            title="选择抓包文件", filetypes=[("抓包文件", "*.txt *.har *.json"), ("所有文件", "*.*")])
        if not path:
            return
        def work():
            return M.cmd_import(path)
        def done(rc):
            self.cfg = M.load_config()
            self._refresh_auth_label()
            self._refresh_account_combo()
            self.log("认证导入%s。当前账号: %s" % (
                "成功" if rc == 0 else "失败", M.current_student_id(self.cfg)))
            if rc == 0:
                # 导入成功后重新加载楼层(启动时无账号, 楼层加载会失败)
                self._load_floors()
            else:
                self._load_account_state()
        self._run_async(work, done)

    # -- 多账号管理 -------------------------------------------------------
    def _account_display_name(self, sid):
        """下拉框只显示学号。"""
        return sid

    def _current_sid(self):
        """当前选中的学号(维护在 _selected_sid, 不受下拉框显示名影响)。"""
        return getattr(self, "_selected_sid", "") or M.current_student_id(self.cfg)

    def _refresh_account_combo(self):
        self._account_ids = M.account_list(self.cfg)
        self.account_combo["values"] = [self._account_display_name(sid)
                                        for sid in self._account_ids]
        cur = M.current_student_id(self.cfg)
        if cur and cur in self._account_ids:
            self._selected_sid = cur
            self.account_var.set(self._account_display_name(cur))
        elif self._account_ids:
            self._selected_sid = self._account_ids[0]
            M.set_current(self.cfg, self._account_ids[0])
            self.account_var.set(self._account_display_name(self._account_ids[0]))
        else:
            # 尚未导入任何账号, 显示"无"
            self._selected_sid = ""
            self.account_var.set("无")

    def _save_current_state(self):
        """把当前 GUI 表单状态保存到当前学号账号(gui_state), 切换学号互不干扰。"""
        acc = M.active_account(self.cfg)
        if not acc:
            return
        room = self.room_var.get().split(" [")[0] if self.room_var.get() else ""
        acc["gui_state"] = {
            "floor_name": self.floor_var.get(),
            "content_id": getattr(self, "_cid", ""),
            "room": room,
            "seat_num": self.seat_var.get().strip(),
            "time_segs": [list(seg) for seg in self.time_segs],
        }
        M.save_config(self.cfg)

    def _load_account_state(self):
        """从当前账号的 gui_state 恢复 GUI 表单。"""
        acc = M.active_account(self.cfg)
        state = acc.get("gui_state") or {}
        self._refresh_memory_combo()
        self.time_segs = []
        self.time_list.delete(0, "end")
        for seg in state.get("time_segs", []):
            if len(seg) == 2:
                self.time_segs.append((seg[0], seg[1]))
                self.time_list.insert("end", "%s - %s" % (seg[0], seg[1]))
        self.seat_var.set(state.get("seat_num", ""))
        self._refresh_time_options()
        floor_name = state.get("floor_name", "")
        cid = state.get("content_id", "")
        if floor_name and cid:
            self.floor_var.set(floor_name)
            self._cid = cid
            self._set_status("加载阅览室...")
            saved_room = state.get("room", "")
            def work():
                begin = M.ts_of(1, 8)
                return M.get_rooms(self.cfg, cid, begin, 6 * 3600)
            def done(rooms):
                self.rooms = rooms
                self.room_combo["values"] = ["%s [%s]" % (r, M.room_type(r)) for r in rooms]
                chosen = saved_room if saved_room in rooms else (rooms[0] if rooms else "")
                if chosen:
                    self.room_var.set("%s [%s]" % (chosen, M.room_type(chosen)))
                    self._on_room_selected()
                self._set_status("就绪")
            self._run_async(work, done)
        else:
            if self.floors:
                self.floor_var.set(self.floors[0][0])
                self._on_floor_selected()

    def _on_account_changed(self, _event=None):
        idx = self.account_combo.current()
        ids = getattr(self, "_account_ids", [])
        if not (0 <= idx < len(ids)):
            return
        new_id = ids[idx]
        if new_id == M.current_student_id(self.cfg):
            self._selected_sid = new_id
            return
        self._save_current_state()          # 保存旧账号
        M.set_current(self.cfg, new_id)     # 切换
        self._selected_sid = new_id
        self._load_account_state()          # 加载新账号
        self._refresh_auth_label()
        self.log("已切换到学号: %s" % new_id)
        self._render_log()

    def _on_clear_reserve(self):
        """清除当前学号的预约信息(所选所有选项 + 习惯座位记忆), 保留认证数据。"""
        sid = self._current_sid()
        if not sid:
            return
        if not messagebox.askyesno("确认", "确定清除学号 %s 的预约信息吗?\n\n"
                                   "将清空: 所选楼层/阅览室/座位号/时间段, 以及习惯座位记忆。\n"
                                   "认证数据保留。" % sid):
            return
        acc = M.get_account(self.cfg, sid)
        acc["gui_state"] = {}
        acc["tasks"] = []
        (acc.get("reserve") or {}).pop("target_seats", None)
        M.clear_memory(sid)   # 清除习惯座位记忆(bookmemory)
        M.save_config(self.cfg)
        if sid == M.current_student_id(self.cfg):
            # 清空界面上所选的所有选项
            self.time_segs = []
            self.time_list.delete(0, "end")
            self.floor_var.set("")
            self.room_var.set("")
            self.seat_var.set("")
            self.start_var.set("")
            self.end_var.set("")
            self.memory_var.set("")
            self.rooms = []
            self.seats = []
            self._room = ""
            self._cid = ""
        self._refresh_account_combo()
        self._refresh_memory_combo()
        self.log("已清除学号 %s 的预约信息与习惯座位记忆" % sid)

    def _on_clear_auth(self):
        """删除当前学号的整个账号(认证数据+预约信息), 彻底删除保护隐私。"""
        sid = self._current_sid()
        if not sid:
            return
        if not messagebox.askyesno("确认", "确定删除学号 %s 的账号吗?\n\n"
                                   "将彻底删除该账号的认证数据(auth/uid 等)与预约信息。\n"
                                   "删除后用户 ID 恢复为\"无\", 需重新抓包导入才能预约。" % sid):
            return
        accounts = self.cfg.get("accounts") or {}
        accounts.pop(sid, None)
        remaining = M.account_list(self.cfg)
        self.cfg["current"] = remaining[0] if remaining else ""
        M.save_config(self.cfg)
        self._refresh_account_combo()
        self._refresh_auth_label()
        self._load_account_state()
        self.log("已彻底删除学号 %s 的账号" % sid)

    # -- 习惯座位记忆 -----------------------------------------------------
    def _refresh_memory_combo(self):
        """加载当前账号的历史座位记忆到下拉框。"""
        sid = M.current_student_id(self.cfg)
        self._memory_list = M.get_memory(sid)
        self.memory_combo["values"] = [
            "%s · %s · %s" % (m.get("seat_num", ""), m.get("room", ""),
                              m.get("floor_name", ""))
            for m in self._memory_list]
        self.memory_var.set("")

    def _on_memory_selected(self, _event=None):
        idx = self.memory_combo.current()
        mems = getattr(self, "_memory_list", [])
        if 0 <= idx < len(mems):
            self._apply_memory(mems[idx])

    def _apply_memory(self, m):
        """把记忆的座位/楼层/房间填充到表单。"""
        self.seat_var.set(str(m.get("seat_num", "")))
        floor_name = m.get("floor_name", "")
        cid = m.get("content_id", "")
        room = m.get("room", "")
        if floor_name:
            self.floor_var.set(floor_name)
        if cid:
            self._cid = cid
            self._set_status("加载阅览室...")
            def work():
                begin = M.ts_of(1, 8)
                return M.get_rooms(self.cfg, cid, begin, 6 * 3600)
            def done(rooms):
                self.rooms = rooms
                self.room_combo["values"] = ["%s [%s]" % (r, M.room_type(r)) for r in rooms]
                chosen = room if room in rooms else (rooms[0] if rooms else "")
                if chosen:
                    self.room_var.set("%s [%s]" % (chosen, M.room_type(chosen)))
                    self._on_room_selected()
                self._set_status("就绪")
            self._run_async(work, done)
        self.log("已选择习惯座位: %s座 (%s · %s)" % (
            m.get("seat_num"), m.get("room"), m.get("floor_name")))

    def _record_memory(self, seat_num):
        """预约成功后, 把当前座位号+房间+楼层写入该账号的记忆。"""
        sid = M.current_student_id(self.cfg)
        M.add_memory(sid, {
            "seat_num": str(seat_num),
            "room": getattr(self, "_room", "") or "",
            "floor_name": self.floor_var.get() or "",
            "content_id": getattr(self, "_cid", "") or "",
        })
        self._refresh_memory_combo()

    def _current_region(self):
        """当前区域名 = 楼层 + 阅览室(如 '三楼自习区'), 不含单独楼层列。"""
        floor = self.floor_var.get() or ""
        room = getattr(self, "_room", "") or ""
        return (floor + room).strip()

    # -- 楼层 / 阅览室 / 座位 联动 ---------------------------------------
    def _load_floors(self):
        self._set_status("加载楼层列表...")
        def work():
            return M.get_floors(self.cfg)
        def done(floors):
            self.floors = floors
            self.floor_combo["values"] = [n for n, _ in floors]
            self._refresh_time_options()
            self._load_account_state()  # 恢复当前账号的楼层/阅览室/座位/时间段
            self._set_status("就绪")
        self._run_async(work, done)

    def _on_floor_selected(self, _event=None):
        name = self.floor_var.get()
        cid = ""
        for n, c in self.floors:
            if n == name:
                cid = c
                break
        if not cid:
            return
        self._cid = cid
        self._set_status("加载阅览室...")
        begin = M.ts_of(1, 8)
        def work():
            return M.get_rooms(self.cfg, cid, begin, 6 * 3600)
        def done(rooms):
            self.rooms = rooms
            self.room_combo["values"] = ["%s [%s]" % (r, M.room_type(r)) for r in rooms]
            if rooms:
                self.room_var.set("%s [%s]" % (rooms[0], M.room_type(rooms[0])))
                self._on_room_selected()
            self._set_status("就绪")
        self._run_async(work, done)

    def _on_room_selected(self, _event=None):
        room_display = self.room_var.get()
        room = room_display.split(" [")[0]
        self._room = room
        begin = M.ts_of(1, 8)
        def work():
            seats = M.search_seats(self.cfg, begin, 6 * 3600, content_id=self._cid)
            return [s for s in seats if s.get("_room") == room]
        def done(seats):
            self.seats = seats
            self._set_status("就绪")
        self._run_async(work, done)

    # -- 预约 -------------------------------------------------------------
    def _selected_seat(self):
        val = self.seat_var.get().strip()
        if not val:
            return None, None
        for s in self.seats:
            if str(s.get("title")) == val:
                return s.get("id"), str(s.get("title"))
        return None, None

    def _book_tasks(self, days_ahead):
        self._save_current_state()
        seat_id, seat_num = self._selected_seat()
        if not seat_id:
            seat_input = self.seat_var.get().strip()
            msg = ("座位号 %s 不存在于当前阅览室" % seat_input) if seat_input else "请先填写座位号"
            self.log("[预约失败] %s" % msg)

            return
        if not self.time_segs:
            msg = "请先添加时间段(开始/结束时间)"
            self.log("[预约失败] %s" % msg)

            return
        cid = getattr(self, "_cid", "") or M.active_account(self.cfg).get(
            "reserve", {}).get("space_category", {}).get("content_id", "")

        self._set_status("预约中...")
        def work():
            results = []
            for s, e in self.time_segs:
                begin, dur = M.time_range_to_ts(days_ahead, s, e)
                r = M.do_book(self.cfg, begin, dur, seat_id)
                results.append((s, e, r))
            return results
        def done(results):
            ok = 0
            sid = M.current_student_id(self.cfg)
            day_label = "明天" if days_ahead == 1 else "今天"
            for s, e, r in results:
                self.log("预约 %s-%s: %s" % (s, e, M.json.dumps(r, ensure_ascii=False)[:180]))
                data = r.get("DATA", {}) if isinstance(r, dict) else {}
                if data.get("result") == "success":
                    ok += 1
                    status = "成功"
                    self.log("[预约成功] %s座 %s-%s (bookingId=%s)" % (
                        seat_num, s, e, data.get("bookingId")))
                else:
                    status = "失败: %s" % M.explain_failure(r)
                    self.log("[预约失败] %s座 %s-%s 原因: %s" % (
                        seat_num, s, e, M.explain_failure(r)))
                self._log_booking(sid, seat_num, self._current_region(),
                                  "%s %s-%s" % (day_label, s, e), status,
                                  booking_id=data.get("bookingId") or "")
                if M.is_login_expired(r):
                    self.log("[!] 登录已失效(auth/uid 过期), 请重新抓包导入")
            if ok > 0:
                self._record_memory(seat_num)
            self._render_log()
            self._set_status("完成: %d/%d 成功" % (ok, len(results)))
        self._run_async(work, done)

    def _on_book_now(self):
        self._save_current_state()
        seat_id, seat_num = self._selected_seat()
        if not seat_id:
            seat_input = self.seat_var.get().strip()
            msg = ("座位号 %s 不存在于当前阅览室" % seat_input) if seat_input else "请先填写座位号"
            self.log("[预约失败] %s" % msg)

            return
        # 即刻预约 = 预约"今天"已选时间段, 开始时间早于当前时间则跳过
        if not self.time_segs:
            msg = "请先添加时间段(开始/结束时间)"
            self.log("[失败] %s" % msg)

            return
        now = M.datetime.now()
        now_min = now.hour * 60  # 向前取整到整点(如 7:03 → 7:00, 7:00 仍可预约)
        valid_segs, skipped = [], []
        for s, e in self.time_segs:
            if M._to_min(s) < now_min:
                skipped.append("%s-%s" % (s, e))
            else:
                valid_segs.append((s, e))
        if skipped:
            self.log("[跳过] 开始时间早于当前时间, 无法即刻预约: %s" % ", ".join(skipped))
        if not valid_segs:
            msg = "所有时间段开始时间都已早于当前时间, 无法即刻预约"
            self.log("[失败] %s" % msg)

            return

        self._set_status("即刻预约中...")
        def work():
            results = []
            for s, e in valid_segs:
                begin, dur = M.time_range_to_ts(0, s, e)
                r = M.do_book(self.cfg, begin, dur, seat_id)
                results.append((s, e, r))
            return results
        def done(results):
            ok = 0
            sid = M.current_student_id(self.cfg)
            for s, e, r in results:
                self.log("即刻预约 %s-%s: %s" % (s, e, M.json.dumps(r, ensure_ascii=False)[:180]))
                data = r.get("DATA", {}) if isinstance(r, dict) else {}
                if data.get("result") == "success":
                    ok += 1
                    status = "成功"
                    self.log("[预约成功] %s座 %s-%s (bookingId=%s)" % (
                        seat_num, s, e, data.get("bookingId")))
                else:
                    status = "失败: %s" % M.explain_failure(r)
                    self.log("[预约失败] %s座 %s-%s 原因: %s" % (
                        seat_num, s, e, M.explain_failure(r)))
                self._log_booking(sid, seat_num, self._current_region(),
                                  "今天 %s-%s" % (s, e), status,
                                  booking_id=data.get("bookingId") or "")
                if M.is_login_expired(r):
                    self.log("[!] 登录已失效(auth/uid 过期), 请重新抓包导入")
            if ok > 0:
                self._record_memory(seat_num)
            self._render_log()
            self._set_status("即刻预约完成: %d/%d 成功" % (ok, len(results)))
        self._run_async(work, done)

    def _on_book(self, days_ahead=1):
        if days_ahead == 1:
            self._schedule_book()   # 预约次日 = 定时预约(到 22:00 放号自动抢)
        else:
            self._book_tasks(days_ahead)

    def _schedule_book(self):
        """预约次日: 记录任务, 等到放号时间(默认 22:00)自动抢, 结果写日志。"""
        self._save_current_state()
        seat_id, seat_num = self._selected_seat()
        if not seat_id:
            seat_input = self.seat_var.get().strip()
            msg = ("座位号 %s 不存在于当前阅览室" % seat_input) if seat_input else "请先填写座位号"
            self.log("[预约失败] %s" % msg)
            return
        if not self.time_segs:
            msg = "请先添加时间段(开始/结束时间)"
            self.log("[预约失败] %s" % msg)
            return

        release = self.cfg.get("schedule", {}).get("release_time", "22:00:00")
        hh, mm, ss = (int(x) for x in release.split(":"))
        now = M.datetime.now()
        target = M.datetime(now.year, now.month, now.day, hh, mm, ss)
        if now >= target:
            # 已过今天的放号时间, 明天的座位已经放出, 立即预约
            wait = 0.0
        else:
            wait = (target - now).total_seconds()

        segs_str = "、".join("%s-%s" % (s, e) for s, e in self.time_segs)
        if wait > 0:
            self.log("[定时预约] 已记录: 明天 %s座 %s, 将在 %s 放号后自动抢" % (
                seat_num, segs_str, target.strftime("%H:%M:%S")))
            self._set_status("定时预约已记录, %s 自动抢明天 %s座" % (
                target.strftime("%H:%M:%S"), seat_num))
        else:
            self.log("[定时预约] 已到放号时间, 立即抢明天 %s座 %s" % (seat_num, segs_str))
            self._set_status("已到放号时间, 正在抢明天 %s座" % seat_num)

        def work():
            M.time.sleep(wait + 1.0)
            self.log("[定时预约] 到点, 开始抢明天 %s座..." % seat_num)
            results = []
            for s, e in self.time_segs:
                begin, dur = M.time_range_to_ts(1, s, e)
                r = M.do_book(self.cfg, begin, dur, seat_id)
                results.append((s, e, r))
            return results

        def done(results):
            ok = 0
            sid = M.current_student_id(self.cfg)
            for s, e, r in results:
                self.log("预约 %s-%s: %s" % (s, e, M.json.dumps(r, ensure_ascii=False)[:180]))
                data = r.get("DATA", {}) if isinstance(r, dict) else {}
                if data.get("result") == "success":
                    ok += 1
                    status = "成功"
                    self.log("[预约成功] %s座 %s-%s (bookingId=%s)" % (
                        seat_num, s, e, data.get("bookingId")))
                else:
                    status = "失败: %s" % M.explain_failure(r)
                    self.log("[预约失败] %s座 %s-%s 原因: %s" % (
                        seat_num, s, e, M.explain_failure(r)))
                self._log_booking(sid, seat_num, self._current_region(),
                                  "明天 %s-%s" % (s, e), status,
                                  booking_id=data.get("bookingId") or "")
                if M.is_login_expired(r):
                    self.log("[!] 登录已失效(auth/uid 过期), 请重新抓包导入")
            if ok > 0:
                self._record_memory(seat_num)
            self._render_log()
            self._set_status("定时预约完成: %d/%d 成功" % (ok, len(results)))

        self._run_async(work, done)

    # -- 本次会话预约记录 -------------------------------------------------
    def _log_booking(self, student_id, seat, region, time_seg, status, booking_id=""):
        """记录/更新一次预约操作。同一任务(学号+座位+时间段)只保留一行, 更新状态与时间。"""
        key = "%s|%s|%s" % (student_id, seat, time_seg)
        now = M.time.strftime("%Y-%m-%d %H:%M:%S")
        for item in self.booking_log:
            if item["key"] == key:
                item["status"] = status
                item["result_time"] = now
                item["region"] = region
                if booking_id:
                    item["booking_id"] = booking_id
                return
        self.booking_log.append({
            "key": key, "student_id": student_id, "seat": seat,
            "region": region, "time": time_seg, "status": status,
            "result_time": now, "booking_id": booking_id,
        })

    def _render_log(self):
        self.tree.delete(*self.tree.get_children())
        for item in self.booking_log:
            self.tree.insert("", "end", iid=item["key"], values=(
                item["student_id"], item["seat"], item.get("region", ""),
                item["time"], item["status"], item["result_time"]))

    def _on_cancel(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择要取消的预约")
            return
        key = sel[0]
        item = next((x for x in self.booking_log if x["key"] == key), None)
        if not item:
            return
        if not item.get("booking_id"):
            messagebox.showinfo("提示", "该记录没有可取消的预约(可能预约未成功)")
            return
        if not messagebox.askyesno("确认", "确定取消学号 %s 的预约(%s座 %s)吗?" % (
                item["student_id"], item["seat"], item["time"])):
            return
        sid, bid = item["student_id"], item["booking_id"]
        def work():
            return M.cancel_booking(self.cfg, bid, sid)
        def done(r):
            self.log("取消结果: %s" % M.json.dumps(r, ensure_ascii=False)[:200])
            data = r.get("DATA", {}) if isinstance(r, dict) else {}
            text = "%s %s" % (r.get("CODE", ""), r.get("MESSAGE", ""))
            if isinstance(data, dict):
                text += " %s" % data.get("msg", "")
            text_low = text.lower()
            # 取消成功: CODE=ok 或 提示含"取消"
            if "ok" in text_low or "取消" in text or "success" in text_low:
                item["status"] = "已取消"
                item["result_time"] = M.time.strftime("%Y-%m-%d %H:%M:%S")
                self.log("[已取消] 学号%s %s座 %s" % (
                    item["student_id"], item["seat"], item["time"]))
            else:
                self.log("[取消失败] 学号%s %s座 %s 原因: %s" % (
                    item["student_id"], item["seat"], item["time"],
                    M.explain_failure(r)))
            self._render_log()
        self._run_async(work, done)

    def _on_close(self):
        self._save_current_state()
        M.save_config(self.cfg)
        self.destroy()


def main():
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
