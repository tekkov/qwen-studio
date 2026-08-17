import base64
import json
import tempfile
import unittest
import zipfile
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

    def test_docx_is_extracted_and_unknown_files_get_guidance(self):
        docx_path = self.root / "brief.docx"
        with zipfile.ZipFile(docx_path, "w") as archive:
            archive.writestr("word/document.xml", '<document xmlns:w="urn"><w:t>Project brief</w:t></document>')
        document = server.ingest_attachment(docx_path, "thread-1")
        self.assertEqual(document["kind"], "document")
        self.assertEqual(document["status"], "ready")
        self.assertIn("Project brief", server.model_messages([{"role": "user", "content": "Read", "attachments": [document["id"]]}])[0]["content"])
        unknown = self.root / "archive.bin"
        unknown.write_bytes(b"binary")
        item = server.ingest_attachment(unknown, "thread-1")
        self.assertEqual(item["status"], "unsupported")
        self.assertIn("no built-in text extractor", item["guidance"])

    def test_context_trimming_preserves_the_newest_turn(self):
        messages = [{"role": "user", "content": str(index) * 1000} for index in range(20)]
        selected, omitted = server.trim_messages(messages, 2048)
        self.assertGreater(omitted, 0)
        self.assertEqual(selected[-1], messages[-1])

    def test_context_trimming_never_drops_system_instructions(self):
        system = {"role": "system", "content": "Always use tools and verify work."}
        messages = [system] + [{"role": "user", "content": str(index) * 2000} for index in range(20)]
        selected, omitted = server.trim_messages(messages, 2048)
        self.assertGreater(omitted, 0)
        self.assertIs(selected[0], system)
        self.assertEqual(selected[-1], messages[-1])

    def test_semantic_compaction_keeps_tool_memory_and_reports_utilization(self):
        messages = [{"role": "system", "content": "Use tools and verify."}]
        messages += [{"role": "user", "content": f"Request {index} " + ("details " * 400)} for index in range(12)]
        messages += [{"role": "tool", "content": "Saved index.html successfully."}, {"role": "user", "content": "Now verify the saved file."}]
        selected, omitted, details = server.compact_messages(messages, 2048)
        self.assertGreater(omitted, 0)
        self.assertTrue(details["compacted"])
        self.assertTrue(any("Saved index.html" in item.get("content", "") for item in selected))

    def test_profiles_use_larger_project_contexts(self):
        self.assertEqual(server.PROFILES["fast"]["num_ctx"], 32768)
        self.assertEqual(server.PROFILES["balanced"]["num_ctx"], 65536)
        self.assertEqual(server.PROFILES["deep"]["num_ctx"], 131072)

    def test_project_snapshot_contains_manifest_and_key_files(self):
        (self.root / "src").mkdir()
        (self.root / "README.md").write_text("Project-specific instructions", encoding="utf-8")
        snapshot = server.project_context_snapshot(self.root)
        self.assertIn("folder: src", snapshot)
        self.assertIn("[README.md]", snapshot)
        self.assertIn("Project-specific instructions", snapshot)

    def test_project_snapshot_loads_local_workflows(self):
        workflow = self.root / ".qwen" / "workflows"; workflow.mkdir(parents=True)
        (workflow / "release.md").write_text("Always run the release audit.", encoding="utf-8")
        self.assertIn("Always run the release audit", server.project_context_snapshot(self.root))

    def test_runtime_settings_round_trip_without_secret_values(self):
        settings = server.load_runtime_settings()
        self.assertFalse(settings["enabled"])
        settings["enabled"] = True; settings["mode"] = "continuous"; settings["dailyBudgetUsd"] = 2.5; settings["lowResource"] = True; settings["permissionProfile"] = "read-only"; settings["outputTokens"] = 4096; settings["idleOnly"] = True; settings["busyProcesses"] = "Game.exe, OBS64"
        server.save_runtime_settings(settings)
        loaded = server.load_runtime_settings()
        self.assertTrue(loaded["enabled"])
        self.assertEqual(loaded["mode"], "continuous")
        self.assertEqual(loaded["dailyBudgetUsd"], 2.5)
        self.assertTrue(loaded["lowResource"])
        self.assertEqual(loaded["permissionProfile"], "read-only")
        self.assertEqual(loaded["outputTokens"], 4096)
        self.assertTrue(loaded["idleOnly"])
        self.assertEqual(loaded["busyProcesses"], "game,obs64")

    def test_interrupted_jobs_restore_from_disk_as_resumable(self):
        job_id = "persisted-job"
        server.JOBS[job_id] = {"id": job_id, "threadId": "thread-1", "status": "running", "phase": "model", "activity": "Working", "events": [], "metrics": {}, "artifacts": [], "_request": {"messages": [{"role": "user", "content": "Continue"}]}}
        server.persist_jobs()
        server.JOBS.clear(); server.JOBS_LOADED = False; server.JOBS_SOURCE = None
        server.ensure_jobs_loaded()
        restored = server.JOBS[job_id]
        self.assertEqual(restored["status"], "interrupted")
        self.assertEqual(restored["_request"]["messages"][0]["content"], "Continue")
        self.assertTrue(any(event["kind"] == "interrupted" for event in restored["events"]))

    def test_supervisor_status_reports_only_credential_presence(self):
        with patch.dict(server.os.environ, {"OPENAI_API_KEY": "test-sensitive-value"}, clear=False), patch.object(server, "codex_cli_status", return_value={"available": True, "authenticated": True, "method": "api", "command": "codex", "message": "authenticated"}):
            status = server.supervisor_status()
        self.assertTrue(status["apiKeyAvailable"])
        self.assertNotIn("test-sensitive", json.dumps(status))


if __name__ == "__main__":
    unittest.main()
