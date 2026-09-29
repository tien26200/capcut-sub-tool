import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from capcut_sub_tool import chunk_words, draft_media, inject_to_capcut, make_subtitles


@unittest.skipUnless(sys.platform == "win32", "Windows desktop layout test")
class LayoutTests(unittest.TestCase):
    def test_start_button_visible_at_minimum_window_size(self):
        import customtkinter as ctk
        from capcut_sub_tool import App
        ctk.set_widget_scaling(1.0)
        ctk.set_window_scaling(1.0)
        with patch("capcut_sub_tool.discover_projects", return_value=[]):
            app = App()
        try:
            app.mode.set("Từng từ (karaoke)")
            app._mode_changed(app.mode.get())
            self.assertEqual(app.sample_subs[0]["text"], "XIN")
            app._set_color(0, "#00AAFF")
            self.assertEqual(app.sample_text.cget("text_color"), "#00AAFF")
            app.font_search.set("___no_matching_font___")
            self.assertEqual(app.font_cb.cget("state"), "disabled")
            app.font_search.set(app.fonts[0])
            self.assertIn(app.fonts[0], app.font_cb.cget("values"))
            app.font_search.set("")
            app.mode.set("Theo số từ")
            app._mode_changed(app.mode.get())
            self.assertEqual(len(app.sample_subs[0]["text"].split()), 6)
            app.color_mode.set("Đổi màu theo cụm")
            app._refresh_sample()
            app._step_sample(1)
            self.assertEqual(app.sample_text.cget("text_color"), app.colors[1])
            for geometry in ("1040x820", "880x640"):
                app.geometry(geometry)
                app.status.configure(text="Đã lưu phụ đề. " + "Tên thư mục dự án rất dài/" * 8)
                app.update()
                button = app.go_btn
                self.assertTrue(button.winfo_ismapped())
                x = button.winfo_rootx() - app.winfo_rootx()
                y = button.winfo_rooty() - app.winfo_rooty()
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + button.winfo_width(), app.winfo_width())
                self.assertLessEqual(y + button.winfo_height(), app.winfo_height())
        finally:
            app.destroy()


class SubtitleTests(unittest.TestCase):
    def setUp(self):
        self.words = [
            {"text": "Xin", "start": 1.0, "end": 1.2},
            {"text": " chào", "start": 1.2, "end": 1.5},
            {"text": " bạn.", "start": 1.5, "end": 1.9},
        ]

    def test_split_by_word_count_preserves_word_timing(self):
        groups = chunk_words(self.words, "Theo số từ", 2)
        self.assertEqual([len(group) for group in groups], [2, 1])
        subs = make_subtitles(self.words, "Theo số từ", 2, "Một màu")
        self.assertEqual(subs[0]["start_us"], 1_000_000)
        self.assertEqual(subs[0]["end_us"], 1_500_000)

    def test_sentence_and_karaoke_modes(self):
        sentence = make_subtitles(self.words, "Theo câu", 6, "Một màu")
        karaoke = make_subtitles(self.words, "Từng từ (karaoke)", 6, "Một màu")
        self.assertEqual(len(sentence), 1)
        self.assertEqual(len(karaoke), 3)

    def test_more_split_modes(self):
        punctuation_words = [
            {"text": "Một", "start": 0.0, "end": 0.4},
            {"text": "hai,", "start": 0.4, "end": 0.8},
            {"text": "ba", "start": 0.8, "end": 1.2},
            {"text": "bốn.", "start": 1.2, "end": 1.8},
        ]
        punct = make_subtitles(punctuation_words, "Theo dấu câu", 38, "Một màu")
        timed = make_subtitles(punctuation_words, "Theo thời lượng", 1.0, "Một màu")
        self.assertEqual([x["text"] for x in punct], ["MỘT HAI,", "BA BỐN."])
        self.assertEqual([x["text"] for x in timed], ["MỘT HAI,", "BA BỐN."])

    def test_draft_media_reads_clip_and_timeline_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            draft_path = Path(directory) / "draft_content.json"
            draft_path.write_text(json.dumps({
                "materials": {"videos": [{"id": "video-1", "path": "clip.mp4"}]},
                "tracks": [{"segments": [{"material_id": "video-1",
                    "target_timerange": {"start": 3_000_000, "duration": 4_000_000},
                    "source_timerange": {"start": 2_000_000, "duration": 4_000_000}}]}]
            }), encoding="utf-8")
            _, clips = draft_media(str(draft_path))
            self.assertEqual(clips[0]["timeline_start"], 3_000_000)
            self.assertEqual(clips[0]["source_start"], 2_000_000)

    def test_injection_creates_backup_and_text_track(self):
        with tempfile.TemporaryDirectory() as directory:
            draft_path = Path(directory) / "draft_content.json"
            draft_path.write_text(json.dumps({"materials": {"texts": []}, "tracks": []}), encoding="utf-8")
            backup = inject_to_capcut(str(draft_path), [{"text": "TEST", "start_us": 10, "end_us": 50}], "DejaVu Sans", ["#FFFFFF"])
            self.assertTrue(Path(backup).is_file())
            updated = json.loads(draft_path.read_text(encoding="utf-8"))
            self.assertEqual(len(updated["tracks"]), 1)
            self.assertEqual(len(updated["materials"]["texts"]), 1)


if __name__ == "__main__":
    unittest.main()
