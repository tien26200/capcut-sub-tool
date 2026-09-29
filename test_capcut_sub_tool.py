import json
import tempfile
import unittest
from pathlib import Path

from capcut_sub_tool import chunk_words, draft_media, inject_to_capcut, make_subtitles


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
