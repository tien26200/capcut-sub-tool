import json
import os
import shutil
import threading
from datetime import datetime
import uuid
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

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
    if mode == "Theo số từ":
        return [words[i:i + limit] for i in range(0, len(words), limit)]
    # Readability mode: break before a long line, keeping a practical word cap.
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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CapCut Subtitle Assistant")
        self.geometry("940x760")
        self.minsize(820, 650)
        self.projects = {}
        self.media_items = []
        self.colors = ["#FFFFFF", "#FFE600", "#FF2A54"]
        self._build_ui()
        self.refresh_projects()

    def _build_ui(self):
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="CAPCUT SUBTITLE ASSISTANT", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(root, text="Chọn dự án CapCut, lấy clip và tọa độ timeline từ draft, rồi tạo phụ đề theo cách bạn muốn.",
                  wraplength=850).pack(anchor="w", pady=(2, 12))

        project_box = ttk.LabelFrame(root, text="1. Dự án CapCut", padding=10)
        project_box.pack(fill="x", pady=5)
        row = ttk.Frame(project_box); row.pack(fill="x")
        ttk.Label(row, text="Dự án:").pack(side="left")
        self.project_cb = ttk.Combobox(row, state="readonly")
        self.project_cb.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Quét & lấy dự án", command=self.refresh_projects).pack(side="left", padx=3)
        ttk.Button(row, text="Chọn thư mục dự án…", command=self.choose_project).pack(side="left", padx=3)
        ttk.Label(project_box, text="Chọn dự án đã lưu hoặc quét thư mục draft. App đọc file dự án cục bộ; không cần nhập link hay tự chọn file video.",
                  wraplength=850).pack(anchor="w", pady=(7, 0))
        self.project_cb.bind("<<ComboboxSelected>>", self.load_project)

        source_box = ttk.LabelFrame(root, text="2. Clip và vị trí trên timeline", padding=10)
        source_box.pack(fill="x", pady=5)
        self.media_cb = ttk.Combobox(source_box, state="readonly")
        self.media_cb.pack(fill="x")
        self.project_info = ttk.Label(source_box, text="Chọn dự án để đọc clip và tọa độ.")
        self.project_info.pack(anchor="w", pady=(6, 0))

        opts = ttk.LabelFrame(root, text="3. Cách chia phụ đề", padding=10)
        opts.pack(fill="x", pady=5)
        grid = ttk.Frame(opts); grid.pack(fill="x")
        ttk.Label(grid, text="Kiểu chia:").grid(row=0, column=0, sticky="w", padx=4, pady=5)
        self.mode = ttk.Combobox(grid, state="readonly", values=["Theo câu", "Theo số từ", "Theo độ dài dòng", "Từng từ (karaoke)"])
        self.mode.set("Theo độ dài dòng"); self.mode.grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Label(grid, text="Số từ mỗi cụm:").grid(row=0, column=2, sticky="w", padx=4)
        self.word_limit = ttk.Spinbox(grid, from_=2, to=14, width=6); self.word_limit.set("6"); self.word_limit.grid(row=0, column=3, padx=4)
        ttk.Label(grid, text="Độ dài dòng (ký tự):").grid(row=1, column=0, sticky="w", padx=4, pady=5)
        self.char_limit = ttk.Spinbox(grid, from_=20, to=100, width=6); self.char_limit.set("38"); self.char_limit.grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(grid, text="Màu:").grid(row=1, column=2, sticky="w", padx=4)
        self.color_mode = ttk.Combobox(grid, state="readonly", values=["Một màu", "Đổi màu theo cụm"])
        self.color_mode.set("Một màu"); self.color_mode.grid(row=1, column=3, sticky="ew", padx=4)
        ttk.Label(grid, text="Ngôn ngữ nhận diện:").grid(row=2, column=0, sticky="w", padx=4, pady=5)
        self.language = ttk.Combobox(grid, state="readonly", values=["Tự nhận diện", "Tiếng Việt", "English"], width=18)
        self.language.set("Tiếng Việt"); self.language.grid(row=2, column=1, sticky="w", padx=4)
        grid.columnconfigure(1, weight=1); grid.columnconfigure(3, weight=1)

        style = ttk.LabelFrame(root, text="4. Hiển thị", padding=10); style.pack(fill="x", pady=5)
        fonts = sorted({f.name for f in fm.fontManager.ttflist})
        ttk.Label(style, text="Font:").pack(side="left")
        self.font_cb = ttk.Combobox(style, values=fonts, width=27)
        self.font_cb.set("Arial" if "Arial" in fonts else (fonts[0] if fonts else "Arial")); self.font_cb.pack(side="left", padx=8)
        self.color_buttons = []
        for i, color in enumerate(self.colors):
            button = tk.Button(style, text=f"Màu {i+1}", bg=color, width=9, command=lambda j=i: self.pick_color(j))
            button.pack(side="left", padx=4); self.color_buttons.append(button)

        script = ttk.LabelFrame(root, text="5. Kịch bản tùy chọn (để trống nếu muốn dùng lời nhận diện)", padding=8)
        script.pack(fill="both", expand=True, pady=5)
        self.script = tk.Text(script, height=8, wrap="word", font=("Segoe UI", 10))
        self.script.pack(fill="both", expand=True)

        bottom = ttk.Frame(root); bottom.pack(fill="x", pady=(8, 0))
        self.status = ttk.Label(bottom, text="Sẵn sàng")
        self.status.pack(side="left", fill="x", expand=True)
        self.preview_btn = ttk.Button(bottom, text="Xem trước", command=self.preview)
        self.preview_btn.pack(side="right", padx=5)
        self.go_btn = ttk.Button(bottom, text="Tạo phụ đề vào dự án", command=self.start)
        self.go_btn.pack(side="right")

    def refresh_projects(self):
        files = discover_projects()
        self.projects = {str(p): str(p) for p in files}
        self.project_cb["values"] = list(self.projects)
        if files:
            self.project_cb.current(0); self.load_project()
            self.status.config(text=f"Đã tìm thấy {len(files)} dự án CapCut")
        else:
            self.status.config(text="Chưa tìm thấy dự án tự động; chọn thư mục dự án thủ công.")

    def choose_project(self):
        folder = filedialog.askdirectory(title="Chọn thư mục dự án CapCut")
        if not folder: return
        candidates = list(Path(folder).rglob("draft_content.json"))
        if not candidates:
            messagebox.showerror("Không tìm thấy draft", "Thư mục này không có draft_content.json.")
            return
        p = max(candidates, key=lambda x: x.stat().st_mtime)
        key = str(p.resolve()); self.projects[key] = key
        self.project_cb["values"] = list(self.projects); self.project_cb.set(key); self.load_project()

    def load_project(self, _event=None):
        path = self.project_cb.get()
        if not path: return
        try:
            _, self.media_items = draft_media(path)
            labels = []
            for item in self.media_items:
                exists = os.path.isfile(item["path"])
                start = item["timeline_start"] / 1e6
                label = f"{'✓' if exists else '⚠'} {Path(item['path']).name} | timeline {start:.2f}s | source {item['source_start']/1e6:.2f}s"
                labels.append(label)
            self.media_cb["values"] = labels
            if labels: self.media_cb.current(0)
            self.project_info.config(text=f"Draft: {path}\nĐọc được {len(labels)} nguồn video và vị trí timeline. Chỉ clip có đường dẫn tồn tại mới xử lý được.")
        except Exception as exc:
            messagebox.showerror("Không đọc được dự án", str(exc))

    def pick_color(self, index):
        color = colorchooser.askcolor(color=self.colors[index], parent=self)[1]
        if color:
            self.colors[index] = color; self.color_buttons[index].config(bg=color)

    def selected_media(self):
        index = self.media_cb.current()
        if index < 0 or index >= len(self.media_items): raise ValueError("Dự án không có clip video để xử lý.")
        item = self.media_items[index]
        if not os.path.isfile(item["path"]): raise ValueError("Không tìm thấy file video nguồn trên máy:\n" + item["path"])
        return item

    def collect_settings(self):
        item = dict(self.selected_media())
        return {"media": item, "mode": self.mode.get(), "word_limit": int(self.word_limit.get()),
                "char_limit": int(self.char_limit.get()), "color_mode": self.color_mode.get(),
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
        limit = settings["word_limit"] if settings["mode"] == "Theo số từ" else settings["char_limit"]
        return make_subtitles(words, settings["mode"], limit, settings["color_mode"]), warning

    def preview(self):
        try:
            settings = self.collect_settings()
            self.status.config(text="Đang nhận diện để tạo bản xem trước…")
            self.go_btn.config(state="disabled"); self.preview_btn.config(state="disabled")
            threading.Thread(target=self._preview_worker, args=(settings,), daemon=True).start()
        except Exception as exc: messagebox.showerror("Lỗi", str(exc))

    def _preview_worker(self, settings):
        try:
            subs, warning = self.build_subs(settings)
            lines = [f"{s['start_us']/1e6:7.2f}s  {s['text']}" for s in subs[:120]]
            self.after(0, lambda: self._show_preview(subs, lines, warning))
        except Exception as exc: self.after(0, lambda: self._finish(str(exc), error=True))

    def _show_preview(self, subs, lines, warning):
        win = tk.Toplevel(self); win.title(f"Xem trước — {len(subs)} phụ đề"); win.geometry("600x500")
        box = tk.Text(win, wrap="none"); box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", "\n".join(lines)); box.config(state="disabled")
        ttk.Label(win, text="Đang hiển thị tối đa 120 dòng đầu; thời gian đã cộng vị trí clip trên timeline.").pack(pady=(0, 8))
        self._finish(f"{warning}Xem trước xong: {len(subs)} cụm phụ đề")

    def start(self):
        try:
            path = self.project_cb.get()
            if not path or not os.path.isfile(path): raise ValueError("Hãy chọn dự án CapCut trước.")
            settings = self.collect_settings()
            if messagebox.askyesno("Ghi phụ đề vào dự án?", "App sẽ tạo bản sao .backup rồi thêm track phụ đề vào draft_content.json. Hãy đóng dự án trong CapCut trước khi tiếp tục."):
                self.go_btn.config(state="disabled"); self.preview_btn.config(state="disabled")
                self.status.config(text="Đang nhận diện và căn theo clip/tọa độ timeline…")
                threading.Thread(target=self._worker, args=(path, settings), daemon=True).start()
        except Exception as exc: messagebox.showerror("Thiếu thông tin", str(exc))

    def _worker(self, path, settings):
        try:
            subtitles, warning = self.build_subs(settings)
            backup = inject_to_capcut(path, subtitles, settings["font"], settings["colors"])
            self.after(0, lambda: self._finish(f"{warning}Đã thêm {len(subtitles)} phụ đề. Bản sao lưu: {backup}"))
        except Exception as exc: self.after(0, lambda: self._finish(str(exc), error=True))

    def _finish(self, text, error=False):
        self.status.config(text=text)
        self.go_btn.config(state="normal"); self.preview_btn.config(state="normal")
        if error: messagebox.showerror("Không hoàn tất", text)


if __name__ == "__main__":
    App().mainloop()
