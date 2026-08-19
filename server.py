import base64
import hashlib
import hmac
import html
import json
import mimetypes
import os
import queue
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
HOST, PORT = "127.0.0.1", int(os.getenv("QWEN_PORT", "8000"))
API_TOKEN = os.getenv("QWEN_API_TOKEN", "")
ALLOWED_ORIGINS = {"http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"}
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("QWEN_MODEL", "qwen3:8b")
FAST_MODEL = os.getenv("QWEN_FAST_MODEL", "qwen2.5:1.5b")
def user_data_dir():
    override = os.getenv("QWEN_DATA_DIR")
    if override: return Path(override)
    if os.name == "nt": return Path(os.getenv("APPDATA", ROOT)) / "QwenLocalAgent"
    if sys.platform == "darwin": return Path(os.getenv("HOME", ROOT)) / "Library" / "Application Support" / "QwenLocalAgent"
    return Path(os.getenv("XDG_DATA_HOME", Path(os.getenv("HOME", ROOT)) / ".local" / "share")) / "QwenLocalAgent"

DATA_DIR = user_data_dir()
MCP_FILE = DATA_DIR / "mcp.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
THREADS_FILE = DATA_DIR / "threads.json"
ATTACHMENTS_FILE = DATA_DIR / "attachments.json"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
MCP_BRIDGE = ROOT / "mcp-bridge.mjs"
JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_PERSIST_LOCK = threading.Lock()
JOBS_LOADED = False
JOBS_SOURCE = None
AGENT_LOCK = threading.Lock()
TERMINAL_RUNS = {}
TERMINAL_LOCK = threading.Lock()
APPROVAL_CONDITIONS = {}
APPROVAL_LOCK = threading.Lock()
PAUSE_CONDITIONS = {}
PAUSE_LOCK = threading.Lock()
THREADS_LOCK = threading.RLock()
ATTACHMENTS_LOCK = threading.RLock()
MODEL_INFO_CACHE = {"at": 0, "value": None}
CODEX_STATUS_CACHE = {"at": 0, "value": None}

def shell_command(command):
    """Return the platform's native interactive shell invocation."""
    if os.name == "nt": return ["powershell", "-NoLogo", "-NoProfile", "-Command", command]
    return [os.getenv("SHELL", "/bin/sh"), "-lc", command]

def process_options(new_session=False):
    if os.name == "nt": return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {"start_new_session": True} if new_session else {}

def stop_process(process):
    if not process or process.poll() is not None: return
    if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10, **process_options())
    else:
        try: os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError): process.terminate()

def stop_process_id(process_id):
    if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process_id), "/T", "/F"], capture_output=True, timeout=10, **process_options())
    else: os.kill(int(process_id), signal.SIGTERM)

SUPERVISOR_DEFAULTS = {
    "enabled": False,
    "mode": "milestones",
    "maxRunsPerJob": 4,
    "dailyBudgetUsd": 5.0,
    "sandbox": "workspace-write",
    "lowResource": False,
    "permissionProfile": "project-write",
    "outputTokens": -1,
    "processPriority": "normal",
    "supervisorCadence": "milestones",
    "idleOnly": False,
    "busyProcesses": "",
}

PROFILES = {
    "fast": {"label": "Fast", "num_ctx": 32768, "temperature": 0.2, "think": False},
    "balanced": {"label": "Balanced", "num_ctx": 65536, "temperature": 0.18, "think": False},
    "deep": {"label": "Deep", "num_ctx": 131072, "temperature": 0.15, "think": True},
}

def ollama_model_info():
    now = time.time()
    cache_seconds = 60 if (MODEL_INFO_CACHE.get("value") or {}).get("available") else 3
    if MODEL_INFO_CACHE["value"] is not None and now - MODEL_INFO_CACHE["at"] < cache_seconds:
        return MODEL_INFO_CACHE["value"]
    value = {"available": False, "state": "offline", "message": "Ollama is not reachable yet.", "capabilities": [], "nativeContext": None}
    try:
        request = Request(f"{OLLAMA_URL}/api/show", data=json.dumps({"model": MODEL}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response: details = json.loads(response.read())
        model_info = details.get("model_info", {})
        context = next((number for key, number in model_info.items() if key.endswith(".context_length")), None)
        value = {"available": True, "state": "ready", "message": "Ollama and the selected model are ready.", "capabilities": details.get("capabilities", []), "nativeContext": context, "parameterSize": details.get("details", {}).get("parameter_size"), "quantization": details.get("details", {}).get("quantization_level")}
    except HTTPError as error:
        if error.code in (400, 404): value.update({"state": "model-missing", "message": f"Model {MODEL} is not installed in Ollama."})
    except Exception: pass
    MODEL_INFO_CACHE.update({"at": now, "value": value})
    return value

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".sql", ".sh", ".ps1", ".bat", ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".rb", ".php", ".swift", ".kt"}
DOCUMENT_EXTENSIONS = {".pdf", ".docx"}

SYSTEM = """You are Qwen, a local coding agent running on the user's computer. Work as a careful, capable collaborator: inspect before changing, explain important decisions, use tools when useful, and verify your work. You have local filesystem and native shell tools, plus any connected MCP tools. Never claim a tool action succeeded unless its result confirms it.

Execution rules:
- When the user asks you to create, build, implement, change, or fix something, perform the work with tools. Do not merely describe steps or paste the intended artifact into chat.
- Put generated code and content into real files with write_file (or a scaffolding command that creates files). Creating an empty directory is only setup and never completes a build task.
- For implementation work, follow this visible sequence: inspect the relevant files, explain the intended change briefly, edit the real files, run a focused verification command, then summarize the exact files changed and what was verified.
- Never claim that code was added, changed, or tested unless a tool result proves it. If no file or command tool was used, say that no code change was made.
- Keep tool calls focused. Do not spend a long generation writing source code into your chat response when that code belongs in a file.
- Treat the active project folder as authoritative context. For questions about the project, inspect the relevant files instead of guessing from general knowledge.
- Continue from the current on-disk project state after a steered or interrupted turn; previously completed tool actions may already have changed files.
- Before finishing an implementation task, inspect the created files and run a relevant verification command when possible. State exactly what was created and tested.
- Final answers must be structured as: What I did; Files changed (or “No files changed”); Verification; Remaining issues or next step. Keep internal chain-of-thought private and report observable actions and evidence instead."""

BUILT_IN_TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List files and folders at a local path.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file at a local path.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or replace a text file with exact content.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a native shell command as the current user and return its output.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "get_terminal_output", "description": "Read the latest output and status from the app's integrated project terminal.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_git_status", "description": "Inspect the current Git branch, changed files, and diff summary without changing repository state.", "parameters": {"type": "object", "properties": {}}}}
]

MCP_LIBRARY = [
    {"id": "filesystem", "name": "Filesystem", "description": "Give Qwen access to a chosen directory through an MCP server.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\path\\to\\workspace"]},
    {"id": "github", "name": "GitHub", "description": "Work with repositories, issues, and pull requests. Requires GitHub authentication.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    {"id": "playwright", "name": "Playwright", "description": "Automate browser-based research and testing locally.", "command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
    {"id": "postgres", "name": "PostgreSQL", "description": "Connect Qwen to a PostgreSQL database using a server you configure.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:password@localhost/database"]},
    {"id": "remote-mcp", "name": "Remote MCP", "description": "Connect to a Streamable HTTP MCP endpoint with optional bearer headers.", "transport": "streamable-http", "authMode": "bearer", "url": "https://your-mcp.example.com/mcp", "args": []}
]

def load_mcps():
    try:
        return json.loads(MCP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

def save_mcps(mcps):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MCP_FILE.write_text(json.dumps(mcps, indent=2), encoding="utf-8")

def public_mcp(config):
    safe = {key: value for key, value in config.items() if key not in ("env", "headers")}
    if config.get("env"): safe["environmentKeys"] = sorted(config["env"].keys())
    if config.get("headers"): safe["headerKeys"] = sorted(config["headers"].keys())
    return safe

def settings_file():
    return DATA_DIR / "settings.json"

def jobs_file():
    return DATA_DIR / "jobs.json"

def load_runtime_settings():
    settings = dict(SUPERVISOR_DEFAULTS)
    try:
        stored = json.loads(settings_file().read_text(encoding="utf-8"))
        if isinstance(stored, dict): settings.update({key: value for key, value in stored.items() if key in settings})
    except (OSError, json.JSONDecodeError): pass
    settings["enabled"] = bool(settings.get("enabled"))
    settings["maxRunsPerJob"] = max(0, min(int(settings.get("maxRunsPerJob") or 0), 20))
    settings["dailyBudgetUsd"] = max(0.0, min(float(settings.get("dailyBudgetUsd") or 0), 1000.0))
    settings["outputTokens"] = max(-1, min(int(settings.get("outputTokens") or -1), 1_000_000))
    if settings.get("processPriority") not in ("normal", "below-normal"): settings["processPriority"] = "normal"
    if settings.get("supervisorCadence") not in ("milestones", "failures", "continuous"): settings["supervisorCadence"] = "milestones"
    settings["idleOnly"] = bool(settings.get("idleOnly"))
    settings["busyProcesses"] = ",".join(item.strip().lower().replace(".exe", "") for item in str(settings.get("busyProcesses") or "").split(",") if item.strip())[:500]
    if settings.get("mode") not in ("milestones", "failures", "continuous"): settings["mode"] = "milestones"
    if settings.get("sandbox") not in ("read-only", "workspace-write"): settings["sandbox"] = "workspace-write"
    if settings.get("permissionProfile") not in ("read-only", "project-write", "full-access"): settings["permissionProfile"] = "project-write"
    return settings

def save_runtime_settings(settings):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    clean = dict(SUPERVISOR_DEFAULTS); clean.update({key: settings.get(key, value) for key, value in SUPERVISOR_DEFAULTS.items()})
    settings_file().write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean

def codex_command():
    configured = os.getenv("CODEX_COMMAND", "codex")
    return shutil.which(configured) or configured

def codex_cli_status():
    now = time.time()
    if CODEX_STATUS_CACHE["value"] is not None and now - CODEX_STATUS_CACHE["at"] < 30:
        return dict(CODEX_STATUS_CACHE["value"])
    command = codex_command()
    available = bool(shutil.which(command) or Path(command).is_file())
    status = {"available": available, "command": Path(command).name if available else "codex", "authenticated": False, "method": "none", "message": "Codex CLI is not installed." if not available else "Not checked."}
    if not available:
        CODEX_STATUS_CACHE.update({"at": now, "value": status}); return status
    try:
        result = subprocess.run([command, "login", "status"], capture_output=True, text=True, timeout=8, cwd=ROOT, **process_options())
        output = redact_text((result.stdout or "") + "\n" + (result.stderr or ""))
        lower = output.lower()
        status["authenticated"] = result.returncode == 0
        status["method"] = "api" if "api key" in lower or "api-key" in lower else "chatgpt" if "chatgpt" in lower else "unknown" if status["authenticated"] else "none"
        status["message"] = output.strip()[-280:] or ("Authenticated" if status["authenticated"] else "Not authenticated.")
    except Exception as error:
        status["message"] = redact_text(str(error))
    CODEX_STATUS_CACHE.update({"at": now, "value": status})
    return status

def supervisor_status():
    settings = load_runtime_settings()
    api_key_available = bool(os.getenv("OPENAI_API_KEY") or os.getenv("CODEX_API_KEY"))
    status = codex_cli_status()
    try:
        usage = json.loads(supervisor_usage_file().read_text(encoding="utf-8"))
        if usage.get("date") != time.strftime("%Y-%m-%d"): usage = {"runs": 0, "estimatedUsd": 0.0}
    except (OSError, json.JSONDecodeError): usage = {"runs": 0, "estimatedUsd": 0.0}
    status.update({"enabled": settings["enabled"], "mode": settings["mode"], "maxRunsPerJob": settings["maxRunsPerJob"], "dailyBudgetUsd": settings["dailyBudgetUsd"], "sandbox": settings["sandbox"], "permissionProfile": settings["permissionProfile"], "lowResource": bool(settings.get("lowResource")), "outputTokens": settings["outputTokens"], "processPriority": settings["processPriority"], "supervisorCadence": settings["supervisorCadence"], "idleOnly": settings["idleOnly"], "busyProcesses": settings["busyProcesses"], "usageRuns": int(usage.get("runs") or 0), "usageEstimatedUsd": float(usage.get("estimatedUsd") or 0), "apiKeyAvailable": api_key_available, "effectiveMethod": "api" if api_key_available else status.get("method", "none")})
    return status

def lower_process_priority(process):
    """Best-effort Windows resource kindness for optional game/low-resource mode."""
    settings = load_runtime_settings()
    if not process or (not settings.get("lowResource") and settings.get("processPriority") != "below-normal") or os.name != "nt": return
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", f"$p=Get-Process -Id {int(process.pid)} -ErrorAction SilentlyContinue; if ($p) {{ $p.PriorityClass='BelowNormal' }}"], capture_output=True, timeout=8, **process_options())
    except Exception: pass

def detected_busy_processes(settings=None):
    settings = settings or load_runtime_settings()
    wanted = {item.strip().lower().replace(".exe", "") for item in str(settings.get("busyProcesses") or "").split(",") if item.strip()}
    if not wanted or os.name != "nt": return []
    try:
        result = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process | Select-Object -ExpandProperty ProcessName)"], capture_output=True, text=True, timeout=8, **process_options())
        running = {line.strip().lower() for line in result.stdout.splitlines() if line.strip()}
        return sorted(wanted & running)
    except Exception:
        return []

