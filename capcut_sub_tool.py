import os
import sys
import json
import uuid
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser
import matplotlib.font_manager as fm
def hex_to_capcut_rgba(hex_code, alpha=1.0):
    hex_code = hex_code.lstrip('#')
    if len(hex_code) == 6:
        r = int(hex_code[0:2], 16) / 255.0
        g = int(hex_code[2:4], 16) / 255.0
        b = int(hex_code[4:6], 16) / 255.0
        return [round(r, 4), round(g, 4), round(b, 4), float(alpha)]
    return [1.0, 1.0, 1.0, 1.0]
def get_installed_fonts():
    fonts = sorted(list(set([f.name for f in fm.fontManager.ttflist])))
    return fonts
def inject_to_capcut(draft_path, subtitles_data, font_name, colors):
    if not os.path.exists(draft_path):
        raise FileNotFoundError(f"Khong tim thay file: {draft_path}")
    with open(draft_path, 'r', encoding='utf-8') as f:
        draft = json.load(f)
    if "materials" not in draft:
        draft["materials"] = {}
    if "texts" not in draft["materials"]:
        draft["materials"]["texts"] = []
    if "tracks" not in draft:
        draft["tracks"] = []
    text_track_id = str(uuid.uuid4())
    new_track = {
        "id": text_track_id,
        "type": "text",
        "segments": [],
        "attribute": 0,
        "flag": 0
    }
    for item in subtitles_data:
        text_id = str(uuid.uuid4())
        segment_id = str(uuid.uuid4())
        part_idx = item.get("part_idx", 0)
        if part_idx == 0:
            c_hex = colors.get("part1", "#FFFFFF")
        elif part_idx == 1:
            c_hex = colors.get("part2", "#FFE600")
        else:
            c_hex = colors.get("part3", "#FF2A54")
        rgba = hex_to_capcut_rgba(c_hex)
        duration_us = max(0, item['end_us'] - item['start_us'])
        text_content_obj = {
            "styles": [{
                "fill": {
                    "alpha": 1.0,
                    "content": {
                        "render_type": "solid",
                        "solid": {"color": [rgba[0], rgba[1], rgba[2]]}
                    }
                },
                "range": [0, len(item['text'])],
                "size": 8.0,
                "font": {"path": font_name, "name": font_name}
            }],
            "text": item['text']
        }
        text_material = {
            "id": text_id,
            "type": "text",
            "content": json.dumps(text_content_obj, ensure_ascii=False),
            "font_path": font_name,
            "text_color": rgba,
            "border_color": [0.0, 0.0, 0.0, 1.0],
            "border_width": 15.0,
            "shadow_color": [0.0, 0.0, 0.0, 0.8],
            "shadow_alpha": 0.8,
            "shadow_point": {"x": 5.0, "y": -5.0},
            "alignment": 1,
            "typesetting": 0
        }
        draft["materials"]["texts"].append(text_material)
        segment = {
            "id": segment_id,
            "material_id": text_id,
            "render_index": 0,
            "target_timerange": {
                "start": item['start_us'],
                "duration": duration_us
            },
            "source_timerange": {
                "start": 0,
                "duration": duration_us
            },
            "speed": 1.0,
            "volume": 1.0
        }
        new_track["segments"].append(segment)
    draft["tracks"].append(new_track)
    with open(draft_path, 'w', encoding='utf-8') as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
class CapCutSubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CapCut Auto-Sub: 3-Stage Highlighter")
        self.geometry("780x680")
        self.resizable(False, False)
        self.color_p1 = "#FFFFFF"
        self.color_p2 = "#FFE600"
        self.color_p3 = "#FF2A54"
        self.setup_ui()
    def setup_ui(self):
        pad = {'padx': 10, 'pady': 5}
        file_frame = ttk.LabelFrame(self, text=" 1. Thiết lập tệp tin ")
        file_frame.pack(fill="x", **pad)
        ttk.Label(file_frame, text="File Media (Audio/Video):").grid(row=0, column=0, sticky="w", **pad)
        self.entry_media = ttk.Entry(file_frame, width=58)
        self.entry_media.grid(row=0, column=1, **pad)
        ttk.Button(file_frame, text="Browse...", command=self.browse_media).grid(row=0, column=2, **pad)
        ttk.Label(file_frame, text="File draft_content.json:").grid(row=1, column=0, sticky="w", **pad)
        self.entry_draft = ttk.Entry(file_frame, width=58)
        self.entry_draft.grid(row=1, column=1, **pad)
        ttk.Button(file_frame, text="Browse...", command=self.browse_draft).grid(row=1, column=2, **pad)
        style_frame = ttk.LabelFrame(self, text=" 2. Tùy chọn Font & Màu Sắc Nhấn Nhá ")
        style_frame.pack(fill="x", **pad)
        ttk.Label(style_frame, text="Chọn Font:").grid(row=0, column=0, sticky="w", **pad)
        fonts = get_installed_fonts()
        self.font_cb = ttk.Combobox(style_frame, values=fonts, width=35)
        default_font = "Arial" if "Arial" in fonts else (fonts[0] if fonts else "")
        self.font_cb.set(default_font)
        self.font_cb.grid(row=0, column=1, sticky="w", **pad)
        color_box = ttk.Frame(style_frame)
        color_box.grid(row=1, column=0, columnspan=3, pady=10, sticky="w")
        ttk.Label(color_box, text="Đoạn 1:").pack(side="left", padx=5)
        self.btn_col1 = tk.Button(color_box, text=self.color_p1, bg=self.color_p1, width=8,
                                  command=lambda: self.pick_color(1))
        self.btn_col1.pack(side="left", padx=5)
        ttk.Label(color_box, text="Đoạn 2:").pack(side="left", padx=5)
        self.btn_col2 = tk.Button(color_box, text=self.color_p2, bg=self.color_p2, width=8,
                                  command=lambda: self.pick_color(2))
        self.btn_col2.pack(side="left", padx=5)
        ttk.Label(color_box, text="Đoạn 3:").pack(side="left", padx=5)
        self.btn_col3 = tk.Button(color_box, text=self.color_p3, bg=self.color_p3, width=8,
                                  command=lambda: self.pick_color(3))
        self.btn_col3.pack(side="left", padx=5)
        script_frame = ttk.LabelFrame(self, text=" 3. Kịch bản / Caption có sẵn (Mỗi câu 1 dòng) ")
        script_frame.pack(fill="both", expand=True, **pad)
        self.txt_script = tk.Text(script_frame, height=9, font=("Consolas", 10))
        self.txt_script.pack(fill="both", expand=True, padx=5, pady=5)
        action_frame = ttk.Frame(self)
        action_frame.pack(fill="x", **pad)
        self.lbl_status = ttk.Label(action_frame, text="Trạng thái: Sẵn sàng", foreground="gray")
        self.lbl_status.pack(side="left", padx=5)
        self.btn_start = ttk.Button(action_frame, text="TIẾN HÀNH XỬ LÝ & INJECT VÀO CAPCUT", command=self.run_process)
        self.btn_start.pack(side="right", padx=5, pady=5)
    def browse_media(self):
        f = filedialog.askopenfilename(filetypes=[("Media Files", "*.mp4 *.mp3 *.wav *.m4a *.mov")])
        if f:
            self.entry_media.delete(0, tk.END)
            self.entry_media.insert(0, f)
    def browse_draft(self):
        f = filedialog.askopenfilename(filetypes=[("CapCut Draft Content", "draft_content.json")])
        if f:
            self.entry_draft.delete(0, tk.END)
            self.entry_draft.insert(0, f)
    def pick_color(self, part):
        initial = self.color_p1 if part == 1 else (self.color_p2 if part == 2 else self.color_p3)
        col = colorchooser.askcolor(initialcolor=initial)[1]
        if col:
            if part == 1:
                self.color_p1 = col
                self.btn_col1.config(bg=col, text=col)
            elif part == 2:
                self.color_p2 = col
                self.btn_col2.config(bg=col, text=col)
            else:
                self.color_p3 = col
                self.btn_col3.config(bg=col, text=col)
    def run_process(self):
        media = self.entry_media.get().strip()
        draft = self.entry_draft.get().strip()
        raw_script = self.txt_script.get("1.0", tk.END).strip()
        if not media or not os.path.exists(media):
            messagebox.showerror("Lỗi", "Vui lòng chọn file Audio/Video hợp lệ!")
            return
        if not draft or not os.path.exists(draft):
            messagebox.showerror("Lỗi", "Vui lòng chọn file draft_content.json của CapCut!")
            return
        self.btn_start.config(state="disabled")
        self.lbl_status.config(text="Đang nhận diện giọng nói và chia cụm 3 đoạn...", foreground="blue")
        threading.Thread(target=self.worker_thread, args=(media, draft, raw_script), daemon=True).start()
    def worker_thread(self, media_path, draft_path, script_text):
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(media_path, word_timestamps=True, language="vi")
            recognized_sentences = []
            for seg in segments:
                words = seg.words
                if not words:
                    continue
                full_text = " ".join([w.word.strip() for w in words])
                recognized_sentences.append({
                    "start": seg.start,
                    "end": seg.end,
                    "words": words,
                    "text": full_text
                })
            script_lines = [l.strip() for l in script_text.splitlines() if l.strip()]
            subtitles_data = []
            for i, item in enumerate(recognized_sentences):
                display_text = script_lines[i] if i < len(script_lines) else item["text"]
                words = display_text.split()
                n = len(words)
                total_duration = item["end"] - item["start"]
                if n < 3:
                    chunks = [words]
                else:
                    k, m = divmod(n, 3)
                    chunks = [
                        words[:k + (1 if m > 0 else 0)],
                        words[k + (1 if m > 0 else 0): 2 * k + (1 if m > 1 else 0)],
                        words[2 * k + (1 if m > 1 else 0):]
                    ]
                current_start = item["start"]
                for p_idx, chunk in enumerate(chunks):
                    if not chunk:
                        continue
                    part_text = " ".join(chunk).upper()
                    part_duration = total_duration * (len(chunk) / n)
                    part_end = current_start + part_duration
                    subtitles_data.append({
                        "text": part_text,
                        "start_us": int(current_start * 1_000_000),
                        "end_us": int(part_end * 1_000_000),
                        "part_idx": p_idx
                    })
                    current_start = part_end
            colors = {
                "part1": self.color_p1,
                "part2": self.color_p2,
                "part3": self.color_p3
            }
            inject_to_capcut(draft_path, subtitles_data, self.font_cb.get(), colors)
            self.lbl_status.config(text="Thành công! Đã chèn phụ đề vào CapCut.", foreground="green")
            messagebox.showinfo("Hoàn tất", f"Đã inject thành công {len(subtitles_data)} phân đoạn subtitle vào dự án CapCut!")
        except Exception as e:
            self.lbl_status.config(text="Có lỗi xảy ra!", foreground="red")
            messagebox.showerror("Lỗi thực thi", str(e))
        finally:
            self.btn_start.config(state="normal")
if __name__ == "__main__":
    app = CapCutSubApp()
    app.mainloop()
