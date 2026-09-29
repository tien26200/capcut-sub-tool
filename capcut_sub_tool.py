import json
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
        self.geometry("1020x880")
        self.minsize(900, 760)
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
        card.pack(fill="x", pady=6)
        ctk.CTkLabel(card, text=title, font=("Segoe UI", 14, "bold"), text_color="#18243A").pack(anchor="w", padx=16, pady=(12, 0))
        if subtitle:
            ctk.CTkLabel(card, text=subtitle, font=("Segoe UI", 11), text_color="#718096", wraplength=920, justify="left").pack(anchor="w", padx=16, pady=(2, 8))
        return card

    def _build_ui(self):
        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=22, pady=18)
        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(header, text="CAPCUT", font=("Segoe UI", 11, "bold"), text_color="#FFFFFF",
                     fg_color="#2864DC", corner_radius=10, width=78, height=32).pack(side="left", padx=(0, 12))
        title_box = ctk.CTkFrame(header, fg_color="transparent"); title_box.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(title_box, text="Subtitle Assistant", font=("Segoe UI", 23, "bold"), text_color="#17243A").pack(anchor="w")
        ctk.CTkLabel(title_box, text="Chọn dự án, thiết lập cách chia và xem trước trước khi chèn vào timeline.",
                     font=("Segoe UI", 12), text_color="#6B7890").pack(anchor="w")

        project = self._card(root, "01  ·  Chọn dự án CapCut", "Kéo dấu ngắm vào cửa sổ CapCut đang mở. App sẽ nhận diện cửa sổ và chọn draft đã lưu gần nhất.")
        prow = ctk.CTkFrame(project, fg_color="transparent"); prow.pack(fill="x", padx=14, pady=(0, 12))
        self.project_cb = ctk.CTkComboBox(prow, values=[], command=self._project_changed, corner_radius=10, height=38)
        self.project_cb.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.aim_handle = ctk.CTkLabel(prow, text="⌖  KÉO TỚI CAPCUT", width=176, height=40, corner_radius=12,
                                       fg_color="#E8F0FF", text_color="#2458C5", font=("Segoe UI", 12, "bold"), cursor="hand2")
        self.aim_handle.pack(side="left", padx=(0, 8))
        self.aim_handle.bind("<ButtonPress-1>", self.begin_pointer_pick)
        ctk.CTkButton(prow, text="Quét", width=72, height=38, corner_radius=10, command=self.refresh_projects).pack(side="left")
        ctk.CTkButton(prow, text="Thư mục…", width=100, height=38, corner_radius=10, fg_color="#EEF2F8",
                      hover_color="#DFE6F1", text_color="#2B3952", command=self.choose_project).pack(side="left", padx=(8, 0))
        self.target_info = ctk.CTkLabel(project, text="Chưa chọn cửa sổ CapCut.", font=("Segoe UI", 11), text_color="#6B7890", anchor="w")
        self.target_info.pack(fill="x", padx=16, pady=(0, 12))
        self.project_cb.bind("<<ComboboxSelected>>", self.load_project)

        source = self._card(root, "02  ·  Clip và tọa độ timeline", "Nguồn và thời gian lấy từ draft dự án. Chọn clip cần làm phụ đề.")
        self.media_cb = ctk.CTkComboBox(source, values=[], state="readonly", corner_radius=10, height=38)
        self.media_cb.pack(fill="x", padx=14, pady=(0, 8))
        self.project_info = ctk.CTkLabel(source, text="Chờ chọn dự án…", font=("Segoe UI", 11), text_color="#718096", anchor="w", justify="left")
        self.project_info.pack(fill="x", padx=16, pady=(0, 12))

        opts = self._card(root, "03  ·  Cách tách phụ đề", "Chọn quy tắc phù hợp với nhịp lời thoại. Timestamp lấy từ từng từ nhận diện.")
        grid = ctk.CTkFrame(opts, fg_color="transparent"); grid.pack(fill="x", padx=14, pady=(0, 12))
        self.mode = ctk.CTkOptionMenu(grid, values=["Theo câu", "Theo dấu câu", "Theo số từ", "Theo ký tự", "Theo thời lượng", "Từng từ (karaoke)"], corner_radius=10, height=36, command=self._mode_changed)
        self.mode.set("Theo số từ"); self.mode.grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=4)
        self.word_label = ctk.CTkLabel(grid, text="Từ/cụm", text_color="#43516A")
        self.word_label.grid(row=0, column=1, sticky="w", padx=6)
        self.word_limit = ctk.CTkOptionMenu(grid, values=[str(n) for n in range(2, 15)], width=88, corner_radius=10, height=36)
        self.word_limit.set("6"); self.word_limit.grid(row=0, column=2, padx=(2, 12), pady=4)
        self.char_label = ctk.CTkLabel(grid, text="Ký tự/dòng", text_color="#43516A")
        self.char_label.grid(row=0, column=3, sticky="w", padx=6)
        self.char_limit = ctk.CTkOptionMenu(grid, values=[str(n) for n in range(20, 81, 2)], width=88, corner_radius=10, height=36)
        self.char_limit.set("38"); self.char_limit.grid(row=0, column=4, padx=(2, 12), pady=4)
        self.duration_label = ctk.CTkLabel(grid, text="Giây/cụm", text_color="#43516A")
        self.duration_label.grid(row=0, column=5, sticky="w", padx=6)
        self.duration_limit = ctk.CTkOptionMenu(grid, values=["1.0", "1.5", "2.0", "2.5", "3.0", "4.0"], width=82, corner_radius=10, height=36)
        self.duration_limit.set("2.0"); self.duration_limit.grid(row=0, column=6, pady=4)
        grid.columnconfigure(0, weight=1)
        style_row = ctk.CTkFrame(opts, fg_color="transparent"); style_row.pack(fill="x", padx=14, pady=(0, 12))
        self.color_mode = ctk.CTkOptionMenu(style_row, values=["Một màu", "Đổi màu theo cụm"], corner_radius=10, height=34, width=165)
        self.color_mode.set("Một màu"); self.color_mode.pack(side="left", padx=(0, 10))
        self.language = ctk.CTkOptionMenu(style_row, values=["Tự nhận diện", "Tiếng Việt", "English"], corner_radius=10, height=34, width=155)
        self.language.set("Tiếng Việt"); self.language.pack(side="left")

        appearance = self._card(root, "04  ·  Phong cách chữ")
        arow = ctk.CTkFrame(appearance, fg_color="transparent"); arow.pack(fill="x", padx=14, pady=(4, 12))
        fonts = sorted({f.name for f in fm.fontManager.ttflist})
        self.font_cb = ctk.CTkComboBox(arow, values=fonts, width=245, corner_radius=10, height=36)
        self.font_cb.set("Arial" if "Arial" in fonts else (fonts[0] if fonts else "Arial")); self.font_cb.pack(side="left", padx=(0, 12))
        self.color_buttons = []
        for i, color in enumerate(self.colors):
            button = ctk.CTkButton(arow, text=f"Màu {i+1}", width=82, height=34, corner_radius=11,
                                   fg_color=color, hover_color=color, text_color="#202838" if color in ("#FFFFFF", "#FFE600") else "#FFFFFF",
                                   border_width=1, border_color="#D7DEEA", command=lambda j=i: self.pick_color(j))
            button.pack(side="left", padx=4); self.color_buttons.append(button)

        script_card = ctk.CTkFrame(root, corner_radius=16, fg_color="#FFFFFF", border_width=1, border_color="#E4EAF3")
        script_card.pack(fill="both", expand=True, pady=6)
        ctk.CTkLabel(script_card, text="05  ·  Kịch bản tùy chọn", font=("Segoe UI", 14, "bold"), text_color="#18243A").pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(script_card, text="Để trống nếu muốn dùng lời nhận diện. Bản nhập chỉ thay chữ khi số từ khớp để giữ timing.", font=("Segoe UI", 11), text_color="#718096").pack(anchor="w", padx=16, pady=(2, 8))
        self.script = ctk.CTkTextbox(script_card, height=110, corner_radius=10, border_width=1, border_color="#E4EAF3", wrap="word")
        self.script.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        bottom = ctk.CTkFrame(root, fg_color="transparent"); bottom.pack(fill="x", pady=(5, 0))
        self.status = ctk.CTkLabel(bottom, text="Sẵn sàng", text_color="#62718A", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.go_btn = ctk.CTkButton(bottom, text="Tạo phụ đề vào dự án", height=42, corner_radius=12, command=self.start)
        self.go_btn.pack(side="right")
        self.preview_btn = ctk.CTkButton(bottom, text="Xem trước", height=42, width=110, corner_radius=12,
                                         fg_color="#E9EEF8", hover_color="#DDE6F5", text_color="#2A3C5D", command=self.preview)
        self.preview_btn.pack(side="right", padx=8)

    def _mode_changed(self, value):
        self.word_label.grid_remove(); self.word_limit.grid_remove()
        self.char_label.grid_remove(); self.char_limit.grid_remove()
        self.duration_label.grid_remove(); self.duration_limit.grid_remove()
        if value == "Theo số từ":
            self.word_label.grid(); self.word_limit.grid()
        elif value == "Theo ký tự":
            self.char_label.grid(); self.char_limit.grid()
        elif value == "Theo thời lượng":
            self.duration_label.grid(); self.duration_limit.grid()

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

    def pick_color(self, index):
        color = colorchooser.askcolor(color=self.colors[index], parent=self)[1]
        if color:
            self.colors[index] = color
            self.color_buttons[index].configure(fg_color=color, hover_color=color,
                                                 text_color="#202838" if color in ("#FFFFFF", "#FFE600") else "#FFFFFF")

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
        return {"media": item, "mode": self.mode.get(), "word_limit": int(self.word_limit.get()),
                "char_limit": int(self.char_limit.get()), "duration_limit": float(self.duration_limit.get()),
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
                threading.Thread(target=self._worker, args=(path, settings), daemon=True).start()
        except Exception as exc: messagebox.showerror("Thiếu thông tin", str(exc), parent=self)

    def _worker(self, path, settings):
        try:
            subtitles, warning = self.build_subs(settings)
            backup = inject_to_capcut(path, subtitles, settings["font"], settings["colors"])
            self.after(0, lambda: self._finish(f"{warning}Đã thêm {len(subtitles)} phụ đề. Bản sao lưu: {backup}"))
        except Exception as exc: self.after(0, lambda: self._finish(str(exc), error=True))

    def _finish(self, text, error=False):
        self.status.configure(text=text)
        self.go_btn.configure(state="normal"); self.preview_btn.configure(state="normal")
        if error: messagebox.showerror("Không hoàn tất", text, parent=self)


if __name__ == "__main__":
    App().mainloop()