def path_is_within(path, workspace):
    try:
        Path(path).resolve().relative_to(Path(workspace).resolve())
        return True
    except (ValueError, OSError):
        return False

def tool_approval_requirement(name, arguments, workspace, profile):
    """Return a plain-language approval request for risky actions, or None when auto-approved."""
    if name == "write_file":
        target = resolve_workspace_path(arguments.get("path", ""), workspace).resolve()
        if profile == "read-only": return {"reason": "This session is read-only, so writing a file needs your approval.", "action": "Write a file", "target": str(target)}
        if not path_is_within(target, workspace): return {"reason": "This file is outside the active project folder.", "action": "Write a file outside the project", "target": str(target)}
    if name == "run_command":
        command = str(arguments.get("command", "")); lower = command.lower()
        destructive = re.search(r"\b(remove-item|del\s|erase\s|rmdir\s|rm\s|sudo\s|shutdown\s|reboot\s|mkfs\b|dd\s|chmod\s|chown\s|kill\s|pkill\s|format-\w+|git\s+(reset|checkout|clean|restore)|stop-process|taskkill)\b", lower)
        network = re.search(r"\b(invoke-webrequest|invoke-restmethod|curl\s|wget\s|iwr\s|irm\s|start-bitstransfer|git\s+(clone|fetch|pull|push)|npm\s+(install|i|ci)|pip\s+install|pip3\s+install)\b", lower)
        if profile == "read-only": return {"reason": "This session is read-only, so running a computer command needs your approval.", "action": "Run a shell command", "command": redact_text(command)}
        if destructive: return {"reason": "This potentially destructive command can delete, reset, stop, or otherwise change existing computer state.", "action": "Run a potentially destructive command", "command": redact_text(command)}
        if network: return {"reason": "This command connects to an external service or downloads data.", "action": "Run a network command", "command": redact_text(command)}
    if name.startswith("mcp__"):
        return {"reason": "MCP tools can affect external services or data, so this action needs a visible approval.", "action": "Run an MCP tool", "tool": name, "input": redact_text(json.dumps(arguments, ensure_ascii=False))[:1200]}
    return None

def wait_for_tool_approval(job, name, arguments, workspace):
    profile = job.get("permissionProfile") or load_runtime_settings().get("permissionProfile", "project-write")
    request = tool_approval_requirement(name, arguments, workspace, profile)
    if not request: return True, None
    approval_id = uuid.uuid4().hex[:12]
    pending = {"id": approval_id, "tool": name, "request": request, "profile": profile, "createdAt": time.time(), "decision": None}
    with JOBS_LOCK: job["pendingApproval"] = pending
    add_job_event(job, "approval_required", f"Qwen is waiting for your approval before it can {request['action'].lower()}.", {"Why": request["reason"], **{key: value for key, value in request.items() if key not in ("reason", "action")}})
    update_job_activity(job, "approval", f"Waiting for your approval: {request['action'].lower()}.", approvalId=approval_id)
    with APPROVAL_LOCK:
        condition = APPROVAL_CONDITIONS.setdefault(job["id"], threading.Condition(APPROVAL_LOCK))
    while True:
        with JOBS_LOCK:
            decision = (job.get("pendingApproval") or {}).get("decision")
            cancelled = bool(job.get("cancelRequested"))
        if cancelled:
            with JOBS_LOCK: job.pop("pendingApproval", None)
            return False, "Approval cancelled because the job was stopped."
        if decision in ("approved", "denied"):
            with JOBS_LOCK: job.pop("pendingApproval", None)
            if decision == "approved":
                add_job_event(job, "approval_granted", f"Approval granted. Qwen may now {request['action'].lower()}.", {"Approval ID": approval_id})
                return True, None
            add_job_event(job, "approval_denied", f"Approval denied. Qwen will receive the denial and choose another path.", {"Approval ID": approval_id})
            return False, "The user denied this action. Choose a safe alternative or explain what is blocked."
        with condition: condition.wait(timeout=1.0)

def wait_if_paused(job):
    if not job.get("pauseRequested"): return
    with JOBS_LOCK:
        job["phase"] = "paused"; job["activity"] = "Paused safely before the next Qwen or computer action."; job["updatedAt"] = time.time()
    add_job_event(job, "paused", "The run is paused safely. No new model or computer action will start until you resume it.")
    with PAUSE_LOCK:
        condition = PAUSE_CONDITIONS.setdefault(job["id"], threading.Condition(PAUSE_LOCK))
    while True:
        with JOBS_LOCK:
            paused = bool(job.get("pauseRequested")); cancelled = bool(job.get("cancelRequested"))
        if cancelled: raise RuntimeError("Stopped by user.")
        if not paused:
            with JOBS_LOCK: job["phase"] = "setup"; job["activity"] = "Resuming from the current project state."; job["updatedAt"] = time.time()
            add_job_event(job, "resumed", "The pause ended. Qwen will continue from the current project state.")
            return
        with condition: condition.wait(timeout=1.0)

def wait_if_busy_processes(job):
    """Optional idle-only mode: wait for user-configured game/heavy processes to clear."""
    settings = load_runtime_settings()
    if not settings.get("idleOnly") or not settings.get("busyProcesses"): return
    announced = False
    while True:
        if job.get("cancelRequested"): raise RuntimeError("Stopped by user.")
        busy = detected_busy_processes(settings)
        if not busy:
            if announced: add_job_event(job, "idle_ready", "The configured busy processes are no longer running. Qwen is continuing now.", {"Processes": "None detected"})
            return
        if not announced:
            announced = True
            add_job_event(job, "idle_wait", "Idle-only mode is waiting so Qwen does not compete with your active game or heavy process.", {"Detected processes": ", ".join(busy), "Action": "No model or computer action will start until they close."})
        update_job_activity(job, "waiting", f"Waiting for idle time because {', '.join(busy)} is running.")
        time.sleep(5)

def load_project_state():
    try:
        state = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        if isinstance(state, dict) and isinstance(state.get("items"), list): return state
    except (OSError, json.JSONDecodeError): pass
    return {"active": None, "items": []}

def save_project_state(state):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def load_thread_state():
    with THREADS_LOCK:
        try:
            state = json.loads(THREADS_FILE.read_text(encoding="utf-8"))
            if isinstance(state, dict) and isinstance(state.get("items"), list): return state
        except (OSError, json.JSONDecodeError): pass
        return {"version": 1, "items": []}

def save_thread_state(state):
    with THREADS_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = THREADS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(THREADS_FILE)

def thread_by_id(thread_id):
    return next((item for item in load_thread_state()["items"] if item.get("id") == thread_id), None)

def create_thread(project_id=None, title="New chat", mode="fast"):
    now = time.time()
    thread = {"id": uuid.uuid4().hex, "projectId": project_id, "title": title or "New chat", "mode": mode, "pinned": False, "archived": False, "createdAt": now, "updatedAt": now, "messages": []}
    with THREADS_LOCK:
        state = load_thread_state(); state["items"].append(thread); save_thread_state(state)
    return thread

def update_thread(thread_id, updater):
    with THREADS_LOCK:
        state = load_thread_state()
        thread = next((item for item in state["items"] if item.get("id") == thread_id), None)
        if not thread: return None
        updater(thread)
        thread["updatedAt"] = time.time()
        save_thread_state(state)
        return thread

def append_thread_message(thread_id, role, content, attachments=None):
    message = {"id": uuid.uuid4().hex, "role": role, "content": content, "attachments": attachments or [], "createdAt": time.time()}
    def append(thread):
        thread.setdefault("messages", []).append(message)
        if role == "user" and (thread.get("title") in (None, "", "New chat")):
            clean = re.sub(r"\s+", " ", str(content)).strip()
            thread["title"] = (clean[:57] + "...") if len(clean) > 60 else (clean or "New chat")
    return update_thread(thread_id, append), message

def model_messages(messages):
    prepared = []
    for item in messages:
        if item.get("role") not in ("user", "assistant"): continue
        message = {"role": item.get("role"), "content": str(item.get("content", ""))}
        image_paths = []
        for attachment_id in item.get("attachments", [])[-8:]:
            attachment = attachment_by_id(attachment_id)
            if not attachment: continue
            if attachment.get("kind") in ("text", "document") and attachment.get("extractedText"):
                message["content"] += f"\n\n[Attached file: {attachment['name']}]\n{attachment['extractedText']}"
            elif attachment.get("kind") == "document" and attachment.get("guidance"):
                message["content"] += f"\n\n[Attached document: {attachment['name']}]\nThe app could not extract its text: {attachment['guidance']}"
            elif attachment.get("kind") == "image": image_paths.append(attachment.get("storedPath"))
            elif attachment.get("kind") == "video": image_paths.extend(attachment.get("derivedFrames", []))
            else: message["content"] += f"\n\n[Attached file available at: {attachment.get('storedPath')}]"
        images = []
        for image_path in image_paths[:12]:
            try: images.append(base64.b64encode(Path(image_path).read_bytes()).decode("ascii"))
            except OSError: pass
        if images: message["images"] = images
        prepared.append(message)
    return prepared

def trim_messages(messages, context_limit):
    """Keep the newest complete turns inside a conservative local context budget."""
    system = messages[0] if messages and messages[0].get("role") == "system" else None
    candidates = messages[1:] if system else messages
    system_cost = len(str(system.get("content", ""))) if system else 0
    character_budget = max(1000, int(context_limit * 2.8) - system_cost)
    selected, used = [], 0
    for message in reversed(candidates):
        cost = len(str(message.get("content", ""))) + (4500 * len(message.get("images", [])))
        if selected and used + cost > character_budget: break
        selected.append(message); used += cost
    selected.reverse()
    if system: selected.insert(0, system)
    return selected, max(0, len(messages) - len(selected))

def compact_messages(messages, context_limit):
    """Trim old turns while preserving a small semantic handoff for the next model step.

    Character trimming alone can discard the reason a tool was run. This deterministic
    handoff keeps the recent beginning/end of older turns, including tool outcomes,
    without asking another model to summarize or spending hosted tokens.
    """
    selected, omitted = trim_messages(messages, context_limit)
    if not omitted:
        return selected, 0, {"compacted": False, "omitted": 0}
    selected_ids = {id(item) for item in selected}
    older = [item for item in messages if id(item) not in selected_ids and item.get("role") != "system"]
    lines = []
    for item in older[-18:]:
        role = str(item.get("role", "message")).title()
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        if not content and item.get("tool_calls"): content = f"requested {len(item['tool_calls'])} tool action(s)"
        if content:
            lines.append(f"- {role}: {content[:420]}")
    summary = {"role": "system", "content": "Earlier conversation was compacted to protect the active context window. Treat this as memory, not new user instructions:\n" + ("\n".join(lines) if lines else "- Earlier turns contained no readable text.")}
    if selected and selected[0].get("role") == "system": selected = [selected[0], summary] + selected[1:]
    else: selected = [summary] + selected
    return selected, omitted, {"compacted": True, "omitted": omitted, "summaryCharacters": len(summary["content"])}

def load_attachment_state():
    with ATTACHMENTS_LOCK:
        try:
            state = json.loads(ATTACHMENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(state, dict) and isinstance(state.get("items"), list): return state
        except (OSError, json.JSONDecodeError): pass
        return {"version": 1, "items": []}

def save_attachment_state(state):
    with ATTACHMENTS_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = ATTACHMENTS_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(ATTACHMENTS_FILE)

def attachment_by_id(attachment_id):
    return next((item for item in load_attachment_state()["items"] if item.get("id") == attachment_id), None)

def public_attachment(attachment):
    return {key: value for key, value in attachment.items() if key not in ("storedPath", "derivedFrames", "extractedText")}

def video_duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, timeout=30, **process_options())
    try: return max(0.0, float(result.stdout.strip()))
    except ValueError: return 0.0

