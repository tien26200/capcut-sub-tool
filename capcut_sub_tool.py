import json
import re
import os
import shutil
import threading
from datetime import datetime
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
import customtkinter as ctk

import matplotlib.font_manager as fm


def rgba(hex_code):
    value = hex_code.lstrip("#")
    return [round(int(value[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)] + [1.0]


def discover_projects():
    roots = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.extend([
            Path(local) / "CapCut" / "User Data" / "Projects",
            Path(local) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft",
            Path(local) / "JianyingPro" / "User Data" / "Projects",
        ])
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "CapCut" / "User Data" / "Projects")
    found = []
    for root in roots:
        if root.exists():
            try:
                found.extend(root.rglob("draft_content.json"))
            except OSError:
                continue
    return sorted({p.resolve() for p in found if p.is_file()}, key=lambda p: p.stat().st_mtime, reverse=True)


def draft_media(draft_path):
    """Return video source files and the first timeline placement for each source."""
    with open(draft_path, "r", encoding="utf-8-sig") as stream:
        draft = json.load(stream)
    materials = draft.get("materials", {})
    videos = materials.get("videos", []) if isinstance(materials, dict) else []
    if not isinstance(videos, list):
        videos = []
    by_id = {v.get("id"): v for v in videos if isinstance(v, dict) and v.get("id")}
    placements = []
    tracked_paths = set()
    for track in draft.get("tracks", []):
        if not isinstance(track, dict):
            continue
        for segment in track.get("segments", []):
            material = by_id.get(segment.get("material_id"))
            if not material:
                continue
            source = material.get("path") or material.get("material_path") or material.get("file_path")
            if not source:
                continue
            timerange = segment.get("target_timerange", {}) or {}
            source_range = segment.get("source_timerange", {}) or {}
            placements.append({
                "path": source,
                "timeline_start": int(timerange.get("start", 0)),
                "source_start": int(source_range.get("start", 0)),
                "duration": int(source_range.get("duration", timerange.get("duration", 0))),
            })
            tracked_paths.add(os.path.normcase(os.path.normpath(source)))
    # Some drafts only expose media paths without segment references.
    for material in videos:
        if isinstance(material, dict):
            source = material.get("path") or material.get("material_path") or material.get("file_path")
            if source and os.path.normcase(os.path.normpath(source)) not in tracked_paths:
                placements.append({
                    "path": source, "timeline_start": 0, "source_start": 0, "duration": 0,
                })
                tracked_paths.add(os.path.normcase(os.path.normpath(source)))
    return draft, placements


def chunk_words(words, mode, limit):
    if not words:
        return []
    if mode == "Từng từ (karaoke)":
        return [[w] for w in words]
    if mode == "Theo câu":
        groups, current = [], []
        for word in words:
            current.append(word)
            if word["text"].rstrip().endswith((".", "!", "?", ";", ":")):
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups
    if mode == "Theo dấu câu":
        groups, current = [], []
        for word in words:
            current.append(word)
            if word["text"].rstrip().endswith((",", ".", "!", "?", ";", ":")):
                groups.append(current)
                current = []
        if current:
            groups.append(current)
        return groups
    if mode == "Theo số từ":
        return [words[i:i + limit] for i in range(0, len(words), limit)]
    if mode == "Theo thời lượng":
        groups, current = [], []
        for word in words:
            if current and word["end"] - current[0]["start"] > limit:
                groups.append(current)
                current = []
            current.append(word)
        if current:
            groups.append(current)
        return groups
    # Character-based mode: break before a long line, keeping a practical word cap.
    groups, current, chars = [], [], 0
    for word in words:
        length = len(word["text"].strip())
        if current and (chars + length + 1 > limit or len(current) >= 14):
            groups.append(current)
            current, chars = [], 0
        current.append(word)
        chars += length + (1 if len(current) > 1 else 0)
    if current:
        groups.append(current)
    return groups


def make_subtitles(words, mode, limit, color_mode):
    result = []
    groups = chunk_words(words, mode, limit)
    for index, group in enumerate(groups):
        result.append({"text": " ".join(w["text"].strip() for w in group).upper(),
                       "start_us": int(group[0]["start"] * 1e6), "end_us": int(group[-1]["end"] * 1e6),
                       "color_index": index if color_mode == "Đổi màu theo cụm" else 0})
    return result


def inject_to_capcut(draft_path, subtitles, font_name, colors):
    with open(draft_path, "r", encoding="utf-8-sig") as stream:
        draft = json.load(stream)
    draft.setdefault("materials", {}).setdefault("texts", [])
    draft.setdefault("tracks", [])
    track = {"id": str(uuid.uuid4()), "type": "text", "segments": [], "attribute": 0, "flag": 0}
    for item in subtitles:
        text_id, segment_id = str(uuid.uuid4()), str(uuid.uuid4())
        color = rgba(colors[item.get("color_index", 0) % len(colors)])
        duration = max(1, item["end_us"] - item["start_us"])
        actual_font_path = fm.findfont(font_name, fallback_to_default=True)
        style = {"fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"color": color[:3]}}},
                 "range": [0, len(item["text"])], "size": 8.0,
                 "font": {"path": actual_font_path, "name": font_name}}
        material = {"id": text_id, "type": "text",
                    "content": json.dumps({"styles": [style], "text": item["text"]}, ensure_ascii=False),
                    "font_path": actual_font_path, "text_color": color, "border_color": [0, 0, 0, 1],
                    "border_width": 15.0, "shadow_color": [0, 0, 0, 0.8], "shadow_alpha": 0.8,
                    "shadow_point": {"x": 5.0, "y": -5.0}, "alignment": 1, "typesetting": 0}
        draft["materials"]["texts"].append(material)
        track["segments"].append({"id": segment_id, "material_id": text_id, "render_index": 0,
                                  "target_timerange": {"start": item["start_us"], "duration": duration},
                                  "source_timerange": {"start": 0, "duration": duration}, "speed": 1.0, "volume": 1.0})
    draft["tracks"].append(track)
    backup = draft_path + ".backup"
    if os.path.exists(backup):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = draft_path + f".{stamp}.backup"
    shutil.copy2(draft_path, backup)
    temp_path = draft_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as stream:
        json.dump(draft, stream, ensure_ascii=False, indent=2)
    os.replace(temp_path, draft_path)
    return backup


class App(ctk.CTk):
    def __init__(self):
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        super().__init__()
        self.title("CapCut Subtitle Assistant")
        self.geometry("1040x820")
        self.minsize(880, 640)
        self.configure(fg_color="#F3F6FB")
        self.projects = {}
        self.project_paths = []
        self.media_items = []
        self.media_labels = []
        self.colors = ["#FFFFFF", "#FFE600", "#FF2A54"]
        self.pointer_active = False
        self.detected_target = None
        self._build_ui()
        self.refresh_projects()

    def _card(self, parent, title, subtitle=None):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color="#FFFFFF", border_width=1, border_color="#E4EAF3")
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 14, "bold"), text_color="#18243A").pack(anchor="w", padx=16, pady=(14, 0))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, font=("Segoe UI", 11), text_color="#718096", wraplength=460, justify="left").pack(anchor="w", padx=16, pady=(3, 9))
        return card

    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=22, pady=(16, 12))
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(1, weight=1)
        header = ctk.CTkFrame(root, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(header, text="CC", font=("Segoe UI", 13, "bold"), text_color="#FFFFFF",
                     fg_color="#2864DC", corner_radius=11, width=46, height=42).pack(side="left", padx=(0, 12))
        title_box = ctk.CTkFrame(header, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_box, text="Tạo phụ đề cho CapCut", font=("Segoe UI", 22, "bold"), text_color="#17243A").pack(anchor="w")
        ctk.CTkLabel(title_box, text="Chọn dự án, tùy chỉnh cách chia, rồi bắt đầu xử lý.",
                     font=("Segoe UI", 12), text_color="#6B7890").pack(anchor="w")
        ctk.CTkLabel(header, text="BẢN DESKTOP", font=("Segoe UI", 10, "bold"), text_color="#60708A",
                     fg_color="#E8EDF5", corner_radius=10, width=110, height=30).pack(side="right")

        body = ctk.CTkScrollableFrame(root, fg_color="transparent", corner_radius=0,
                                      scrollbar_button_color="#C9D3E2", scrollbar_button_hover_color="#9DACC2")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1, uniform="cards")
        body.grid_columnconfigure(1, weight=1, uniform="cards")

        project = self._card(body, "01  ·  Dự án", "Kéo nút ngắm vào cửa sổ CapCut để chọn dự án đang mở.")
        project.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 12))
        prow = ctk.CTkFrame(project, fg_color="transparent"); prow.pack(fill="x", padx=14, pady=(0, 8))
        self.aim_handle = ctk.CTkLabel(prow, text="⌖  KÉO TỚI CAPCUT", width=160, height=38, corner_radius=11,
                                       fg_color="#E8F0FF", text_color="#2458C5",
                                       font=("Segoe UI", 11, "bold"), cursor="hand2")
        self.aim_handle.pack(side="left", padx=(0, 8))
        self.aim_handle.bind("<ButtonPress-1>", self.begin_pointer_pick)
        ctk.CTkButton(prow, text="Quét", width=64, height=38, corner_radius=10, command=self.refresh_projects).pack(side="left")
        ctk.CTkButton(prow, text="Thư mục…", width=92, height=38, corner_radius=10, fg_color="#EEF2F8",
                      hover_color="#DFE6F1", text_color="#2B3952", command=self.choose_project).pack(side="left", padx=(8, 0))
        self.project_cb = ctk.CTkComboBox(project, values=[], command=self._project_changed, state="readonly", corner_radius=10, height=36)
        self.project_cb.pack(fill="x", padx=14, pady=(2, 8))
        self.target_info = ctk.CTkLabel(project, text="Chưa chọn cửa sổ CapCut.", font=("Segoe UI", 10), text_color="#6B7890", anchor="w", justify="left", wraplength=430)
        self.target_info.pack(fill="x", padx=16, pady=(0, 12))

        source = self._card(body, "02  ·  Clip trên timeline", "Nguồn và vị trí đọc từ draft đã lưu trong dự án.")
        source.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 12))
        self.media_cb = ctk.CTkComboBox(source, values=[], state="readonly", corner_radius=10, height=38)
        self.media_cb.pack(fill="x", padx=14, pady=(1, 8))
        self.project_info = ctk.CTkLabel(source, text="Chờ chọn dự án…", font=("Segoe UI", 10), text_color="#718096", anchor="w", justify="left", wraplength=430)
        self.project_info.pack(fill="x", padx=16, pady=(0, 12))

        opts = self._card(body, "03  ·  Cách chia phụ đề", "Chọn kiểu tách và điều chỉnh giới hạn khi cần.")
        opts.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 12))
        ctk.CTkLabel(opts, text="KIỂU TÁCH", font=("Segoe UI", 10, "bold"), text_color="#718096").pack(anchor="w", padx=16, pady=(1, 5))
        self.mode = ctk.CTkOptionMenu(opts, values=["Theo câu", "Theo dấu câu", "Theo số từ", "Theo ký tự", "Theo thời lượng", "Từng từ (karaoke)"], corner_radius=10, height=38, command=self._mode_changed)
        self.mode.set("Theo số từ"); self.mode.pack(fill="x", padx=14, pady=(0, 10))
        limit_row = ctk.CTkFrame(opts, fg_color="#F5F7FB", corner_radius=11)
        limit_row.pack(fill="x", padx=14, pady=(0, 11))
        self.limit_label = ctk.CTkLabel(limit_row, text="Số từ trong mỗi cụm", text_color="#43516A", font=("Segoe UI", 11))
        self.limit_label.pack(side="left", padx=11, pady=8)
        self.limit = ctk.CTkOptionMenu(limit_row, values=[str(n) for n in range(2, 15)], width=94, corner_radius=9, height=32, command=self._refresh_sample)
        self.limit.set("6"); self.limit.pack(side="right", padx=7, pady=6)
        ctk.CTkLabel(opts, text="NGÔN NGỮ VÀ MÀU", font=("Segoe UI", 10, "bold"), text_color="#718096").pack(anchor="w", padx=16, pady=(0, 5))
        setting_row = ctk.CTkFrame(opts, fg_color="transparent"); setting_row.pack(fill="x", padx=14, pady=(0, 12))
        self.color_mode = ctk.CTkOptionMenu(setting_row, values=["Một màu", "Đổi màu theo cụm"], corner_radius=10, height=34, command=self._refresh_sample)
        self.color_mode.set("Một màu"); self.color_mode.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.language = ctk.CTkOptionMenu(setting_row, values=["Tự nhận diện", "Tiếng Việt", "English"], corner_radius=10, height=34)
        self.language.set("Tiếng Việt"); self.language.pack(side="left", fill="x", expand=True, padx=(6, 0))

        appearance = self._card(body, "04  ·  Studio chữ", "Chọn font, phối màu và xem mẫu ngay bên dưới.")
        appearance.grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(0, 12))
        arow = ctk.CTkFrame(appearance, fg_color="transparent"); arow.pack(fill="x", padx=14, pady=(4, 12))
        self.fonts = sorted({f.name for f in fm.fontManager.ttflist}) or ["Arial"]
        ctk.CTkLabel(arow, text="TÌM FONT", font=("Segoe UI", 10, "bold"), text_color="#718096").pack(anchor="w")
        self.font_search = ctk.StringVar()
        ctk.CTkEntry(arow, textvariable=self.font_search, placeholder_text="Tìm font theo tên…", height=36, corner_radius=10).pack(fill="x", pady=(0, 6))
        self.font_cb = ctk.CTkComboBox(arow, values=self.fonts, state="readonly", corner_radius=10, height=36, command=self._refresh_sample)
        self.font_cb.set("Arial" if "Arial" in self.fonts else self.fonts[0])
        self.font_cb.pack(fill="x", pady=(0, 4))
        self.font_results = ctk.CTkLabel(arow, text=f"{len(self.fonts)} font trên máy", text_color="#718096", font=("Segoe UI", 10))
        self.font_results.pack(anchor="w", pady=(0, 8))
        self.font_search.trace_add("write", self._filter_fonts)
        color_row = ctk.CTkFrame(arow, fg_color="transparent"); color_row.pack(fill="x")
        self.color_buttons = []
        for i, color in enumerate(self.colors):
            button = ctk.CTkButton(color_row, text=f"{i+1} · {color}", width=90, height=36, corner_radius=10,
                                   fg_color=color, hover_color=color, text_color="#202838" if color in ("#FFFFFF", "#FFE600") else "#FFFFFF",
                                   border_width=1, border_color="#D7DEEA", command=lambda j=i: self.pick_color(j))
            button.pack(side="left", fill="x", expand=True, padx=3); self.color_buttons.append(button)

        sample = ctk.CTkFrame(appearance, fg_color="transparent")
        sample.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sample, text="MẪU MINH HỌA · THỜI GIAN GIẢ LẬP", text_color="#718096", font=("Segoe UI", 10)).pack(anchor="w", padx=16, pady=(0, 6))
        stage = ctk.CTkFrame(sample, fg_color="#111C30", corner_radius=14)
        stage.pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkLabel(stage, text="SUBTITLE PREVIEW", text_color="#8D9DB8", font=("Segoe UI", 10, "bold")).pack(pady=(12, 4))
        self.sample_text = ctk.CTkLabel(stage, text="", height=90, wraplength=340, font=("Arial", 22), text_color=self.colors[0])
        self.sample_text.pack(fill="x", padx=20, pady=(0, 12))
        nav = ctk.CTkFrame(sample, fg_color="transparent")
        nav.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkButton(nav, text="←", width=38, height=30, command=lambda: self._step_sample(-1)).pack(side="left")
        self.sample_info = ctk.CTkLabel(nav, text="", font=("Segoe UI", 10), text_color="#62718A", wraplength=260)
        self.sample_info.pack(side="left", expand=True, fill="x", padx=8)
        ctk.CTkButton(nav, text="→", width=38, height=30, command=lambda: self._step_sample(1)).pack(side="right")
        self.sample_index = 0
        self.sample_subs = []

        script_card = self._card(body, "05  ·  Kịch bản tùy chọn", "Để trống để dùng lời nhận diện. Kịch bản chỉ thay chữ khi số từ khớp.")
        script_card.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
        self.script = ctk.CTkTextbox(script_card, height=82, corner_radius=10, border_width=1, border_color="#E4EAF3", wrap="word")
        self.script.pack(fill="x", padx=14, pady=(0, 12))

        # Fixed action bar stays visible regardless of the scroll position.
        footer = ctk.CTkFrame(root, fg_color="#FFFFFF", corner_radius=16, border_width=1, border_color="#E0E7F0")
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        footer.grid_columnconfigure(0, weight=1, minsize=150)
        left = ctk.CTkFrame(footer, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=14, pady=11)
        self.status = ctk.CTkLabel(left, text="Sẵn sàng", text_color="#62718A", anchor="w", justify="left", wraplength=320, font=("Segoe UI", 11))
        self.status.pack(fill="x")
        self.progress = ctk.CTkProgressBar(left, height=5, corner_radius=5, progress_color="#2864DC")
        self.progress.pack(fill="x", pady=(7, 0)); self.progress.set(0)
        self.preview_btn = ctk.CTkButton(footer, text="Xem trước", height=42, width=110, corner_radius=11,
                                         fg_color="#E9EEF8", hover_color="#DDE6F5", text_color="#2A3C5D", command=self.preview)
        self.preview_btn.grid(row=0, column=1, padx=(6, 10), pady=10)
        self.go_btn = ctk.CTkButton(footer, text="▶  BẮT ĐẦU TẠO PHỤ ĐỀ", height=42, width=218, corner_radius=11,
                                    font=("Segoe UI", 12, "bold"), command=self.start)
        self.go_btn.grid(row=0, column=2, padx=(0, 14), pady=10)
        self._mode_changed(self.mode.get())

    def _mode_changed(self, value):
        values = []
        if value == "Theo số từ":
            self.limit_label.configure(text="Số từ trong mỗi cụm")
            values = [str(n) for n in range(2, 15)]
            current, default = self.limit.get(), "6"
        elif value == "Theo ký tự":
            self.limit_label.configure(text="Ký tự tối đa mỗi dòng")
            values = [str(n) for n in range(20, 81, 2)]
            current, default = self.limit.get(), "38"
        elif value == "Theo thời lượng":
            self.limit_label.configure(text="Thời lượng tối đa (giây)")
            values = ["1.0", "1.5", "2.0", "2.5", "3.0", "4.0"]
            current, default = self.limit.get(), "2.0"
        else:
            self.limit_label.configure(text="Không cần giới hạn cho kiểu này")
            values = ["—"]
            current, default = "—", "—"
        self.limit.configure(values=values, state="normal" if len(values) > 1 else "disabled")
        self.limit.set(current if current in values else default)
        self._refresh_sample()

    def begin_pointer_pick(self, _event=None):
        if os.name != "nt":
            messagebox.showinfo("Chọn CapCut", "Kéo chọn cửa sổ bằng con trỏ hiện chỉ hỗ trợ Windows.", parent=self)
            return
        self.pointer_active = True
        self.pointer_coords = None
        self.aim_handle.configure(text="ĐANG KÉO… THẢ TRÊN CAPCUT", fg_color="#DCE8FF")
        self.status.configure(text="Kéo dấu ngắm vào vùng dự án CapCut rồi thả chuột.")
        self.after(100, self._hide_and_track_pointer)

    def _hide_and_track_pointer(self):
        if not self.pointer_active:
            return
        self.withdraw()
        self._poll_pointer()

    def _poll_pointer(self):
        if not self.pointer_active:
            return
        try:
            import ctypes
            from ctypes import wintypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
            point = POINT()
            user32 = ctypes.windll.user32
            user32.GetCursorPos(ctypes.byref(point))
            if user32.GetAsyncKeyState(0x01) & 0x8000:
                self.pointer_coords = (point.x, point.y)
                self.after(35, self._poll_pointer)
            else:
                x, y = getattr(self, "pointer_coords", (point.x, point.y))
                self.pointer_active = False
                self.deiconify(); self.lift()
                self._resolve_pointer_target(x, y)
        except Exception as exc:
            self.pointer_active = False
            self.deiconify(); self.lift()
            self.aim_handle.configure(text="⌖  KÉO TỚI CAPCUT", fg_color="#E8F0FF")
            messagebox.showerror("Không lấy được vị trí con trỏ", str(exc), parent=self)

    def _resolve_pointer_target(self, x, y):
        import ctypes
        from ctypes import wintypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.argtypes = [POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        hwnd = user32.WindowFromPoint(POINT(x, y))
        hwnd = user32.GetAncestor(hwnd, 2) or hwnd
        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        kernel = ctypes.windll.kernel32
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                       ctypes.POINTER(wintypes.DWORD)]
        kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        process = kernel.OpenProcess(0x1000, False, pid.value)
        exe = ""
        if process:
            exe_buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(exe_buf))
            if kernel.QueryFullProcessImageNameW(process, 0, exe_buf, ctypes.byref(size)):
                exe = exe_buf.value
            kernel.CloseHandle(process)
        title = title_buf.value or "(không có tiêu đề)"
        if "capcut" not in Path(exe).name.lower() and "jianying" not in Path(exe).name.lower() and "capcut" not in title.lower():
            self.aim_handle.configure(text="⌖  KÉO TỚI CAPCUT", fg_color="#E8F0FF")
            self.target_info.configure(text=f"Con trỏ ở ({x}, {y}) nhưng cửa sổ được chọn không phải CapCut: {title}")
            self.status.configure(text="Chưa nhận diện được cửa sổ CapCut. Thử kéo vào vùng timeline/project trong CapCut.")
            return
        self.detected_target = {"title": title, "exe": exe, "x": x, "y": y}
        self.target_info.configure(text=f"CapCut: {title}  ·  tọa độ màn hình ({x}, {y})")
        self.aim_handle.configure(text="✓  ĐÃ CHỌN CAPCUT", fg_color="#DFF5E8", text_color="#176B3A")
        self._choose_recent_project(title)

    def _choose_recent_project(self, window_title):
        files = discover_projects()
        if not files:
            self.status.configure(text="Đã nhận diện CapCut nhưng chưa tìm thấy draft đã lưu. Lưu project rồi bấm Quét.")
            return
        title = window_title.casefold()
        chosen = files[0]
        for draft_path in files:
            try:
                with open(draft_path, "r", encoding="utf-8-sig") as f:
                    draft = json.load(f)
                possible = [draft.get("draft_name"), draft.get("name"), draft.get("project_name"), draft_path.parent.name]
                possible += [draft.get("draft_info", {}).get("draft_name")] if isinstance(draft.get("draft_info"), dict) else []
                if any(name and str(name).casefold() in title for name in possible):
                    chosen = draft_path
                    break
            except (OSError, ValueError):
                continue
        key = str(chosen.resolve())
        label = self._register_project(key)
        self.project_cb.set(label)
        self.load_project()
        # The pointer identifies the CapCut window; use its first valid timeline clip automatically.
        valid = next((i for i, item in enumerate(self.media_items) if os.path.isfile(item["path"])), None)
        if valid is not None:
            self.media_cb.set(self.media_labels[valid])
        self.status.configure(text="Đã chọn CapCut và ghép draft đã lưu gần nhất. Kiểm tra tên project và clip trước khi tạo phụ đề.")

    def _project_changed(self, value):
        self.load_project()

    def _register_project(self, path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                draft = json.load(f)
            name = draft.get("draft_name") or draft.get("name") or draft.get("project_name")
        except (OSError, ValueError):
            name = None
        name = str(name or Path(path).parent.name)
        label = name
        suffix = 2
        while label in self.projects and self.projects[label] != path:
            label = f"{name} ({suffix})"
            suffix += 1
        self.projects[label] = path
        if label not in self.project_paths:
            self.project_paths.append(label)
        return label

    def refresh_projects(self):
        files = discover_projects()
        self.projects = {}
        self.project_paths = []
        self.project_paths = [self._register_project(str(p)) for p in files]
        self.project_cb.configure(values=self.project_paths)
        if files:
            self.project_cb.set(self.project_paths[0]); self.load_project()
            self.status.configure(text=f"Đã tìm thấy {len(files)} dự án CapCut")
        else:
            self.status.configure(text="Chưa tìm thấy dự án tự động; hãy chọn thư mục dự án.")

    def choose_project(self):
        folder = filedialog.askdirectory(title="Chọn thư mục dự án CapCut")
        if not folder: return
        candidates = list(Path(folder).rglob("draft_content.json"))
        if not candidates:
            messagebox.showerror("Không tìm thấy draft", "Thư mục này không có draft_content.json.")
            return
        p = max(candidates, key=lambda x: x.stat().st_mtime)
        key = str(p.resolve())
        label = self._register_project(key)
        self.project_cb.configure(values=self.project_paths); self.project_cb.set(label); self.load_project()

    def load_project(self, _event=None):
        path = self.projects.get(self.project_cb.get(), "")
        if not path: return
        try:
            _, self.media_items = draft_media(path)
            labels = []
            for item in self.media_items:
                exists = os.path.isfile(item["path"])
                start = item["timeline_start"] / 1e6
                label = f"{'✓' if exists else '⚠'} {Path(item['path']).name} | timeline {start:.2f}s | source {item['source_start']/1e6:.2f}s"
                labels.append(label)
            self.media_labels = labels
            self.media_cb.configure(values=labels)
            if labels: self.media_cb.set(labels[0])
            self.project_info.configure(text=f"Đã đọc {len(labels)} clip từ draft. Dấu ✓ là nguồn video còn tìm thấy trên máy.")
        except Exception as exc:
            messagebox.showerror("Không đọc được dự án", str(exc), parent=self)

    def _filter_fonts(self, *_args):
        query = self.font_search.get().strip().casefold()
        matches = [name for name in self.fonts if query in name.casefold()]
        self.font_cb.configure(values=matches, state="readonly" if matches else "disabled")
        self.font_results.configure(text=f"{len(matches)} font phù hợp · mở danh sách để chọn" if matches else "Không tìm thấy font · thử tên khác")

    def _refresh_sample(self, _value=None):
        if not hasattr(self, "sample_text"):
            return
        text = "Xin chào, đây là mẫu phụ đề của bạn. Hãy chọn cách chia và màu chữ phù hợp với video!"
        words = [{"text": word, "start": i * 0.4, "end": (i + 1) * 0.4} for i, word in enumerate(text.split())]
        mode = self.mode.get()
        value = self.limit.get()
        limit = float(value) if mode == "Theo thời lượng" else int(value) if mode in ("Theo số từ", "Theo ký tự") else 38
        self.sample_subs = make_subtitles(words, mode, limit, self.color_mode.get())
        self.sample_index = 0
        self._render_sample()

    def _step_sample(self, delta):
        if self.sample_subs:
            self.sample_index = (self.sample_index + delta) % len(self.sample_subs)
            self._render_sample()

    def _render_sample(self):
        if not self.sample_subs:
            return
        sub = self.sample_subs[self.sample_index]
        self.sample_text.configure(text=sub["text"], font=(self.font_cb.get(), 22),
                                   text_color=self.colors[sub["color_index"] % len(self.colors)])
        self.sample_info.configure(text=f"Cụm {self.sample_index + 1}/{len(self.sample_subs)} · {self.mode.get()} · {self.font_cb.get()}")

    @staticmethod
    def _color_ink(color):
        r, g, b = [int(color[i:i+2], 16) for i in (1, 3, 5)]
        return "#18243A" if 0.299*r + 0.587*g + 0.114*b > 155 else "#FFFFFF"

    def _set_color(self, index, color):
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Nhập màu dạng #RRGGBB")
        int(color[1:], 16)
        color = color.upper()
        self.colors[index] = color
        self.color_buttons[index].configure(text=f"{index+1} · {color}", fg_color=color, hover_color=color, text_color=self._color_ink(color))
        self._render_sample()

    def pick_color(self, index):
        win = ctk.CTkToplevel(self)
        win.title(f"Màu phụ đề {index + 1}")
        win.geometry("460x510")
        win.resizable(False, False)
        win.transient(self)
        win.after(150, win.grab_set)
        win.configure(fg_color="#F3F6FB")
        ctk.CTkLabel(win, text="Phối màu phụ đề", font=("Segoe UI", 21, "bold"), text_color="#18243A").pack(anchor="w", padx=22, pady=(18, 10))
        demo = ctk.CTkLabel(win, text="MẪU PHỤ ĐỀ CỦA BẠN", font=(self.font_cb.get(), 21),
                            fg_color="#111C30", text_color=self.colors[index], corner_radius=14, height=100, wraplength=380)
        demo.pack(fill="x", padx=20, pady=(0, 12))
        value = ctk.StringVar(value=self.colors[index])
        entry = ctk.CTkEntry(win, textvariable=value, height=36, corner_radius=10)
        entry.pack(fill="x", padx=20, pady=(0, 8))
        error = ctk.CTkLabel(win, text="HEX · nhập #RRGGBB hoặc kéo thanh RGB", text_color="#718096", font=("Segoe UI", 11))
        error.pack()
        sliders = []
        def slide(_value=None):
            value.set("#" + "".join(f"{round(slider.get()):02X}" for slider in sliders))
        for channel, offset in zip(("R", "G", "B"), (1, 3, 5)):
            row = ctk.CTkFrame(win, fg_color="transparent")
            row.pack(fill="x", padx=20, pady=6)
            ctk.CTkLabel(row, text=channel, width=24).pack(side="left")
            slider = ctk.CTkSlider(row, from_=0, to=255, number_of_steps=255, command=slide)
            slider.set(int(self.colors[index][offset:offset+2], 16))
            slider.pack(side="left", expand=True, fill="x", padx=8)
            sliders.append(slider)
        def update(*_args):
            color = value.get().strip()
            try:
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise ValueError()
                int(color[1:], 16)
                demo.configure(text_color=color)
                for slider, offset in zip(sliders, (1, 3, 5)):
                    slider.set(int(color[offset:offset+2], 16))
                error.configure(text="Màu hợp lệ · mẫu cập nhật trực tiếp", text_color="#176B3A")
                apply_btn.configure(state="normal")
            except ValueError:
                error.configure(text="Mã màu cần đủ 6 ký tự: #RRGGBB", text_color="#CB344D")
                apply_btn.configure(state="disabled")
        palette = ctk.CTkFrame(win, fg_color="transparent")
        palette.pack(pady=10)
        for color in ("#FFFFFF", "#FFE600", "#FF2A54", "#35D9AD", "#70B7FF", "#C599FF"):
            ctk.CTkButton(palette, text="", width=48, height=30, corner_radius=8, fg_color=color, hover_color=color,
                          command=lambda c=color: value.set(c)).pack(side="left", padx=4)
        actions = ctk.CTkFrame(win, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=12)
        def apply():
            self._set_color(index, value.get().strip())
            win.destroy()
        ctk.CTkButton(actions, text="Hủy", width=100, fg_color="#DFE6F1", text_color="#18243A", command=win.destroy).pack(side="left")
        apply_btn = ctk.CTkButton(actions, text="Áp dụng màu", command=apply)
        apply_btn.pack(side="right")
        value.trace_add("write", update)

    def selected_media(self):
        try:
            index = self.media_labels.index(self.media_cb.get())
        except ValueError:
            raise ValueError("Chọn clip trong danh sách trước khi tiếp tục.")
        if index < 0 or index >= len(self.media_items): raise ValueError("Dự án không có clip video để xử lý.")
        item = self.media_items[index]
        if not os.path.isfile(item["path"]): raise ValueError("Không tìm thấy file video nguồn trên máy:\n" + item["path"])
        return item

    def collect_settings(self):
        item = dict(self.selected_media())
        mode = self.mode.get()
        selected_limit = self.limit.get()
        return {"media": item, "mode": mode,
                "word_limit": int(selected_limit) if mode == "Theo số từ" else 6,
                "char_limit": int(selected_limit) if mode == "Theo ký tự" else 38,
                "duration_limit": float(selected_limit) if mode == "Theo thời lượng" else 2.0,
                "color_mode": self.color_mode.get(),
                "script": self.script.get("1.0", "end"), "font": self.font_cb.get(), "colors": list(self.colors),
                "language": {"Tiếng Việt": "vi", "English": "en"}.get(self.language.get())}

    def build_subs(self, settings):
        item = settings["media"]
        from faster_whisper import WhisperModel
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(item["path"], word_timestamps=True,
                                       language=settings["language"], vad_filter=True)
        words = []
        source_start = item["source_start"] / 1e6
        source_end = source_start + item["duration"] / 1e6 if item["duration"] else None
        offset = item["timeline_start"] / 1e6 - source_start
        for segment in segments:
            for word in segment.words or []:
                if source_end and (word.end <= source_start or word.start >= source_end): continue
                start = max(word.start, source_start)
                end = min(word.end, source_end) if source_end else word.end
                words.append({"text": word.word, "start": max(0, start + offset), "end": max(0.01, end + offset)})
        script = [line.strip() for line in settings["script"].splitlines() if line.strip()]
        warning = ""
        if script:
            # Preserve word timing from recognition; replace text only when token counts agree.
            tokens = " ".join(script).split()
            if len(tokens) == len(words):
                for word, token in zip(words, tokens): word["text"] = token
            else:
                warning = f"Số từ kịch bản ({len(tokens)}) khác số từ nhận diện ({len(words)}); đã dùng lời nhận diện để tránh lệch thời gian. "
        limit = settings["word_limit"] if settings["mode"] == "Theo số từ" else (
            settings["duration_limit"] if settings["mode"] == "Theo thời lượng" else settings["char_limit"])
        return make_subtitles(words, settings["mode"], limit, settings["color_mode"]), warning

    def preview(self):
        try:
            settings = self.collect_settings()
            self.status.configure(text="Đang nhận diện để tạo bản xem trước…")
            self.progress.start()
            self.go_btn.configure(state="disabled"); self.preview_btn.configure(state="disabled")
            threading.Thread(target=self._preview_worker, args=(settings,), daemon=True).start()
        except Exception as exc: messagebox.showerror("Lỗi", str(exc), parent=self)

    def _preview_worker(self, settings):
        try:
            subs, warning = self.build_subs(settings)
            lines = [f"{s['start_us']/1e6:7.2f}s  {s['text']}" for s in subs[:120]]
            self.after(0, lambda: self._show_preview(subs, lines, warning))
        except Exception as exc: self.after(0, lambda: self._finish(str(exc), error=True))

    def _show_preview(self, subs, lines, warning):
        win = ctk.CTkToplevel(self); win.title(f"Xem trước — {len(subs)} phụ đề"); win.geometry("680x540")
        box = ctk.CTkTextbox(win, wrap="none", corner_radius=12); box.pack(fill="both", expand=True, padx=14, pady=14)
        box.insert("1.0", "\n".join(lines)); box.configure(state="disabled")
        ctk.CTkLabel(win, text="Hiển thị tối đa 120 dòng đầu · thời gian đã căn theo vị trí clip trên timeline.",
                     text_color="#62718A").pack(pady=(0, 12))
        self._finish(f"{warning}Xem trước xong: {len(subs)} cụm phụ đề")

    def start(self):
        try:
            path = self.projects.get(self.project_cb.get(), "")
            if not path or not os.path.isfile(path): raise ValueError("Hãy chọn dự án CapCut trước.")
            settings = self.collect_settings()
            if messagebox.askyesno("Ghi phụ đề vào dự án?", "App sẽ tạo bản sao .backup rồi thêm track phụ đề vào draft_content.json. Hãy đóng dự án trong CapCut trước khi tiếp tục.", parent=self):
                self.go_btn.configure(state="disabled"); self.preview_btn.configure(state="disabled")
                self.status.configure(text="Đang nhận diện và căn theo clip/tọa độ timeline…")
                self.progress.start()
                threading.Thread(target=self._worker, args=(path, settings), daemon=True).start()
        except Exception as exc: messagebox.showerror("Thiếu thông tin", str(exc), parent=self)

    def _worker(self, path, settings):
        try:
            subtitles, warning = self.build_subs(settings)
            backup = inject_to_capcut(path, subtitles, settings["font"], settings["colors"])
            self.after(0, lambda: self._finish(f"{warning}Đã thêm {len(subtitles)} phụ đề. Bản sao lưu: {backup}"))
        except Exception as exc: self.after(0, lambda: self._finish(str(exc), error=True))

    def _finish(self, text, error=False):
        self.progress.stop()
        self.progress.set(0)
        self.status.configure(text=text)
        self.go_btn.configure(state="normal"); self.preview_btn.configure(state="normal")
        if error: messagebox.showerror("Không hoàn tất", text, parent=self)


if __name__ == "__main__":
    App().mainloop()
