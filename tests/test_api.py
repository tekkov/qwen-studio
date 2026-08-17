import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
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
        _, thread = self.request("/api/threads", "POST", {"projectId": project_id, "mode": "balanced"})
        note = self.root / "note.txt"
        note.write_text("attachment API smoke test", encoding="utf-8")
        _, attachments = self.request("/api/attachments", "POST", {"threadId": thread["id"], "paths": [str(note)]})
        _, threads = self.request(f"/api/threads?projectId={project_id}")

        self.assertEqual(attachments["items"][0]["kind"], "text")
        self.assertEqual(threads["items"][0]["id"], thread["id"])

    def test_terminal_streams_output_and_exits(self):
        _, run = self.request("/api/terminal", "POST", {"command": "Write-Output 'terminal smoke ok'"})
        for _ in range(50):
            _, current = self.request(f"/api/terminal/{run['id']}")
            if current["status"] != "running": break
            time.sleep(0.05)
        self.assertEqual(current["status"], "complete")
        self.assertEqual(current["exitCode"], 0)
        self.assertIn("terminal smoke ok", current["output"])


if __name__ == "__main__":
    unittest.main()