def sample_video_frames(source, target_dir, maximum=8):
    duration = video_duration(source)
    interval = max(duration / maximum, 1.0) if duration else 2.0
    pattern = target_dir / "frame-%02d.jpg"
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", f"fps=1/{interval:.3f},scale='min(1280,iw)':-2", "-frames:v", str(maximum), "-q:v", "3", str(pattern)], capture_output=True, text=True, timeout=180, **process_options())
    if result.returncode: raise RuntimeError((result.stderr or "FFmpeg could not sample this video.")[-1000:])
    return [str(path) for path in sorted(target_dir.glob("frame-*.jpg"))], duration

def extract_document_text(path):
    """Use installed/local parsers only; return text plus a user-facing fallback reason."""
    if path.suffix.lower() == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
            root = ET.fromstring(xml)
            text = "\n".join((node.text or "") for node in root.iter() if node.tag.endswith("}t"))
            return html.unescape(text)[:120000], None
        except Exception as error:
            return "", f"DOCX text extraction failed: {error}"
    if path.suffix.lower() == ".pdf":
        executable = shutil.which("pdftotext")
        if not executable: return "", "PDF text extraction needs pdftotext or another PDF parser installed on this computer."
        result = subprocess.run([executable, "-layout", str(path), "-"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, **process_options())
        if result.returncode: return "", (result.stderr or "PDF text extraction failed.")[-500:]
        return result.stdout[:120000], None
    return "", "This file type is stored locally but has no built-in text extractor. Attach a supported text, image, video, PDF, or DOCX file, or ask Qwen to inspect it with a tool."

def ingest_attachment(source_path, thread_id=None):
    source = Path(source_path)
    if not source.is_file(): raise FileNotFoundError(f"File not found: {source}")
    size = source.stat().st_size
    if size > 500 * 1024 * 1024: raise ValueError(f"{source.name} is larger than the 500 MB local attachment limit.")
    identifier = uuid.uuid4().hex
    target_dir = ATTACHMENTS_DIR / identifier; target_dir.mkdir(parents=True, exist_ok=False)
    try:
        target = target_dir / source.name; shutil.copy2(source, target)
        extension = source.suffix.lower(); mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        kind = "image" if extension in IMAGE_EXTENSIONS else "video" if extension in VIDEO_EXTENSIONS else "text" if extension in TEXT_EXTENSIONS else "document" if extension in DOCUMENT_EXTENSIONS else "file"
        attachment = {"id": identifier, "threadId": thread_id, "name": source.name, "kind": kind, "mimeType": mime, "size": size, "createdAt": time.time(), "storedPath": str(target), "derivedFrames": [], "extractedText": "", "status": "ready", "guidance": None}
        if kind == "text":
            attachment["extractedText"] = target.read_text(encoding="utf-8", errors="replace")[:120000]
        elif kind == "document":
            attachment["extractedText"], attachment["guidance"] = extract_document_text(target)
            if attachment["guidance"] and not attachment["extractedText"]: attachment["status"] = "needs-parser"
        elif kind == "file":
            attachment["status"] = "unsupported"
            attachment["guidance"] = "This file type is stored locally but has no built-in text extractor. Attach a supported text, image, video, PDF, or DOCX file, or ask Qwen to inspect it with a tool."
        elif kind == "video":
            frames, duration = sample_video_frames(target, target_dir)
            if not frames: raise RuntimeError("No readable frames were found in this video.")
            attachment["derivedFrames"] = frames; attachment["durationSeconds"] = round(duration, 2); attachment["frameCount"] = len(frames)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise
    with ATTACHMENTS_LOCK:
        state = load_attachment_state(); state["items"].append(attachment); save_attachment_state(state)
    return attachment

def active_project():
    state = load_project_state()
    return next((item for item in state["items"] if item["id"] == state.get("active")), None)

def activate_project_id(project_id):
    state = load_project_state()
    project = next((item for item in state["items"] if item.get("id") == project_id), None)
    if not project: return None
    state["active"] = project_id; save_project_state(state)
    return project

def project_workspace():
    project = active_project()
    if project and Path(project["path"]).is_dir(): return Path(project["path"])
    return ROOT

def project_context_snapshot(workspace):
    """Build a bounded manifest so every project chat starts from real folder context."""
    try:
        entries = sorted(workspace.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))[:120]
    except OSError:
        return "The project folder could not be scanned."
    manifest = [f"- {'file' if item.is_file() else 'folder'}: {item.name}" for item in entries]
    excerpts, used = [], 0
    for name in ("AGENTS.md", "README.md", "package.json", "pyproject.toml", "Cargo.toml"):
        path = workspace / name
        if not path.is_file(): continue
        try: content = path.read_text(encoding="utf-8", errors="replace")[:6000]
        except OSError: continue
        if used + len(content) > 12000: break
        excerpts.append(f"\n[{name}]\n{content}"); used += len(content)
    workflow_roots = [workspace / ".qwen" / "workflows", workspace / ".codex" / "skills"]
    for root in workflow_roots:
        if not root.is_dir(): continue
        try: workflow_files = sorted(root.rglob("*.md"), key=lambda item: str(item).lower())[:12]
        except OSError: workflow_files = []
        for path in workflow_files:
            try: content = path.read_text(encoding="utf-8", errors="replace")[:3500]
            except OSError: continue
            if used + len(content) > 24000: break
            excerpts.append(f"\n[Local workflow: {path.relative_to(workspace)}]\n{content}"); used += len(content)
    return "Project top-level manifest:\n" + ("\n".join(manifest) if manifest else "- The folder is currently empty.") + "".join(excerpts)

def resolve_workspace_path(value, workspace):
    path = Path(value)
    return path if path.is_absolute() else workspace / path

def mcp_id(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "mcp"

def bridge(payload, timeout=45):
    result = subprocess.run(["node", str(MCP_BRIDGE)], input=json.dumps(payload), text=True, capture_output=True, timeout=timeout, cwd=ROOT, **process_options())
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "MCP bridge failed").strip()[-1000:])
    return json.loads(result.stdout)

def mcp_diagnostics(config):
    """Return a redacted connection diagnosis without exposing header or env values."""
    started = time.time()
    try:
        result = bridge({"action": "list", "config": config}, timeout=30)
        return {"ok": True, "tools": result.get("tools", []), "transport": config.get("transport"), "authMode": config.get("authMode", "none"), "elapsedMs": round((time.time() - started) * 1000)}
    except Exception as error:
        return {"ok": False, "tools": [], "transport": config.get("transport"), "authMode": config.get("authMode", "none"), "elapsedMs": round((time.time() - started) * 1000), "error": redact_text(str(error))[-1800:]}

def connected_mcp_tools():
    tools, mapping = [], {}
    for config in load_mcps():
        if not config.get("enabled") or config.get("transport") not in ("stdio", "streamable-http"):
            continue
        try:
            result = bridge({"action": "list", "config": config})
            for tool in result.get("tools", []):
                tool_name = f"mcp__{config['id'].replace('-', '_')}__{tool['name']}"
                mapping[tool_name] = (config, tool["name"])
                tools.append({"type": "function", "function": {"name": tool_name, "description": f"[{config['name']}] {tool.get('description', '')}", "parameters": tool.get("inputSchema", {"type": "object", "properties": {}})}})
        except Exception:
            continue
    return tools, mapping

def git_snapshot(workspace):
    snapshot = {"available": False, "isRepository": False, "branch": None, "status": [], "diffStat": "", "worktrees": [], "error": None}
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=workspace, capture_output=True, text=True, timeout=15, **process_options())
        if root.returncode != 0: return snapshot
        status = subprocess.run(["git", "status", "--short"], cwd=workspace, capture_output=True, text=True, timeout=15, **process_options())
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=workspace, capture_output=True, text=True, timeout=15, **process_options())
        diff = subprocess.run(["git", "diff", "--stat"], cwd=workspace, capture_output=True, text=True, timeout=15, **process_options())
        worktrees = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=workspace, capture_output=True, text=True, timeout=15, **process_options())
        snapshot.update({"available": True, "isRepository": True, "branch": branch.stdout.strip() or "detached HEAD", "status": [redact_text(line) for line in status.stdout.splitlines() if line.strip()][:200], "diffStat": redact_text(diff.stdout[-6000:]), "worktrees": [line[5:] for line in worktrees.stdout.splitlines() if line.startswith("worktree ")][:50]})
    except FileNotFoundError: snapshot["error"] = "Git is not installed or not on PATH."
    except Exception as error: snapshot["error"] = redact_text(str(error))
    return snapshot

def git_diff_preview(workspace, relative_path=None):
    command = ["git", "diff", "--no-ext-diff", "--unified=3"]
    if relative_path:
        target = resolve_workspace_path(relative_path, workspace).resolve()
        if not path_is_within(target, workspace): raise PermissionError("Diff preview is limited to the active project folder.")
        command.extend(["--", str(target.relative_to(Path(workspace).resolve()))])
    result = subprocess.run(command, cwd=workspace, capture_output=True, text=True, timeout=30, **process_options())
    if result.returncode: raise RuntimeError(result.stderr.strip() or "Git diff could not be read.")
    return {"path": relative_path, "preview": redact_text(result.stdout[-40000:]), "truncated": len(result.stdout) > 40000}

def project_file_review(workspace, relative_path):
    target = resolve_workspace_path(relative_path, workspace).resolve()
    if not path_is_within(target, workspace): raise PermissionError("File review is limited to the active project folder.")
    if not target.is_file(): raise FileNotFoundError(f"File not found: {relative_path}")
    if target.stat().st_size > 2 * 1024 * 1024: return {"path": str(relative_path), "binary": False, "content": "This file is larger than the 2 MB review limit.", "truncated": True}
    try:
        return {"path": str(relative_path), "binary": False, "content": target.read_text(encoding="utf-8", errors="replace")[:40000], "truncated": target.stat().st_size > 40000}
    except OSError as error:
        return {"path": str(relative_path), "binary": True, "content": f"Binary or unreadable file: {redact_text(error)}", "truncated": False}

def run_tool(name, arguments, mcp_mapping, workspace):
    if name in mcp_mapping:
        config, remote_name = mcp_mapping[name]
        result = bridge({"action": "call", "config": config, "tool": remote_name, "arguments": arguments}, timeout=180)
        return json.dumps(result.get("content", result), ensure_ascii=False)[-12000:]
    if name == "list_files":
        target = resolve_workspace_path(arguments.get("path") or ".", workspace)
        if not target.is_dir(): raise FileNotFoundError(f"Folder not found: {target}")
        lines = []
        for item in sorted(target.iterdir(), key=lambda entry: (entry.is_file(), entry.name.lower()))[:500]:
            kind = "file" if item.is_file() else "folder"
            size = item.stat().st_size if item.is_file() else "-"
            lines.append(f"{kind}\t{size}\t{item.name}")
        return "\n".join(lines)
    if name == "read_file":
        return resolve_workspace_path(arguments["path"], workspace).read_text(encoding="utf-8")[-12000:]
    if name == "write_file":
        target = resolve_workspace_path(arguments["path"], workspace)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(arguments.get("content", ""), encoding="utf-8")
        return f"Wrote {target}"
    if name == "run_command":
        result = subprocess.run(shell_command(arguments.get("command", "")), cwd=workspace, capture_output=True, text=True, timeout=900, **process_options())
        return f"exit_code={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"[-12000:]
    if name == "get_terminal_output":
        with TERMINAL_LOCK:
            latest = max(TERMINAL_RUNS.values(), key=lambda item: item.get("createdAt", 0), default=None)
            return json.dumps(terminal_payload(latest), ensure_ascii=False)[-12000:] if latest else "No terminal commands have been run yet."
    if name == "get_git_status":
        return json.dumps(git_snapshot(workspace), ensure_ascii=False)
    return f"Unknown tool: {name}"

