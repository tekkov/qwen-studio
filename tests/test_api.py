import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

import server


class ApiSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patchers = [
            patch.object(server, "DATA_DIR", self.root / "data"),
            patch.object(server, "PROJECTS_FILE", self.root / "data" / "projects.json"),
            patch.object(server, "THREADS_FILE", self.root / "data" / "threads.json"),
            patch.object(server, "ATTACHMENTS_FILE", self.root / "data" / "attachments.json"),
            patch.object(server, "ATTACHMENTS_DIR", self.root / "data" / "attachments"),
        ]
        for patcher in self.patchers: patcher.start()
        self.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.port = self.httpd.server_address[1]
        self.worker = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for patcher in reversed(self.patchers): patcher.stop()
        self.temporary.cleanup()

    def request(self, path, method="GET", body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())

    def test_project_thread_and_attachment_crud(self):
        parent = self.root / "projects"
        parent.mkdir()
        status_code, created = self.request("/api/projects/create", "POST", {"parent": str(parent), "name": "Demo App"})
        self.assertEqual(status_code, 201)
        self.assertTrue((parent / "Demo App").is_dir())

        project_id = created["project"]["id"]
        _, permissioned = self.request(f"/api/projects/{project_id}/permissions", "POST", {"permissionProfile": "read-only"})
        self.assertEqual(permissioned["permissionProfile"], "read-only")
        _, thread = self.request("/api/threads", "POST", {"projectId": project_id, "mode": "balanced"})
        note = self.root / "note.txt"
        note.write_text("attachment API smoke test", encoding="utf-8")
        _, attachments = self.request("/api/attachments", "POST", {"threadId": thread["id"], "paths": [str(note)]})
        _, threads = self.request(f"/api/threads?projectId={project_id}")

        self.assertEqual(attachments["items"][0]["kind"], "text")
        self.assertEqual(threads["items"][0]["id"], thread["id"])

    def test_thread_pin_and_delete_are_persistent_actions(self):
        _, thread = self.request("/api/threads", "POST", {"mode": "fast"})
        _, pinned = self.request(f"/api/threads/{thread['id']}/pin", "POST", {"pinned": True})
        self.assertTrue(pinned["pinned"])
        status, deleted = self.request(f"/api/threads/{thread['id']}", "DELETE")
        self.assertEqual(status, 200)
        self.assertEqual(deleted["deleted"], thread["id"])

    def test_terminal_streams_output_and_exits(self):
        _, run = self.request("/api/terminal", "POST", {"command": "Write-Output 'terminal smoke ok'"})
        for _ in range(50):
            _, current = self.request(f"/api/terminal/{run['id']}")
            if current["status"] != "running": break
            time.sleep(0.05)
        self.assertEqual(current["status"], "complete")
        self.assertEqual(current["exitCode"], 0)
        self.assertIn("terminal smoke ok", current["output"])

    def test_supervisor_settings_are_explicit_and_metered(self):
        _, before = self.request("/api/supervisor")
        self.assertIn("dailyBudgetUsd", before)
        _, changed = self.request("/api/supervisor", "POST", {"enabled": True, "mode": "failures", "dailyBudgetUsd": 1.5})
        self.assertTrue(changed["supervisor"]["enabled"])
        self.assertEqual(changed["supervisor"]["mode"], "failures")
        self.assertEqual(changed["supervisor"]["dailyBudgetUsd"], 1.5)

    def test_job_approval_endpoint_records_explicit_decision(self):
        job_id = "approval-smoke"
        server.JOBS_LOADED = True
        server.JOBS_SOURCE = str((self.root / "data" / "jobs.json").resolve())
        server.JOBS[job_id] = {"id": job_id, "status": "running", "events": [], "pendingApproval": {"id": "approval-1", "tool": "run_command", "request": {"reason": "test"}, "decision": None}}
        status_code, payload = self.request(f"/api/jobs/{job_id}/approve", "POST", {"approved": True})
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["job"]["events"][-1]["kind"], "approval_response")
        self.assertEqual(server.JOBS[job_id]["pendingApproval"]["decision"], "approved")

    def test_job_pause_endpoint_is_resumable(self):
        job_id = "pause-smoke"
        server.JOBS_LOADED = True; server.JOBS_SOURCE = str((self.root / "data" / "jobs.json").resolve())
        server.JOBS[job_id] = {"id": job_id, "status": "running", "events": [], "pauseRequested": False}
        _, paused = self.request(f"/api/jobs/{job_id}/pause", "POST", {"paused": True})
        self.assertTrue(paused["paused"])
        _, resumed = self.request(f"/api/jobs/{job_id}/pause", "POST", {"paused": False})
        self.assertFalse(resumed["paused"])

    def test_git_review_reports_branch_and_uncommitted_files(self):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        parent = self.root / "git-projects"
        parent.mkdir()
        _, created = self.request("/api/projects/create", "POST", {"parent": str(parent), "name": "Git Demo"})
        workspace = parent / "Git Demo"
        result = subprocess.run(["git", "init", "-q"], cwd=workspace, capture_output=True, text=True)
        if result.returncode:
            self.skipTest(f"Git repository could not be initialized: {result.stderr}")
        (workspace / "README.md").write_text("uncommitted", encoding="utf-8")
        _, snapshot = self.request("/api/git")
        self.assertTrue(snapshot["isRepository"])
        self.assertGreaterEqual(len(snapshot["status"]), 1)
        self.assertIn("README.md", "\n".join(snapshot["status"]))
        _, review = self.request("/api/git/file?path=README.md")
        self.assertEqual(review["path"], "README.md")
        self.assertIn("uncommitted", review["content"])
        _, diff = self.request("/api/git/diff")
        self.assertIn("preview", diff)
        self.assertIsInstance(snapshot["worktrees"], list)

    def test_streamable_http_mcp_configuration_redacts_secret_values(self):
        _, created = self.request("/api/mcps", "POST", {"name": "Remote Demo", "transport": "streamable-http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer secret-value"}, "env": {"TOKEN": "secret-value"}})
        connection = next(item for item in created["connections"] if item["name"] == "Remote Demo")
        self.assertEqual(connection["transport"], "streamable-http")
        self.assertEqual(connection["headerKeys"], ["Authorization"])
        self.assertNotIn("secret-value", json.dumps(created))
        _, disabled = self.request(f"/api/mcps/{connection['id']}/toggle", "POST", {"enabled": False})
        self.assertFalse(disabled["enabled"])

    def test_mcp_diagnostics_returns_redacted_failure_details(self):
        _, created = self.request("/api/mcps", "POST", {"name": "Diagnostic Demo", "transport": "streamable-http", "url": "https://example.com/mcp", "authMode": "bearer", "headers": {"Authorization": "Bearer secret-value"}})
        connection = next(item for item in created["connections"] if item["name"] == "Diagnostic Demo")
        with patch.object(server, "mcp_diagnostics", return_value={"ok": False, "tools": [], "error": "connection refused", "authMode": "bearer"}):
            status, diagnostic = self.request(f"/api/mcps/{connection['id']}/diagnostics")
        self.assertEqual(status, 200)
        self.assertFalse(diagnostic["ok"])
        self.assertNotIn("secret-value", json.dumps(diagnostic))

    def test_attachment_batch_limit_is_explicit(self):
        with self.assertRaises(HTTPError) as caught:
            self.request("/api/attachments", "POST", {"paths": [str(self.root / f"file-{index}.txt") for index in range(11)]})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.read()
        caught.exception.close()


if __name__ == "__main__":
    unittest.main()
