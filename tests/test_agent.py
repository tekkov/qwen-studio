import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class AgentCompletionGuardTests(unittest.TestCase):
    def setUp(self):
        server.JOBS.clear()

    def test_build_task_is_forced_to_create_a_file_before_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            responses = iter([
                ({"role": "assistant", "content": "I can describe the website."}, {"eval_count": 4, "eval_duration": 1_000_000_000}),
                ({"role": "assistant", "tool_calls": [{"function": {"name": "write_file", "arguments": {"path": "index.html", "content": "<h1>Built</h1>"}}}]}, {}),
                ({"role": "assistant", "content": "Created and verified index.html."}, {"eval_count": 5, "eval_duration": 1_000_000_000}),
            ])
            job_id = "build-test"
            server.JOBS[job_id] = {
                "id": job_id, "status": "running", "phase": "queued", "activity": "Starting", "events": [],
                "message": None, "error": None, "createdAt": 0, "updatedAt": 0, "finishedAt": None,
                "metrics": {}, "artifacts": [], "requiresArtifacts": False, "cancelRequested": False, "_response": None,
            }
            incoming = {"messages": [{"role": "user", "content": "Build a website for me"}], "mode": "fast"}
            with patch.object(server, "project_workspace", return_value=workspace), \
                 patch.object(server, "active_project", return_value={"name": "Test", "path": str(workspace)}), \
                 patch.object(server, "connected_mcp_tools", return_value=([], {})), \
                 patch.object(server, "stream_ollama_chat", side_effect=lambda payload, job: next(responses)):
                server.run_agent_job(job_id, incoming)

            job = server.JOBS[job_id]
            self.assertEqual(job["status"], "complete")
            self.assertEqual(job["artifacts"], ["index.html"])
            self.assertEqual((workspace / "index.html").read_text(encoding="utf-8"), "<h1>Built</h1>")
            self.assertTrue(any(event["kind"] == "guardrail" for event in job["events"]))

    def test_plain_question_can_complete_without_writing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            payloads = []
            job_id = "chat-test"
            server.JOBS[job_id] = {
                "id": job_id, "status": "running", "phase": "queued", "activity": "Starting", "events": [],
                "message": None, "error": None, "createdAt": 0, "updatedAt": 0, "finishedAt": None,
                "metrics": {}, "artifacts": [], "requiresArtifacts": False, "cancelRequested": False, "_response": None,
            }
            incoming = {"messages": [{"role": "user", "content": "What is a closure?"}], "mode": "fast"}
            with patch.object(server, "project_workspace", return_value=Path(folder)), \
                 patch.object(server, "active_project", return_value=None), \
                 patch.object(server, "connected_mcp_tools", return_value=([], {})), \
                 patch.object(server, "stream_ollama_chat", side_effect=lambda payload, job: (payloads.append(payload) or ({"role": "assistant", "content": "A closure captures scope."}, {"eval_count": 5, "eval_duration": 1_000_000_000}))):
                server.run_agent_job(job_id, incoming)

            self.assertEqual(server.JOBS[job_id]["status"], "complete")
            self.assertEqual(server.JOBS[job_id]["artifacts"], [])
            self.assertEqual(payloads[0]["options"]["num_predict"], -1)
            self.assertTrue(server.JOBS[job_id]["metrics"]["unlimitedRun"])

    def test_empty_response_is_rejected_and_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            responses = iter([
                ({"role": "assistant"}, {}),
                ({"role": "assistant", "content": "The project work is complete and verified."}, {"eval_count": 8, "eval_duration": 1_000_000_000}),
            ])
            job_id = "empty-response-test"
            server.JOBS[job_id] = {
                "id": job_id, "status": "running", "phase": "queued", "activity": "Starting", "events": [],
                "message": None, "error": None, "createdAt": 0, "updatedAt": 0, "finishedAt": None,
                "metrics": {}, "artifacts": [], "requiresArtifacts": False, "cancelRequested": False, "_response": None,
            }
            incoming = {"messages": [{"role": "user", "content": "Explain this project"}], "mode": "fast"}
            with patch.object(server, "project_workspace", return_value=Path(folder)), \
                 patch.object(server, "active_project", return_value=None), \
                 patch.object(server, "connected_mcp_tools", return_value=([], {})), \
                 patch.object(server, "stream_ollama_chat", side_effect=lambda payload, job: next(responses)):
                server.run_agent_job(job_id, incoming)

            self.assertEqual(server.JOBS[job_id]["status"], "complete")
            self.assertTrue(any(event["kind"] == "guardrail" and "no visible answer" in event["text"] for event in server.JOBS[job_id]["events"]))

    def test_agent_powershell_reports_process_and_live_output(self):
        with tempfile.TemporaryDirectory() as folder:
            job = {"events": [], "metrics": {}, "updatedAt": 0, "cancelRequested": False}
            output = server.run_command_streamed("Write-Output 'live progress'", Path(folder), job)
            self.assertIn("exit_code=0", output)
            self.assertIn("live progress", output)
            self.assertTrue(any(event["kind"] == "process" for event in job["events"]))
            self.assertTrue(any(event["kind"] == "process_output" and "live progress" in event["text"] for event in job["events"]))


if __name__ == "__main__":
    unittest.main()