def run_command_streamed(command, workspace, job):
    """Run the native shell with live, bounded output events and cancellation."""
    process = subprocess.Popen(
        shell_command(command), cwd=workspace,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
        **process_options(new_session=True),
    )
    lower_process_priority(process)
    add_job_event(job, "process", f"Shell started process {process.pid} in {workspace}.", {"Process ID": process.pid, "Working folder": str(workspace), "Command": redact_text(command)})
    lines = queue.Queue()
    def read_output():
        try:
            with process.stdout:
                for line in process.stdout: lines.put(line)
        finally: lines.put(None)
    threading.Thread(target=read_output, daemon=True).start()
    output, pending, reader_done, last_event = [], [], False, time.time()
    while process.poll() is None or not reader_done or not lines.empty():
        try: line = lines.get(timeout=0.2)
        except queue.Empty: line = ""
        if line is None: reader_done = True
        elif line:
            output.append(line); pending.append(line.rstrip())
            update_job_activity(job, "tool", f"Shell process {process.pid} is running: {line.strip()[:180]}", processId=process.pid, lastCommandOutput=line.strip()[:500])
        if pending and (time.time() - last_event >= 0.8 or len(pending) >= 8 or (process.poll() is not None and reader_done)):
            preview = redact_text("\n".join(pending))[-2000:]
            add_job_event(job, "process_output", f"Shell output: {preview}", {"Process ID": process.pid})
            pending.clear(); last_event = time.time()
        if job.get("cancelRequested") and process.poll() is None:
            stop_process(process)
    exit_code = process.wait()
    if pending:
        preview = redact_text("\n".join(pending))[-2000:]
        add_job_event(job, "process_output", f"Shell output: {preview}", {"Process ID": process.pid})
    text = "".join(output)
    if re.search(r"(?i)(npm\s+(run\s+)?test|pytest|python\s+-m\s+unittest|cargo\s+test|dotnet\s+test)", command):
        job.setdefault("metrics", {}).setdefault("testResults", []).append({"command": redact_text(command), "exitCode": exit_code, "passed": exit_code == 0, "at": time.time()})
        add_job_event(job, "test_result", "The command was recognized as a test run and its result was recorded for the completion review.", {"Command": redact_text(command), "Exit code": exit_code, "Result": "Passed" if exit_code == 0 else "Failed"})
    return f"exit_code={exit_code}\nSTDOUT:\n{text}\nSTDERR:\n"[-12000:]

