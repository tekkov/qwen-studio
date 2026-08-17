import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class PersistentStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patchers = [
            patch.object(server, "DATA_DIR", self.root),
            patch.object(server, "THREADS_FILE", self.root / "threads.json"),
            patch.object(server, "ATTACHMENTS_FILE", self.root / "attachments.json"),
            patch.object(server, "ATTACHMENTS_DIR", self.root / "attachments"),
        ]
        for patcher in self.patchers: patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers): patcher.stop()
        self.temporary.cleanup()

    def test_thread_messages_survive_a_reload(self):
        thread = server.create_thread("project-1")
        server.append_thread_message(thread["id"], "user", "Build a dashboard")
        server.append_thread_message(thread["id"], "assistant", "I created it.")

        loaded = server.thread_by_id(thread["id"])
        self.assertEqual(loaded["title"], "Build a dashboard")
        self.assertEqual([item["role"] for item in loaded["messages"]], ["user", "assistant"])

    def test_text_and_image_attachments_are_prepared_for_ollama(self):
        text_path = self.root / "notes.md"
        image_path = self.root / "pixel.png"
        text_path.write_text("Important project notes", encoding="utf-8")
        image_path.write_bytes(b"not-a-real-png-but-valid-bytes-for-transport")
        thread = server.create_thread("project-1")
        text_item = server.ingest_attachment(text_path, thread["id"])
        image_item = server.ingest_attachment(image_path, thread["id"])
        server.append_thread_message(thread["id"], "user", "Inspect these", [text_item["id"], image_item["id"]])

        messages = server.model_messages(server.thread_by_id(thread["id"])["messages"])
        self.assertIn("Important project notes", messages[0]["content"])
        self.assertEqual(base64.b64decode(messages[0]["images"][0]), image_path.read_bytes())

    def test_context_trimming_preserves_the_newest_turn(self):
        messages = [{"role": "user", "content": str(index) * 1000} for index in range(20)]
        selected, omitted = server.trim_messages(messages, 2048)
        self.assertGreater(omitted, 0)
        self.assertEqual(selected[-1], messages[-1])


if __name__ == "__main__":
    unittest.main()
