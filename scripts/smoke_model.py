"""Run a real, isolated Qwen tool-use smoke test against local Ollama."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="qwen-agent-smoke-") as folder:
        workspace = Path(folder)
        job_id = "real-model-smoke"
        server.JOBS[job_id] = {
            "id": job_id, "status": "running", "phase": "queued", "activity": "Starting",
            "events": [], "message": None, "error": None, "createdAt": 0, "updatedAt": 0,
            "finishedAt": None, "metrics": {}, "artifacts": [], "requiresArtifacts": False,
            "cancelRequested": False, "_response": None,
        }
        incoming = {
            "messages": [{"role": "user", "content": "Create smoke.txt containing exactly: Qwen tools work. Then read it back and finish."}],
            "mode": "fast",
        }
        with patch.object(server, "project_workspace", return_value=workspace), \
             patch.object(server, "active_project", return_value={"name": "Smoke test", "path": str(workspace)}), \
             patch.object(server, "connected_mcp_tools", return_value=([], {})), \
             patch.object(server, "load_mcps", return_value=[]):
            server.run_agent_job(job_id, incoming)

        job = server.JOBS[job_id]
        target = workspace / "smoke.txt"
        if job["status"] != "complete": raise RuntimeError(job.get("error") or "Agent did not complete")
        if not target.is_file(): raise RuntimeError("Qwen completed without creating smoke.txt")
        if target.read_text(encoding="utf-8").strip() != "Qwen tools work.": raise RuntimeError("smoke.txt had unexpected content")
        print(f"real model smoke ok: {len(job['events'])} events, artifacts={job['artifacts']}")


if __name__ == "__main__":
    main()