def persist_jobs():
    """Persist resumable job metadata without exposing private request state via the API."""
    with JOBS_LOCK:
        rows = []
        for job in JOBS.values():
            row = job_payload(job)
            if job.get("_request") is not None: row["resumeRequest"] = job["_request"]
            rows.append(row)
    with JOB_PERSIST_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        temporary = jobs_file().with_suffix(".tmp")
        temporary.write_text(json.dumps({"version": 1, "items": rows[-100:]}, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(jobs_file())

def ensure_jobs_loaded():
    global JOBS_LOADED, JOBS_SOURCE
    source = str(jobs_file().resolve())
    if JOBS_LOADED and JOBS_SOURCE == source: return
    with JOB_PERSIST_LOCK:
        if JOBS_LOADED and JOBS_SOURCE == source: return
        try: state = json.loads(jobs_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): state = {"items": []}
        with JOBS_LOCK:
            if JOBS_SOURCE != source: JOBS.clear()
            for saved in state.get("items", []) if isinstance(state, dict) else []:
                if not isinstance(saved, dict) or not saved.get("id"): continue
                saved["_request"] = saved.pop("resumeRequest", None)
                if saved.get("status") == "running":
                    saved["status"] = "interrupted"; saved["phase"] = "interrupted"; saved["activity"] = "The app restarted while this job was running. Resume it to continue from the current project files."
                    saved["finishedAt"] = time.time()
                    saved.setdefault("events", []).append({"at": round(time.time()), "kind": "interrupted", "text": "Qwen Studio restarted before this job finished. No completed file actions were replayed.", "detail": {"Next action": "Resume the job to continue from the current files."}})
                JOBS[saved["id"]] = saved
        JOBS_LOADED = True
        JOBS_SOURCE = source

def checkpoint_job(job, label, detail=None):
    with JOBS_LOCK:
        job["checkpoint"] = {"label": label, "at": time.time(), "detail": detail or {}}
    add_job_event(job, "checkpoint", f"Saved a recovery checkpoint: {label}.", {"Checkpoint": label, **(detail or {})})

def add_job_event(job, kind, text, detail=None):
    with JOBS_LOCK:
        now = time.time()
        job["updatedAt"] = now
        job.setdefault("events", []).append({"at": round(now), "kind": kind, "text": redact_text(text), "detail": detail})
        if len(job["events"]) > 600: job["events"] = job["events"][-600:]
    persist_jobs()

def job_payload(job):
    return {key: value for key, value in job.items() if not key.startswith("_")}

def task_needs_artifacts(messages):
    latest = next((str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"), "")
    return bool(re.search(r"(?i)\b(build|create|make|implement|code|develop|scaffold|set up|setup|write|design|fix|update|change)\b", latest))

def command_creates_artifacts(command):
    return bool(re.search(r"(?i)(set-content|out-file|add-content|npm\s+create|npx\s+create-|create-vite|create-next-app|new-item\s+[^\r\n]*-itemtype\s+file|(?:^|\s)>\s*[^&])", command or ""))

def verification_snapshot(job, workspace):
    """Collect cheap local evidence before allowing an implementation job to finish."""
    artifact_checks = []
    for artifact in job.get("artifacts", []):
        if artifact.startswith("Files created by"):
            artifact_checks.append({"artifact": artifact, "exists": True, "reason": "The shell reported a scaffolding action."})
            continue
        path = resolve_workspace_path(artifact, workspace)
        artifact_checks.append({"artifact": artifact, "exists": path.is_file() or path.is_dir()})
    changed_files = []
    try:
        result = subprocess.run(["git", "status", "--short"], cwd=workspace, capture_output=True, text=True, timeout=20, **process_options())
        changed_files = [redact_text(line) for line in result.stdout.splitlines()[:120] if line.strip()]
    except Exception:
        changed_files = []
    artifacts_ok = all(item.get("exists") for item in artifact_checks) if artifact_checks else not job.get("requiresArtifacts")
    verification = {"artifacts": artifact_checks, "artifactsOk": artifacts_ok, "changedFiles": changed_files, "checkedAt": time.time(), "note": "Git status is informational; tool results are the source of truth for file actions."}
    with JOBS_LOCK:
        job["verification"] = verification; job["changedFiles"] = changed_files
    add_job_event(job, "verification", "Checked the requested artifacts and captured the current project change list before completion.", {"Artifacts verified": f"{sum(1 for item in artifact_checks if item.get('exists'))}/{len(artifact_checks)}", "Changed files reported": len(changed_files), "Files": ", ".join(changed_files[:20]) or "No Git changes reported", "Completion gate": "Passed" if artifacts_ok else "Blocked until required artifacts exist"})
    return verification

class BlockedJobError(RuntimeError):
    """Internal signal used when automatic recovery is no longer safe."""

def record_job_failure(job, category, message, threshold=3):
    """Count repeated failures and expose a durable, actionable blocked state."""
    with JOBS_LOCK:
        metrics = job.setdefault("metrics", {})
        failures = metrics.setdefault("failureCounts", {})
        failures[category] = int(failures.get(category) or 0) + 1
        count = failures[category]
        recovery_attempts = int(metrics.get("resumeCount") or 0)
    if count < threshold and recovery_attempts < threshold:
        return False
    with JOBS_LOCK:
        job["status"] = "blocked"
        job["phase"] = "blocked"
        job["error"] = f"The run is blocked after repeated {category} failures."
        job["blockedReason"] = redact_text(message)
        job["finishedAt"] = time.time()
    add_job_event(job, "blocked", f"Qwen is blocked because the same {category} problem kept recurring. No more automatic actions will run.", {"Reason": redact_text(message)[:1600], "Recovery attempts": recovery_attempts, "Failure count": count, "Next step": "Review the current files and fix the blocker, then resume or send a new instruction."})
    return True

def job_watchdog(job, workspace, stop_event):
    """Observe progress and surface stalls without imposing an automatic model timeout."""
    last_notice = 0
    while not stop_event.wait(5):
        with JOBS_LOCK:
            status = job.get("status")
            phase = job.get("phase")
            metrics = dict(job.get("metrics", {}))
            updated = job.get("updatedAt", time.time())
        if status not in ("running", "verifying"): return
        now = time.time()
        last_output = metrics.get("lastChunkAt") or updated
        stale = max(0, int(now - last_output))
        if phase in ("model", "generating") and stale >= 20 and now - last_notice >= 20:
            last_notice = now
            add_job_event(job, "watchdog", f"Qwen has produced no new model output for {stale} seconds. The run is still allowed to continue; the watchdog is checking whether it is processing or stalled.", {"Phase": phase, "Seconds since model output": stale, "Automatic timeout": "Disabled"})
            update_job_activity(job, phase, f"Qwen is still processing; no new model output for {stale} seconds. The watchdog is observing, not terminating the run.", staleSeconds=stale)
            if stale >= 120 and job.get("supervisorEnabled") and not job.get("watchdogEscalated"):
                with JOBS_LOCK: job["watchdogEscalated"] = True
                run_codex_supervisor(job, "stall diagnosis", workspace, f"Qwen has produced no model output for {stale} seconds. Inspect the current project and determine whether the local worker is processing, blocked, or needs recovery. Do not claim completion without evidence.")
        elif phase == "tool" and stale >= 30 and now - last_notice >= 20:
            last_notice = now
            add_job_event(job, "watchdog", f"A computer tool has not reported progress for {stale} seconds. The watchdog is waiting for the process while keeping the project state safe.", {"Seconds since tool output": stale, "Working folder": str(workspace)})

def update_job_activity(job, phase, text, **metrics):
    with JOBS_LOCK:
        job["phase"] = phase
        job["activity"] = text
        job["updatedAt"] = time.time()
        if metrics:
            job.setdefault("metrics", {}).update(metrics)
    persist_jobs()

def stream_ollama_chat(payload, job):
    payload["stream"] = True
    request = Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    message = {"role": "assistant", "content": "", "thinking": "", "tool_calls": []}
    final = {}
    started = time.time()
    chunks = 0
    first_chunk_at = None
    with urlopen(request) as response:
        with JOBS_LOCK: job["_response"] = response
        for raw_line in response:
            if job.get("cancelRequested"):
                raise RuntimeError("Stopped by user.")
            if not raw_line.strip():
                continue
            chunk = json.loads(raw_line)
            if first_chunk_at is None:
                first_chunk_at = time.time()
                update_job_activity(job, "generating", "Qwen started responding.", firstTokenSeconds=round(first_chunk_at - started, 2))
            part = chunk.get("message", {})
            message["content"] += part.get("content") or ""
            message["thinking"] += part.get("thinking") or ""
            if part.get("tool_calls"):
                message["tool_calls"].extend(part["tool_calls"])
            chunks += 1
            stage = "Qwen is drafting the next user-facing update." if message["content"] else "Qwen is deciding which files or tools are needed next."
            update_job_activity(job, "generating", stage, streamChunks=chunks, generatedCharacters=len(message["content"]), responsePreview=message["content"][-1600:], elapsedSeconds=round(time.time() - started, 1), lastChunkAt=time.time())
            if chunk.get("done"):
                final = chunk
    if job.get("cancelRequested"):
        raise RuntimeError("Stopped by user.")
    content = message.get("content", "")
    if "</think>" in content and "<think>" not in content:
        content = content.rsplit("</think>", 1)[-1]
    else:
        content = re.sub(r"(?is)<think>.*?</think>", "", content)
    message["content"] = content.strip()
    message = {key: value for key, value in message.items() if value not in ("", [], None)}
    return message, final

def performance_details(result):
    eval_count = int(result.get("eval_count") or 0)
    eval_duration = int(result.get("eval_duration") or 0)
    prompt_count = int(result.get("prompt_eval_count") or 0)
    prompt_duration = int(result.get("prompt_eval_duration") or 0)
    tps = (eval_count / (eval_duration / 1_000_000_000)) if eval_count and eval_duration else 0
    prompt_tps = (prompt_count / (prompt_duration / 1_000_000_000)) if prompt_count and prompt_duration else 0
    return {
        "Generated tokens": eval_count,
        "Prompt tokens": prompt_count,
        "Generation speed": f"{tps:.1f} tokens/second" if tps else "Not reported",
        "Prompt processing": f"{prompt_tps:.1f} tokens/second" if prompt_tps else "Not reported",
        "Model time": f"{int(result.get('total_duration') or 0) / 1_000_000_000:.1f} seconds",
    }

def record_model_step(job, result, profile, step):
    eval_count = int(result.get("eval_count") or 0); prompt_count = int(result.get("prompt_eval_count") or 0)
    eval_duration = int(result.get("eval_duration") or 0); prompt_duration = int(result.get("prompt_eval_duration") or 0)
    generation_tps = eval_count / (eval_duration / 1_000_000_000) if eval_count and eval_duration else 0
    prompt_tps = prompt_count / (prompt_duration / 1_000_000_000) if prompt_count and prompt_duration else 0
    with JOBS_LOCK:
        metrics = job.setdefault("metrics", {})
        metrics["totalPromptTokens"] = int(metrics.get("totalPromptTokens") or 0) + prompt_count
        metrics["totalGeneratedTokens"] = int(metrics.get("totalGeneratedTokens") or 0) + eval_count
        metrics["contextBudget"] = profile["num_ctx"]
        metrics["lastPromptTokens"] = prompt_count
        metrics["lastGeneratedTokens"] = eval_count
        metrics["lastGenerationTps"] = round(generation_tps, 2)
    usage = (prompt_count / profile["num_ctx"] * 100) if prompt_count else 0
    add_job_event(job, "model_complete", "Qwen finished this decision step and is checking whether another file or tool action is needed.", {
        "Context used": f"{prompt_count:,} / {profile['num_ctx']:,} tokens ({usage:.1f}%)",
        "Prompt processing speed": f"{prompt_tps:.1f} tokens/second" if prompt_tps else "Not reported",
        "Generation speed": f"{generation_tps:.1f} tokens/second" if generation_tps else "Not reported",
        "Running totals": f"{job['metrics']['totalPromptTokens']:,} prompt · {job['metrics']['totalGeneratedTokens']:,} generated tokens",
    })

def run_terminal_command(run_id, command, workspace):
    run = TERMINAL_RUNS[run_id]
    try:
        process = subprocess.Popen(
            shell_command(command),
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **process_options(new_session=True),
        )
        with TERMINAL_LOCK:
            run["process"] = process
            run["pid"] = process.pid
        lower_process_priority(process)
        with process.stdout:
            for line in process.stdout:
                with TERMINAL_LOCK:
                    run["output"] = (run["output"] + line)[-100000:]
                    run["updatedAt"] = time.time()
        exit_code = process.wait()
        with TERMINAL_LOCK:
            run["exitCode"] = exit_code
            run["status"] = "stopped" if run.get("stopRequested") else "complete"
            run["finishedAt"] = time.time()
            run["updatedAt"] = run["finishedAt"]
            run["process"] = None
    except Exception as error:
        with TERMINAL_LOCK:
            run["status"] = "error"
            run["error"] = str(error)
            run["output"] += f"\nTerminal error: {error}\n"
            run["finishedAt"] = time.time()
            run["updatedAt"] = run["finishedAt"]
            run["process"] = None

def terminal_payload(run):
    return {key: value for key, value in run.items() if key != "process"}

def redact_text(value):
    text = str(value or "")
    text = re.sub(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)[^\s;]+", r"\1\2[redacted]", text)
    text = re.sub(r"(?i)(https?://[^:/\s]+:)[^@/\s]+@", r"\1[redacted]@", text)
    text = re.sub(r"\b(sk-[A-Za-z0-9_-]{10,})\b", "[redacted-key]", text)
    return text

def supervisor_usage_file():
    return DATA_DIR / "supervisor-usage.json"

def supervisor_budget_reserve(settings):
    today = time.strftime("%Y-%m-%d")
    with JOB_PERSIST_LOCK:
        try: usage = json.loads(supervisor_usage_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError): usage = {}
        if usage.get("date") != today: usage = {"date": today, "runs": 0, "estimatedUsd": 0.0}
        estimate = float(os.getenv("CODEX_ESTIMATED_RUN_COST_USD", "0.25"))
        if usage["runs"] >= int(settings.get("maxRunsPerJob") or 0): return False, "This job reached its Codex supervisor run limit."
        if float(usage.get("estimatedUsd") or 0) + estimate > float(settings.get("dailyBudgetUsd") or 0): return False, "The configured daily Codex supervisor budget has been reached."
        usage["runs"] += 1; usage["estimatedUsd"] = round(float(usage.get("estimatedUsd") or 0) + estimate, 4)
        DATA_DIR.mkdir(parents=True, exist_ok=True); supervisor_usage_file().write_text(json.dumps(usage, indent=2), encoding="utf-8")
        return True, None

def run_codex_supervisor(job, stage, workspace, instruction):
    """Run an optional Codex review and stream JSONL events into the same job timeline."""
    settings = load_runtime_settings()
    if not bool(job.get("supervisorEnabled")):
        return {"enabled": False, "ok": True, "message": "Codex supervision is disabled for this job."}
    allowed, reason = supervisor_budget_reserve(settings)
    if not allowed:
        add_job_event(job, "supervisor_budget", reason, {"Stage": stage, "Action": "Continue with Qwen and local verification"})
        return {"enabled": True, "ok": False, "message": reason}
    command = codex_command()
    if not (shutil.which(command) or Path(command).is_file()):
        message = "Codex supervision is enabled, but the Codex CLI was not found on this computer."
        add_job_event(job, "supervisor_error", message, {"Stage": stage, "Command": "codex"})
        return {"enabled": True, "ok": False, "message": message}
    sandbox = settings.get("sandbox", "workspace-write")
    prompt = f"""You are the supervisory reviewer for a local Qwen coding agent.
Stage: {stage}
Project folder: {workspace}
Your job is to inspect the current on-disk state and provide a concise, evidence-based review. Do not invent work. Identify what Qwen actually changed, what is incomplete, which tests or commands matter, and the safest next action. If a small harness or project repair is clearly required, make it in the project folder and then verify it. Do not expose credentials.

User/task context:
{instruction}

Return a final summary with: observed state, action taken, verification evidence, remaining risk, and next step."""
    environment = os.environ.copy()
    if environment.get("OPENAI_API_KEY") and not environment.get("CODEX_API_KEY"):
        environment["CODEX_API_KEY"] = environment["OPENAI_API_KEY"]
    args = [command, "exec", "--json", "--sandbox", sandbox, "--skip-git-repo-check", prompt]
    add_job_event(job, "supervisor_started", f"Codex supervisor started a {stage} review of the current project state.", {"Stage": stage, "Sandbox": sandbox, "Action": "Inspect, verify, and report evidence"})
    update_job_activity(job, "supervisor", f"Codex is reviewing the project after Qwen's {stage} milestone.")
    final_text, session_id, usage = "", None, {}
    try:
        process = subprocess.Popen(args, cwd=workspace, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1, **process_options(new_session=True))
        lower_process_priority(process)
        job["supervisorPid"] = process.pid
        started = time.time()
        for raw in process.stdout:
            if job.get("cancelRequested"):
                if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10, **process_options())
                else: process.terminate()
                break
            if time.time() - started > 600:
                if os.name == "nt": subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10, **process_options())
                else: process.terminate()
                add_job_event(job, "supervisor_error", "Codex supervisor exceeded its 10-minute review window and was stopped.", {"Stage": stage})
                break
            line = raw.strip()
            if not line: continue
            try: event = json.loads(line)
            except json.JSONDecodeError:
                add_job_event(job, "supervisor_output", redact_text(line)[-1200:], {"Stage": stage})
                continue
            event_type = event.get("type", "event")
            if event_type == "thread.started": session_id = event.get("thread_id")
            if event_type == "turn.completed": usage = event.get("usage") or {}
            item = event.get("item") or {}
            item_type = item.get("type", event_type)
            if item_type in ("agent_message", "message") and item.get("text"):
                final_text = str(item.get("text")); add_job_event(job, "supervisor_message", redact_text(final_text)[-3000:], {"Stage": stage})
            elif item_type in ("command_execution", "file_change", "mcp_tool_call", "reasoning", "plan_update"):
                description = item.get("command") or item.get("text") or item.get("title") or item_type.replace("_", " ").title()
                add_job_event(job, "supervisor_action", redact_text(str(description))[-1600:], {"Stage": stage, "Item": item_type})
            update_job_activity(job, "supervisor", f"Codex supervisor is reporting {item_type.replace('_', ' ')} activity.", supervisorStage=stage, supervisorSessionId=session_id)
        exit_code = process.wait()
        job.pop("supervisorPid", None)
        if exit_code == 0:
            add_job_event(job, "supervisor_complete", f"Codex finished the {stage} review.", {"Stage": stage, "Session": session_id or "Not reported", "Input tokens": usage.get("input_tokens", "Not reported"), "Output tokens": usage.get("output_tokens", "Not reported"), "Review": redact_text(final_text)[-1800:] or "No final review text reported."})
            return {"enabled": True, "ok": True, "message": final_text, "sessionId": session_id, "usage": usage}
        message = f"Codex supervisor exited with code {exit_code}. Qwen can continue, but the review was not completed."
        add_job_event(job, "supervisor_error", message, {"Stage": stage, "Exit code": exit_code})
        return {"enabled": True, "ok": False, "message": message, "sessionId": session_id}
    except Exception as error:
        job.pop("supervisorPid", None)
        message = f"Codex supervisor could not run: {redact_text(error)}"
        add_job_event(job, "supervisor_error", message, {"Stage": stage})
        return {"enabled": True, "ok": False, "message": message}

def describe_tool(name, arguments):
    if name.startswith("mcp__"):
        parts = name.split("__", 2)
        server = parts[1].replace("_", " ") if len(parts) > 1 else "connected server"
        tool = parts[2].replace("_", " ") if len(parts) > 2 else name
        return f"Asking the {server} MCP connection to run “{tool}”.", {"Component": "MCP client", "Server": server, "Tool": tool, "Input": redact_text(json.dumps(arguments, ensure_ascii=False))[:1200]}
    if name == "list_files":
        path = arguments.get("path") or str(ROOT)
        return f"Looking inside {path} to understand the folder structure.", {"Component": "Filesystem", "Action": "List directory contents", "Path": path}
    if name == "read_file":
        path = arguments.get("path", "")
        return f"Reading {path} so Qwen can understand its current contents.", {"Component": "Filesystem", "Action": "Read text file", "Path": path}
    if name == "write_file":
        path = arguments.get("path", "")
        size = len(arguments.get("content", ""))
        return f"Saving generated code or content to {path}.", {"Component": "Filesystem", "Action": "Create or replace file", "Path": path, "Content size": f"{size:,} characters"}
    if name == "run_command":
        command = redact_text(arguments.get("command", ""))
        lower = command.lower()
        if "npm install" in lower: explanation = "Installing the project’s JavaScript packages and their dependencies."
        elif "npm create" in lower or "create-vite" in lower or "create-next-app" in lower: explanation = "Creating the initial website project structure from a framework template."
        elif "new-item" in lower or "mkdir" in lower: explanation = "Creating a new folder or file on the computer."
        elif "npm run build" in lower: explanation = "Building the project to check that the production version compiles successfully."
        elif "npm test" in lower or "pytest" in lower: explanation = "Running automated tests to check the work."
        elif "git" in lower: explanation = "Using Git to inspect or update the project’s version history."
        else: explanation = "Running a shell command needed for the current task."
        return explanation, {"Component": "Shell", "Action": "Run command", "Command": command}
    if name == "get_terminal_output":
        return "Checking the integrated terminal to see what the latest command is doing.", {"Component": "Integrated terminal", "Action": "Read latest output"}
    if name == "get_git_status":
        return "Checking the repository branch and changed files without modifying Git state.", {"Component": "Git review", "Action": "Read branch, status, and diff summary"}
    return f"Using the {name} tool.", {"Component": "Agent tool", "Tool": name, "Input": redact_text(json.dumps(arguments, ensure_ascii=False))[:1200]}

def describe_tool_result(name, arguments, output, ok):
    if not ok:
        return "That action failed, so Qwen will receive the error and can choose a different approach.", {"Result": "Failed", "Error": redact_text(output)[:1200]}
    if name == "write_file":
        content = str(arguments.get("content", ""))
        lines = len(content.splitlines())
        return f"Added or updated code in {arguments.get('path', 'the file')} ({lines:,} lines) and saved it to disk.", {"Result": "Success", "Change made": "File written to disk", "Path": arguments.get("path", ""), "Lines written": lines}
    if name == "list_files":
        lines = [line for line in output.splitlines() if line.strip()]
        return f"Folder scan finished and returned {len(lines)} lines of information to Qwen.", {"Result": "Success", "Output preview": redact_text("\n".join(lines[:12]))}
    if name == "read_file":
        return f"File reading finished; {len(output):,} characters were returned to Qwen.", {"Result": "Success", "Output size": f"{len(output):,} characters"}
    if name == "run_command":
        match = re.search(r"exit_code=(\d+)", output)
        exit_code = match.group(1) if match else "unknown"
        preview = redact_text(output.split("STDOUT:\n", 1)[-1].split("STDERR:\n", 1)[0]).strip()[:1200]
        detail = {"Result": "Success" if exit_code == "0" else "Command finished", "Exit code": exit_code}
        if preview: detail["Output preview"] = preview
        return f"The shell finished with exit code {exit_code}. Qwen can now inspect the result and choose the next action.", detail
    if name == "get_terminal_output":
        return "The latest integrated terminal output was returned to Qwen.", {"Result": "Success", "Output preview": redact_text(output)[:1200]}
    if name == "get_git_status":
        return "The repository review is ready for inspection.", {"Result": "Success", "Output preview": redact_text(output)[:1600]}
    return "The tool finished and returned its result to Qwen.", {"Result": "Success", "Output preview": redact_text(output)[:1200]}

def run_agent_job(job_id, incoming):
    job = JOBS[job_id]
    watchdog_stop = threading.Event()
    job["_watchdog_stop"] = watchdog_stop
    try:
        messages = incoming.get("messages", [])
        mode = incoming.get("mode", "fast")
        if not messages: raise ValueError("Add a message first.")
        requires_artifacts = task_needs_artifacts(messages)
        with JOBS_LOCK: job["requiresArtifacts"] = requires_artifacts
        add_job_event(job, "started", "The desktop app accepted your request and created a background agent job.", {"Component": "Qwen Studio", "Action": "Create job", "Job ID": job_id[:12]})
        update_job_activity(job, "setup", "Preparing the project and tools.")
        workspace = project_workspace()
        with JOBS_LOCK:
            job.setdefault("metrics", {})["queueWaitSeconds"] = round(max(0, time.time() - job.get("createdAt", time.time())), 2)
        threading.Thread(target=job_watchdog, args=(job, workspace, watchdog_stop), daemon=True).start()
        project = active_project()
        add_job_event(job, "setup", "Opening the active project and checking which computer tools and MCP connections Qwen can use.", {"Project": project["name"] if project else "Qwen Studio folder", "Working folder": str(workspace), "Built-in tools": "Read files, write files, list folders, native shell", "MCP connections": len(load_mcps())})
        if requires_artifacts:
            add_job_event(job, "plan", "Plan: inspect the relevant files, make the requested code change, run a focused verification, then report the exact files changed.", {"Implementation task": "Yes", "Next": "Inspect before editing"})
        else:
            add_job_event(job, "plan", "Plan: inspect the available context, answer the request, and show any verification evidence used.", {"Implementation task": "No file change detected from the request"})
        checkpoint_job(job, "Workspace and tool inventory", {"Project": project["name"] if project else "Qwen Studio folder", "Working folder": str(workspace)})
        mcp_tools, mcp_mapping = connected_mcp_tools()
        if mcp_tools: add_job_event(job, "mcp", f"Loaded {len(mcp_tools)} MCP tool{'s' if len(mcp_tools) != 1 else ''}.")
        snapshot = project_context_snapshot(workspace)
        workspace_prompt = f"\n\nThe active project folder is: {workspace}. Resolve relative file paths and shell work inside this folder. Use the following real project snapshot as orientation, then inspect relevant files with tools before making project-specific claims.\n\n{snapshot}"
        conversation = [{"role": "system", "content": SYSTEM + workspace_prompt}] + messages
        run_codex_supervisor(job, "kickoff", workspace, str(messages[-1].get("content", "")))
        profile = PROFILES.get(mode, PROFILES["fast"])
        active_model = FAST_MODEL if mode == "fast" else MODEL
        options = {"temperature": profile["temperature"], "num_ctx": profile["num_ctx"], "num_predict": load_runtime_settings().get("outputTokens", -1)}
        think = profile["think"]
        reported_omitted = 0
        step = 0
        while True:
            wait_if_paused(job)
            wait_if_busy_processes(job)
            request_conversation, omitted, compaction = compact_messages(conversation, profile["num_ctx"])
            with JOBS_LOCK:
                context_characters = sum(len(str(item.get("content", ""))) for item in request_conversation)
                job.setdefault("metrics", {}).update({"contextMessages": len(request_conversation), "contextCharacters": context_characters, "estimatedContextTokens": round(context_characters / 4), "contextUtilization": round(min(100, context_characters / max(1, profile["num_ctx"] * 4) * 100), 1), "contextLimit": profile["num_ctx"], "compactionCount": int(job.get("metrics", {}).get("compactionCount", 0)) + (1 if compaction.get("compacted") else 0)})
            if omitted > reported_omitted:
                add_job_event(job, "context", f"Kept the newest conversation turns and compacted {omitted} older message{'s' if omitted != 1 else ''} into a short memory handoff to keep Qwen responsive.", {"Profile": profile["label"], "Context limit": f"{profile['num_ctx']:,} tokens", "Older messages omitted": omitted, "Estimated context now": f"{job['metrics'].get('estimatedContextTokens', 0):,} tokens ({job['metrics'].get('contextUtilization', 0):.1f}%)"})
                reported_omitted = omitted
            add_job_event(job, "reasoning", "Sending the conversation and available tools to Qwen through Ollama. Waiting for Qwen to choose the next action.", {"Component": f"Ollama → {active_model}", "Agent step": step + 1, "Mode": f"{profile['label']} — thinking {'enabled' if think else 'disabled'}", "Context limit": f"{profile['num_ctx']:,} tokens"})
            update_job_activity(job, "model", "Ollama is loading the conversation into Qwen. This run has no automatic time limit.", agentStep=step + 1, unlimitedRun=True)
            payload = {"model": active_model, "messages": request_conversation, "tools": BUILT_IN_TOOLS + mcp_tools, "options": options, "think": think, "keep_alive": "30m"}
            message, result = stream_ollama_chat(payload, job)
            step += 1
            record_model_step(job, result, profile, step)
            if step % 3 == 0 or load_runtime_settings().get("mode") == "continuous":
                checkpoint_job(job, f"Qwen model step {step}", {"Agent step": step, "Artifacts": len(job.get("artifacts", []))})
                run_codex_supervisor(job, "milestone", workspace, str(message.get("content", ""))[-5000:])
            calls = message.get("tool_calls", [])
            if not calls:
                if not str(message.get("content", "")).strip():
                    if record_job_failure(job, "empty-response", "Qwen returned no visible content after a recovery prompt."):
                        raise BlockedJobError("empty response recovery exhausted")
                    add_job_event(job, "guardrail", "Qwen returned no visible answer. The app rejected the empty response and asked Qwen to summarize the work and verification evidence.", {"Requirement": "A useful visible final answer", "Next action": "Continue the agent loop and produce a concrete summary"})
                    conversation.append({"role": "user", "content": "Your previous turn had no visible answer. Continue now. Inspect the current project state if needed, then provide a concrete final response explaining what you did, which files changed, what tests ran, and any remaining issue. Do not return an empty response."})
                    continue
                if requires_artifacts and not job.get("artifacts"):
                    add_job_event(job, "guardrail", "Qwen tried to finish before creating any files. The app rejected that answer and told Qwen to continue the actual work.", {"Requirement": "Create at least one real file", "Current artifacts": 0, "Next action": "Use file or scaffolding tools, then verify the result"})
                    conversation.append(message)
                    conversation.append({"role": "user", "content": "You have not created any files yet. Continue the task now using tools. Write the requested artifacts to disk, inspect them, and verify the result before giving a final answer. An empty directory does not count as completion."})
                    continue
                verification = verification_snapshot(job, workspace)
                if not verification.get("artifactsOk"):
                    add_job_event(job, "guardrail", "The completion gate rejected Qwen's answer because a required artifact is missing. Qwen must continue from the current files.", {"Next action": "Create or restore the required artifact, then verify it exists."})
                    conversation.append(message)
                    conversation.append({"role": "user", "content": "The local completion gate found that the required artifact is still missing. Continue from the current project files, create or restore it, inspect it, and verify its existence before summarizing."})
                    continue
                with JOBS_LOCK:
                    job["status"] = "verifying"; job["message"] = message; job["finishedAt"] = None
                checkpoint_job(job, "Qwen completed its implementation turn", {"Artifacts": len(job.get("artifacts", [])), "Agent steps": step})
                review = run_codex_supervisor(job, "final verification", workspace, str(message.get("content", ""))[-7000:])
                with JOBS_LOCK:
                    job["supervisorReview"] = {"ok": review.get("ok"), "message": review.get("message", ""), "stage": "final verification"}
                    job["status"] = "complete" if review.get("ok", True) else "complete_with_warnings"; job["finishedAt"] = time.time()
                if incoming.get("threadId"):
                    append_thread_message(incoming["threadId"], "assistant", message.get("content", ""))
                add_job_event(job, "complete", "Qwen completed the requested work and produced the final answer.", {"Component": "Agent loop", "Result": "No further tool actions requested", "Files changed": len(job.get("artifacts", [])), "Total prompt tokens": f"{job['metrics'].get('totalPromptTokens', 0):,}", "Total generated tokens": f"{job['metrics'].get('totalGeneratedTokens', 0):,}", **performance_details(result)})
                update_job_activity(job, "complete", "Finished.")
                return
            conversation.append(message)
            repeated_tool = False
            for call in calls:
                wait_if_paused(job)
                wait_if_busy_processes(job)
                fn = call.get("function", {}); name = fn.get("name", ""); args = fn.get("arguments", {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except json.JSONDecodeError: args = {"raw": args}
                signature = hashlib.sha256(f"{name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode("utf-8")).hexdigest()[:16]
                with JOBS_LOCK:
                    signatures = job.setdefault("metrics", {}).setdefault("toolSignatures", {})
                    signatures[signature] = int(signatures.get(signature) or 0) + 1
                    repeat_count = signatures[signature]
                if repeat_count >= 3:
                    repeated_tool = True
                    add_job_event(job, "loop_warning", f"Qwen has requested the same {name} tool action {repeat_count} times. The harness will keep the current files and ask Qwen to choose a different verification step.", {"Tool": name, "Repeated count": repeat_count})
                    if repeat_count >= 5 and record_job_failure(job, "repeated-tool", f"Qwen repeated {name} with the same arguments {repeat_count} times."):
                        raise BlockedJobError("repeated tool recovery exhausted")
                explanation, detail = describe_tool(name, args)
                add_job_event(job, "tool", explanation, detail)
                update_job_activity(job, "tool", explanation)
                try:
                    approved, denial = wait_for_tool_approval(job, name, args, workspace)
                    if not approved:
                        if job.get("cancelRequested"): raise RuntimeError("Stopped by user.")
                        output, ok = denial or "The user did not approve this action.", False
                    else:
                        output = run_command_streamed(args.get("command", ""), workspace, job) if name == "run_command" else run_tool(name, args, mcp_mapping, workspace); ok = True
                    if job.get("cancelRequested"): raise RuntimeError("Stopped by user.")
                except Exception as error:
                    if job.get("cancelRequested"): raise
                    output, ok = f"Tool error: {error}", False
                    if record_job_failure(job, f"tool:{name}", str(error)):
                        raise BlockedJobError(f"tool failure recovery exhausted for {name}")
                    run_codex_supervisor(job, "failure diagnosis", workspace, f"Qwen tool {name} failed with: {output[-3000:]}")
                conversation.append({"role": "tool", "content": output})
                if ok and (name == "write_file" or (name == "run_command" and command_creates_artifacts(args.get("command", "")))):
                    artifact = args.get("path") if name == "write_file" else "Files created by a shell scaffolding command"
                    with JOBS_LOCK:
                        if artifact not in job["artifacts"]: job["artifacts"].append(artifact)
                        job.setdefault("metrics", {})["artifactsCreated"] = len(job["artifacts"])
                checkpoint_job(job, f"Tool action: {name}", {"Tool": name, "Success": ok, "Artifacts": len(job.get("artifacts", []))})
                result_text, result_detail = describe_tool_result(name, args, output, ok)
                add_job_event(job, "tool_complete" if ok else "tool_error", result_text, result_detail)
            if repeated_tool:
                conversation.append({"role": "user", "content": "The harness detected a repeated tool action. Do not repeat the same call again. Inspect the latest result, choose a different concrete next step, or explain the verified blocker."})
    except BlockedJobError:
        pass
    except (HTTPError, URLError) as error:
        message = f"Could not reach Ollama: {getattr(error, 'reason', error)}"
        blocked = record_job_failure(job, "ollama-disconnect", message)
        if not blocked and job.get("supervisorEnabled"):
            run_codex_supervisor(job, "Ollama disconnect diagnosis", locals().get("workspace", project_workspace()), message)
        with JOBS_LOCK:
            if not blocked: job["status"] = "error"; job["error"] = message; job["finishedAt"] = time.time()
        if not blocked: add_job_event(job, "error", message)
    except Exception as error:
        stopped = bool(job.get("cancelRequested"))
        if stopped:
            with JOBS_LOCK: job["status"] = "stopped"; job["error"] = "Stopped by user."; job["finishedAt"] = time.time()
            add_job_event(job, "stopped", job["error"])
        else:
            message = str(error)
            blocked = record_job_failure(job, "agent-error", message)
            if not blocked and job.get("supervisorEnabled"):
                run_codex_supervisor(job, "harness error diagnosis", locals().get("workspace", project_workspace()), message)
            with JOBS_LOCK:
                if not blocked: job["status"] = "error"; job["error"] = message; job["finishedAt"] = time.time()
            if not blocked: add_job_event(job, "error", message)
    finally:
        watchdog_stop.set()
        job.pop("_watchdog_stop", None)
        with JOBS_LOCK: job["_response"] = None
        persist_jobs()
        if AGENT_LOCK.locked():
            AGENT_LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def cors_origin(self):
        origin = self.headers.get("Origin", "")
        return origin if origin in ALLOWED_ORIGINS else None
    def send_cors_headers(self):
        origin = self.cors_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Qwen-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    def require_api_access(self, route):
        if not route.startswith("/api/") or not API_TOKEN: return True
        supplied = self.headers.get("X-Qwen-Token", "")
        if supplied and hmac.compare_digest(supplied, API_TOKEN): return True
        self.send_json(403, {"error": "This local API request was not authorized by Qwen Studio."})
        return False
    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Cache-Control", "no-store"); self.send_cors_headers(); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_OPTIONS(self):
        if self.headers.get("Origin") and not self.cors_origin(): self.send_response(403); self.end_headers(); return
        self.send_response(204); self.send_cors_headers(); self.end_headers()
    def send_file(self, path, content_type):
        data = Path(path).read_bytes(); self.send_response(200); self.send_header("Content-Type", content_type); self.send_cors_headers(); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "private, max-age=3600"); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        route = urlparse(self.path).path
        if not self.require_api_access(route): return
        ensure_jobs_loaded()
        if route == "/api/status":
            project = active_project()
            with JOBS_LOCK:
                running = sum(1 for job in JOBS.values() if job.get("status") == "running")
            self.send_json(200, {"model": MODEL, "workspace": str(project_workspace()), "project": project, "mcpCount": len(load_mcps()), "runningJobs": running, "runtime": ollama_model_info(), "profiles": PROFILES, "supervisor": supervisor_status()}); return
        if route == "/api/supervisor":
            self.send_json(200, supervisor_status()); return
        if route == "/api/jobs":
            with JOBS_LOCK:
                jobs = [job_payload(job) for job in JOBS.values()]
            self.send_json(200, {"items": sorted(jobs, key=lambda item: item.get("createdAt", 0), reverse=True)}); return
        if route == "/api/projects":
            state = load_project_state()
            for item in state["items"]: item["available"] = Path(item["path"]).is_dir()
            self.send_json(200, state); return
        if route == "/api/threads":
            state = load_thread_state(); project_id = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item).get("projectId")
            items = [item for item in state["items"] if not item.get("archived") and (not project_id or item.get("projectId") == project_id)]
            summaries = [{key: value for key, value in item.items() if key != "messages"} | {"messageCount": len(item.get("messages", []))} for item in items]
            summaries.sort(key=lambda item: (not item.get("pinned", False), -item.get("updatedAt", 0)))
            self.send_json(200, {"items": summaries}); return
        if route.startswith("/api/threads/"):
            thread_id = unquote(route.rsplit("/", 1)[-1]); thread = thread_by_id(thread_id)
            if not thread: self.send_json(404, {"error": "Chat not found."}); return
            self.send_json(200, thread); return
        if route == "/api/attachments":
            query = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item); thread_id = query.get("threadId")
            items = [public_attachment(item) for item in load_attachment_state()["items"] if not thread_id or item.get("threadId") == thread_id]
            self.send_json(200, {"items": items}); return
        if route.startswith("/api/attachments/") and route.endswith("/content"):
            attachment_id = unquote(route.split("/")[3]); attachment = attachment_by_id(attachment_id)
            if not attachment: self.send_json(404, {"error": "Attachment not found."}); return
            query = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item)
            if attachment.get("kind") == "video":
                frames = attachment.get("derivedFrames", []); index = min(max(int(query.get("frame", 0)), 0), max(len(frames) - 1, 0)); path = frames[index] if frames else None; content_type = "image/jpeg"
            else: path = attachment.get("storedPath"); content_type = attachment.get("mimeType", "application/octet-stream")
            if not path or not Path(path).is_file(): self.send_json(404, {"error": "Attachment content is missing."}); return
            self.send_file(path, content_type); return
        if route == "/api/project/files":
            workspace = project_workspace()
            files = []
            try:
                for path in sorted(workspace.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))[:100]:
                    files.append({"name": path.name, "type": "file" if path.is_file() else "folder", "size": path.stat().st_size if path.is_file() else None})
            except OSError: pass
            self.send_json(200, {"path": str(workspace), "files": files}); return
        if route == "/api/git":
            self.send_json(200, git_snapshot(project_workspace())); return
        if route == "/api/git/file":
            query = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item)
            try: self.send_json(200, project_file_review(project_workspace(), unquote(query.get("path", ""))))
            except PermissionError as error: self.send_json(403, {"error": str(error)})
            except FileNotFoundError as error: self.send_json(404, {"error": str(error)})
            return
        if route == "/api/git/diff":
            query = dict(item.split("=", 1) for item in urlparse(self.path).query.split("&") if "=" in item)
            try: self.send_json(200, git_diff_preview(project_workspace(), unquote(query.get("path", "")) or None))
            except PermissionError as error: self.send_json(403, {"error": str(error)})
            except RuntimeError as error: self.send_json(409, {"error": str(error)})
            return
        if route.startswith("/api/jobs/"):
            job_id = route.rsplit("/", 1)[-1]
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                payload = job_payload(job) if job else None
            if not payload: self.send_json(404, {"error": "Job not found."}); return
            self.send_json(200, payload); return
        if route.startswith("/api/terminal/"):
            run_id = route.rsplit("/", 1)[-1]
            with TERMINAL_LOCK:
                run = TERMINAL_RUNS.get(run_id)
                payload = terminal_payload(run) if run else None
            if not payload: self.send_json(404, {"error": "Terminal command not found."}); return
            self.send_json(200, payload); return
        if route.startswith("/api/mcps/") and route.endswith("/diagnostics"):
            identifier = unquote(route.split("/")[3]); config = next((item for item in load_mcps() if item["id"] == identifier), None)
            if not config: self.send_json(404, {"error": "Connection not found."}); return
            self.send_json(200, mcp_diagnostics(config)); return
        if route == "/api/mcps": self.send_json(200, {"connections": [public_mcp(item) for item in load_mcps()]}); return
        if route == "/api/mcp-library": self.send_json(200, {"items": MCP_LIBRARY}); return
        file_path = ROOT / ("index.html" if route == "/" else route.lstrip("/"))
        if not file_path.is_file() or ROOT not in file_path.resolve().parents: self.send_error(404); return
        content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(file_path.suffix, "application/octet-stream")
        data = file_path.read_bytes(); self.send_response(200); self.send_header("Content-Type", f"{content_type}; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        route = urlparse(self.path).path
        if not self.require_api_access(route): return
        try:
            ensure_jobs_loaded()
            if route.startswith("/api/jobs/") and route.endswith("/dismiss"):
                job_id = unquote(route.split("/")[3])
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    if job: job["dismissed"] = True; job["updatedAt"] = time.time()
                if not job: self.send_json(404, {"error": "Job not found."}); return
                persist_jobs(); self.send_json(200, {"dismissed": True}); return
            if route == "/api/supervisor":
                incoming = self.read_json(); settings = load_runtime_settings()
                for key in ("enabled", "mode", "sandbox", "maxRunsPerJob", "dailyBudgetUsd", "lowResource", "permissionProfile", "outputTokens", "processPriority", "supervisorCadence", "idleOnly", "busyProcesses"):
                    if key in incoming: settings[key] = incoming[key]
                self.send_json(200, {"supervisor": save_runtime_settings(settings)} | {"status": supervisor_status()}); return
            if route.startswith("/api/jobs/") and route.endswith("/approve"):
                job_id = unquote(route.split("/")[3]); incoming = self.read_json()
                decision = "approved" if incoming.get("approved") else "denied"
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    pending = job.get("pendingApproval") if job else None
                    if pending: pending["decision"] = decision
                if not job: self.send_json(404, {"error": "Job not found."}); return
                if not pending: self.send_json(409, {"error": "This job is not waiting for approval."}); return
                with APPROVAL_LOCK:
                    condition = APPROVAL_CONDITIONS.get(job_id)
                    if condition: condition.notify_all()
                add_job_event(job, "approval_response", f"Approval response recorded: {decision}.", {"Approval ID": pending.get("id")})
                self.send_json(200, {"job": job_payload(job)}); return
            if route.startswith("/api/jobs/") and route.endswith("/pause"):
                job_id = unquote(route.split("/")[3]); incoming = self.read_json()
                with JOBS_LOCK:
                    job = JOBS.get(job_id)
                    if job: job["pauseRequested"] = bool(incoming.get("paused", True)); job["updatedAt"] = time.time()
                if not job: self.send_json(404, {"error": "Job not found."}); return
                paused = bool(job.get("pauseRequested"))
                add_job_event(job, "pause_requested" if paused else "resume_requested", "Pause requested. Qwen will stop before its next action." if paused else "Resume requested. Qwen will continue before its next action.")
                with PAUSE_LOCK:
                    condition = PAUSE_CONDITIONS.get(job_id)
                    if condition: condition.notify_all()
                self.send_json(200, {"paused": paused}); return
            if route.startswith("/api/jobs/") and route.endswith("/resume"):
                job_id = unquote(route.split("/")[3])
                with JOBS_LOCK: job = JOBS.get(job_id); request = dict(job.get("_request") or {}) if job else None
                if not job: self.send_json(404, {"error": "Job not found."}); return
                if not request: self.send_json(409, {"error": "This job has no resumable request."}); return
                if job.get("status") == "running": self.send_json(409, {"error": "This job is already running."}); return
                if not AGENT_LOCK.acquire(blocking=False): self.send_json(409, {"error": "Another Qwen job is already running."}); return
                with JOBS_LOCK:
                    job.update({"status": "running", "phase": "queued", "activity": "Resuming from the latest checkpoint and current project files.", "error": None, "message": None, "cancelRequested": False, "pauseRequested": False, "finishedAt": None, "createdAt": time.time(), "updatedAt": time.time()})
                    job.setdefault("metrics", {})["resumeCount"] = int(job.get("metrics", {}).get("resumeCount", 0)) + 1
                add_job_event(job, "resumed", "Resumed this job from its saved checkpoint. Completed file actions were not replayed.", {"Checkpoint": job.get("checkpoint", {}).get("label", "Latest saved state")})
                threading.Thread(target=run_agent_job, args=(job_id, request), daemon=True).start()
                self.send_json(202, {"jobId": job_id}); return
            if route == "/api/projects/create":
                incoming = self.read_json(); parent = Path(incoming.get("parent", "").strip()); name = re.sub(r"\s+", " ", incoming.get("name", "")).strip()
                if not parent.is_dir(): self.send_json(400, {"error": "Choose an existing parent folder."}); return
                if not name or len(name) > 80 or name in (".", "..") or re.search(r'[<>:"/\\|?*]', name): self.send_json(400, {"error": "Use a project name without Windows path characters."}); return
                path = parent / name
                if path.exists(): self.send_json(409, {"error": "A file or folder with that project name already exists."}); return
                path.mkdir()
                state = load_project_state(); item = {"id": uuid.uuid4().hex[:12], "name": name, "path": str(path.resolve()), "permissionProfile": load_runtime_settings().get("permissionProfile", "project-write")}
                state["items"].append(item); state["active"] = item["id"]; save_project_state(state)
                self.send_json(201, {"project": item, "state": state}); return
            if route == "/api/projects":
                incoming = self.read_json(); raw_path = incoming.get("path", "").strip(); path = Path(raw_path)
                if not raw_path or not path.is_dir(): self.send_json(400, {"error": "Choose an existing folder."}); return
                state = load_project_state(); resolved = str(path.resolve())
                existing = next((item for item in state["items"] if item["path"].lower() == resolved.lower()), None)
                if existing: state["active"] = existing["id"]
                else:
                    item = {"id": uuid.uuid4().hex[:12], "name": incoming.get("name", "").strip() or path.name, "path": resolved, "permissionProfile": load_runtime_settings().get("permissionProfile", "project-write")}
                    state["items"].append(item); state["active"] = item["id"]
                save_project_state(state); self.send_json(201, state); return
            if route == "/api/threads":
                incoming = self.read_json(); project_id = incoming.get("projectId")
                if project_id and not any(item.get("id") == project_id for item in load_project_state()["items"]): self.send_json(400, {"error": "Project not found."}); return
                thread = create_thread(project_id, incoming.get("title", "New chat"), incoming.get("mode", "fast")); self.send_json(201, thread); return
            if route == "/api/attachments":
                incoming = self.read_json(); paths = incoming.get("paths", [])
                if not isinstance(paths, list) or not paths: self.send_json(400, {"error": "Choose at least one file."}); return
                if len(paths) > 10: self.send_json(400, {"error": "Attach no more than 10 files at once."}); return
                attachments, errors = [], []
                for path in paths:
                    try: attachments.append(public_attachment(ingest_attachment(path, incoming.get("threadId"))))
                    except Exception as error: errors.append({"path": str(path), "error": str(error)})
                self.send_json(201 if attachments else 400, {"items": attachments, "errors": errors}); return
            if route.startswith("/api/threads/") and route.endswith("/rename"):
                incoming = self.read_json(); thread_id = unquote(route.split("/")[3]); title = re.sub(r"\s+", " ", incoming.get("title", "")).strip()[:100]
                if not title: self.send_json(400, {"error": "Enter a chat name."}); return
                thread = update_thread(thread_id, lambda item: item.update({"title": title}))
                if not thread: self.send_json(404, {"error": "Chat not found."}); return
                self.send_json(200, thread); return
            if route.startswith("/api/threads/") and route.endswith("/archive"):
                thread_id = unquote(route.split("/")[3]); thread = update_thread(thread_id, lambda item: item.update({"archived": True}))
                if not thread: self.send_json(404, {"error": "Chat not found."}); return
                self.send_json(200, thread); return
            if route.startswith("/api/threads/") and route.endswith("/pin"):
                thread_id = unquote(route.split("/")[3]); incoming = self.read_json(); thread = update_thread(thread_id, lambda item: item.update({"pinned": bool(incoming.get("pinned"))}))
                if not thread: self.send_json(404, {"error": "Chat not found."}); return
                self.send_json(200, thread); return
            if route.startswith("/api/projects/") and route.endswith("/activate"):
                identifier = unquote(route.split("/")[3]); state = load_project_state()
                if not any(item["id"] == identifier for item in state["items"]): self.send_json(404, {"error": "Project not found."}); return
                state["active"] = identifier; save_project_state(state); self.send_json(200, state); return
            if route.startswith("/api/projects/") and route.endswith("/permissions"):
                identifier = unquote(route.split("/")[3]); incoming = self.read_json(); profile = incoming.get("permissionProfile")
                if profile not in ("read-only", "project-write", "full-access"): self.send_json(400, {"error": "Choose read-only, project-write, or full-access."}); return
                state = load_project_state(); project = next((item for item in state["items"] if item.get("id") == identifier), None)
                if not project: self.send_json(404, {"error": "Project not found."}); return
                project["permissionProfile"] = profile; save_project_state(state); self.send_json(200, project); return
            if route == "/api/mcps":
                incoming = self.read_json(); name = incoming.get("name", "").strip(); transport = incoming.get("transport", "stdio"); command = incoming.get("command", "").strip(); url = incoming.get("url", "").strip(); auth_mode = incoming.get("authMode", "none")
                if not name or transport not in ("stdio", "streamable-http") or (transport == "stdio" and not command) or (transport == "streamable-http" and not re.match(r"^https?://", url)): self.send_json(400, {"error": "Provide a name and valid stdio command or Streamable HTTP URL."}); return
                if auth_mode not in ("none", "bearer", "oauth"): self.send_json(400, {"error": "Choose no authentication, bearer headers, or OAuth-compatible headers."}); return
                configs = load_mcps(); base = mcp_id(name); identifier = base; index = 2
                while any(item["id"] == identifier for item in configs): identifier = f"{base}-{index}"; index += 1
                configs.append({"id": identifier, "name": name, "transport": transport, "authMode": auth_mode, "command": command, "args": incoming.get("args", []), "url": url, "headers": incoming.get("headers", {}), "env": incoming.get("env", {}), "enabled": True})
                save_mcps(configs); self.send_json(201, {"connections": [public_mcp(item) for item in configs]}); return
            if route.startswith("/api/mcps/") and route.endswith("/test"):
                identifier = unquote(route.split("/")[3]); config = next((item for item in load_mcps() if item["id"] == identifier), None)
                if not config: self.send_json(404, {"error": "Connection not found."}); return
                result = mcp_diagnostics(config); self.send_json(200 if result["ok"] else 502, result); return
            if route.startswith("/api/mcps/") and route.endswith("/diagnostics"):
                identifier = unquote(route.split("/")[3]); config = next((item for item in load_mcps() if item["id"] == identifier), None)
                if not config: self.send_json(404, {"error": "Connection not found."}); return
                self.send_json(200, mcp_diagnostics(config)); return
            if route.startswith("/api/mcps/") and route.endswith("/toggle"):
                identifier = unquote(route.split("/")[3]); incoming = self.read_json(); configs = load_mcps(); config = next((item for item in configs if item["id"] == identifier), None)
                if not config: self.send_json(404, {"error": "Connection not found."}); return
                config["enabled"] = bool(incoming.get("enabled")); save_mcps(configs); self.send_json(200, public_mcp(config)); return
            if route == "/api/terminal":
                incoming = self.read_json(); command = incoming.get("command", "").strip()
                if not command: self.send_json(400, {"error": "Enter a command first."}); return
                run_id = uuid.uuid4().hex; now = time.time(); workspace = project_workspace()
                run = {"id": run_id, "command": command, "workspace": str(workspace), "status": "running", "output": "", "error": None, "exitCode": None, "pid": None, "createdAt": now, "updatedAt": now, "finishedAt": None, "stopRequested": False, "process": None}
                with TERMINAL_LOCK: TERMINAL_RUNS[run_id] = run
                threading.Thread(target=run_terminal_command, args=(run_id, command, workspace), daemon=True).start()
                self.send_json(202, terminal_payload(run)); return
            if route != "/api/chat": self.send_error(404); return
            incoming = self.read_json()
            thread_id = incoming.get("threadId")
            thread = thread_by_id(thread_id) if thread_id else None
            if not thread:
                project = active_project(); thread = create_thread(project.get("id") if project else None, mode=incoming.get("mode", "fast")); thread_id = thread["id"]
            elif thread.get("projectId") and (active_project() or {}).get("id") != thread.get("projectId"):
                if not activate_project_id(thread.get("projectId")): self.send_json(400, {"error": "This chat's project is no longer linked."}); return
            user_text = incoming.get("message", "").strip()
            if not user_text and not incoming.get("messages"):
                self.send_json(400, {"error": "Add a message first."}); return
            if not AGENT_LOCK.acquire(blocking=False):
                self.send_json(409, {"error": "Qwen is already working on another request. Wait for it to finish before sending another."}); return
            try:
                if user_text:
                    attachment_ids = incoming.get("attachments", [])
                    invalid = [item for item in attachment_ids if not (attachment_by_id(item) or {}).get("threadId") == thread_id]
                    if invalid: raise ValueError("One or more attachments do not belong to this chat.")
                    thread, _ = append_thread_message(thread_id, "user", user_text, attachment_ids)
                incoming["threadId"] = thread_id
                incoming["messages"] = model_messages(thread.get("messages", [])) if user_text else incoming.get("messages", [])
                mode = incoming.get("mode", "fast") if incoming.get("mode") in PROFILES else "fast"
                incoming["mode"] = mode
                update_thread(thread_id, lambda item: item.update({"mode": mode}))
                job_id = uuid.uuid4().hex
                now = time.time()
                with JOBS_LOCK:
                    runtime_settings = load_runtime_settings()
                    project_profile = (active_project() or {}).get("permissionProfile") or runtime_settings.get("permissionProfile", "project-write")
                    JOBS[job_id] = {"id": job_id, "threadId": thread_id, "status": "running", "phase": "queued", "activity": "Starting the local agent.", "events": [], "message": None, "error": None, "createdAt": now, "updatedAt": now, "finishedAt": None, "metrics": {}, "artifacts": [], "requiresArtifacts": False, "cancelRequested": False, "pauseRequested": False, "supervisorEnabled": bool(incoming.get("supervisor", runtime_settings.get("enabled"))), "permissionProfile": incoming.get("permissionProfile") if incoming.get("permissionProfile") in ("read-only", "project-write", "full-access") else project_profile, "checkpoint": None, "_response": None, "_request": dict(incoming)}
                persist_jobs()
                threading.Thread(target=run_agent_job, args=(job_id, incoming), daemon=True).start()
            except Exception:
                AGENT_LOCK.release()
                raise
            self.send_json(202, {"jobId": job_id, "threadId": thread_id})
        except (HTTPError, URLError) as error: self.send_json(502, {"error": f"Could not reach Ollama: {getattr(error, 'reason', error)}"})
        except Exception as error: self.send_json(500, {"error": str(error)})
    def do_DELETE(self):
        route = urlparse(self.path).path
        if not self.require_api_access(route): return
        ensure_jobs_loaded()
        if route.startswith("/api/jobs/"):
            job_id = unquote(route.rsplit("/", 1)[-1])
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                response = job.get("_response") if job else None
                supervisor_pid = job.get("supervisorPid") if job else None
                if job: job["cancelRequested"] = True
            if not job: self.send_json(404, {"error": "Job not found."}); return
            if response:
                try: response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: response.close()
                except Exception: pass
            if supervisor_pid:
                try: stop_process_id(supervisor_pid)
                except Exception: pass
            with APPROVAL_LOCK:
                condition = APPROVAL_CONDITIONS.get(job_id)
                if condition: condition.notify_all()
            with PAUSE_LOCK:
                condition = PAUSE_CONDITIONS.get(job_id)
                if condition: condition.notify_all()
            persist_jobs()
            self.send_json(200, {"stopping": True}); return
        if route.startswith("/api/terminal/"):
            run_id = unquote(route.rsplit("/", 1)[-1])
            with TERMINAL_LOCK:
                run = TERMINAL_RUNS.get(run_id)
                process = run.get("process") if run else None
                if run: run["stopRequested"] = True
            if not run: self.send_json(404, {"error": "Terminal command not found."}); return
            if process and process.poll() is None:
                stop_process(process)
            self.send_json(200, {"stopping": True}); return
        if route.startswith("/api/projects/"):
            identifier = unquote(route.rsplit("/", 1)[-1]); state = load_project_state()
            state["items"] = [item for item in state["items"] if item["id"] != identifier]
            if state.get("active") == identifier: state["active"] = state["items"][0]["id"] if state["items"] else None
            save_project_state(state); self.send_json(200, state); return
        if route.startswith("/api/threads/"):
            identifier = unquote(route.rsplit("/", 1)[-1]); state = load_thread_state(); before = len(state["items"])
            state["items"] = [item for item in state["items"] if item.get("id") != identifier]
            if len(state["items"]) == before: self.send_json(404, {"error": "Chat not found."}); return
            save_thread_state(state); self.send_json(200, {"deleted": identifier}); return
        if route.startswith("/api/attachments/"):
            attachment_id = unquote(route.rsplit("/", 1)[-1]); attachment = attachment_by_id(attachment_id)
            if not attachment: self.send_json(404, {"error": "Attachment not found."}); return
            with ATTACHMENTS_LOCK:
                state = load_attachment_state(); state["items"] = [item for item in state["items"] if item.get("id") != attachment_id]; save_attachment_state(state)
            target = (ATTACHMENTS_DIR / attachment_id).resolve()
            if target.parent == ATTACHMENTS_DIR.resolve() and target.is_dir(): shutil.rmtree(target)
            self.send_json(200, {"deleted": True}); return
        if not route.startswith("/api/mcps/"): self.send_error(404); return
        identifier = unquote(route.rsplit("/", 1)[-1]); configs = [item for item in load_mcps() if item["id"] != identifier]; save_mcps(configs); self.send_json(200, {"connections": [public_mcp(item) for item in configs]})

if __name__ == "__main__":
    print(f"Qwen Local Agent: http://{HOST}:{PORT} | model: {MODEL}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
