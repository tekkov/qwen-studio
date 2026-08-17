import tempfile
import json
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

    def test_codex_supervisor_parses_jsonl_evidence_without_exposing_credentials(self):
        class FakeProcess:
            pid = 4123
            stdout = iter([
                json.dumps({"type": "thread.started", "thread_id": "session-1"}) + "\n",
                json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "git status"}}) + "\n",
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Reviewed the project and found no blocking issue."}}) + "\n",
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 20}}) + "\n",
            ])
            def wait(self): return 0

        with tempfile.TemporaryDirectory() as folder:
            job = {"id": "supervisor-test", "status": "running", "events": [], "metrics": {}, "supervisorEnabled": True, "cancelRequested": False}
            with patch.object(server, "load_runtime_settings", return_value={"enabled": True, "mode": "milestones", "maxRunsPerJob": 4, "dailyBudgetUsd": 5, "sandbox": "read-only"}), \
                 patch.object(server, "supervisor_usage_file", return_value=Path(folder) / "usage.json"), \
                 patch.object(server, "codex_command", return_value="codex"), \
                 patch.object(server.shutil, "which", return_value="codex"), \
                 patch.object(server.subprocess, "Popen", return_value=FakeProcess()):
                result = server.run_codex_supervisor(job, "final verification", Path(folder), "Review the current files.")
            self.assertTrue(result["ok"])
            self.assertTrue(any(event["kind"] == "supervisor_complete" for event in job["events"]))
            self.assertTrue(any("Reviewed the project" in event["text"] for event in job["events"]))

    def test_codex_supervisor_budget_blocks_another_run(self):
        with tempfile.TemporaryDirectory() as folder:
            job = {"id": "budget-test", "status": "running", "events": [], "metrics": {}, "supervisorEnabled": True, "cancelRequested": False}
            with patch.object(server, "load_runtime_settings", return_value={"enabled": True, "mode": "milestones", "maxRunsPerJob": 0, "dailyBudgetUsd": 5, "sandbox": "read-only"}), patch.object(server, "supervisor_usage_file", return_value=Path(folder) / "usage.json"):
                result = server.run_codex_supervisor(job, "milestone", Path(folder), "Review")
            self.assertFalse(result["ok"])
            self.assertTrue(any(event["kind"] == "supervisor_budget" for event in job["events"]))

    def test_watchdog_reports_stale_model_without_stopping_it(self):
        class StopAfterNotice:
            def __init__(self): self.calls = 0
            def wait(self, _seconds):
                self.calls += 1
                return self.calls > 1

        job = {"id": "watchdog-test", "status": "running", "phase": "generating", "updatedAt": 0, "events": [], "metrics": {"lastChunkAt": 0}, "cancelRequested": False}
        with patch.object(server, "persist_jobs", return_value=None):
            server.job_watchdog(job, Path("."), StopAfterNotice())
        self.assertTrue(any(event["kind"] == "watchdog" for event in job["events"]))
        self.assertEqual(job["status"], "running")

    def test_repeated_failure_becomes_actionable_blocked_state(self):
        job = {"id": "blocked-test", "status": "running", "events": [], "metrics": {}}
        with patch.object(server, "persist_jobs", return_value=None):
            self.assertFalse(server.record_job_failure(job, "ollama-disconnect", "offline"))
            self.assertFalse(server.record_job_failure(job, "ollama-disconnect", "offline"))
            self.assertTrue(server.record_job_failure(job, "ollama-disconnect", "offline"))
        self.assertEqual(job["status"], "blocked")
        self.assertEqual(job["phase"], "blocked")
        self.assertTrue(any(event["kind"] == "blocked" for event in job["events"]))

    def test_permission_profiles_gate_external_and_destructive_actions(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            self.assertIsNone(server.tool_approval_requirement("write_file", {"path": "inside.txt"}, workspace, "project-write"))
            outside = server.tool_approval_requirement("write_file", {"path": str(workspace.parent / "outside.txt")}, workspace, "project-write")
            self.assertIn("outside", outside["reason"])
            destructive = server.tool_approval_requirement("run_command", {"command": "Remove-Item old.txt"}, workspace, "full-access")
            self.assertIn("destructive", destructive["reason"])
            network = server.tool_approval_requirement("run_command", {"command": "Invoke-WebRequest https://example.com"}, workspace, "project-write")
            self.assertIn("external", network["reason"])
            readonly = server.tool_approval_requirement("run_command", {"command": "Get-ChildItem"}, workspace, "read-only")
            self.assertIsNotNone(readonly)


if __name__ == "__main__":
    unittest.main()
