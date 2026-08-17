import base64
import json
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent
HOST, PORT = "127.0.0.1", int(os.getenv("QWEN_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("QWEN_MODEL", "qwen3.8:27b")
DATA_DIR = Path(os.getenv("QWEN_DATA_DIR") or (Path(os.getenv("APPDATA", ROOT)) / "QwenLocalAgent"))
MCP_FILE = DATA_DIR / "mcp.json"
PROJECTS_FILE = DATA_DIR / "projects.json"
THREADS_FILE = DATA_DIR / "threads.json"
ATTACHMENTS_FILE = DATA_DIR / "attachments.json"
ATTACHMENTS_DIR = DATA_DIR / "attachments"
MCP_BRIDGE = ROOT / "mcp-bridge.mjs"
JOBS = {}
JOBS_LOCK = threading.Lock()
AGENT_LOCK = threading.Lock()
TERMINAL_RUNS = {}
TERMINAL_LOCK = threading.Lock()
THREADS_LOCK = threading.RLock()
ATTACHMENTS_LOCK = threading.RLock()
MODEL_INFO_CACHE = {"at": 0, "value": None}

PROFILES = {
    "fast": {"label": "Fast", "num_ctx": 8192, "temperature": 0.2, "think": False},
    "balanced": {"label": "Balanced", "num_ctx": 16384, "temperature": 0.18, "think": False},
    "deep": {"label": "Deep", "num_ctx": 32768, "temperature": 0.15, "think": True},
}

def ollama_model_info():
    now = time.time()
    if MODEL_INFO_CACHE["value"] is not None and now - MODEL_INFO_CACHE["at"] < 60:
        return MODEL_INFO_CACHE["value"]
    value = {"available": False, "capabilities": [], "nativeContext": None}
    try:
        request = Request(f"{OLLAMA_URL}/api/show", data=json.dumps({"model": MODEL}).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=3) as response: details = json.loads(response.read())
        model_info = details.get("model_info", {})
        context = next((number for key, number in model_info.items() if key.endswith(".context_length")), None)
        value = {"available": True, "capabilities": details.get("capabilities", []), "nativeContext": context, "parameterSize": details.get("details", {}).get("parameter_size"), "quantization": details.get("details", {}).get("quantization_level")}
    except Exception:
        pass
    MODEL_INFO_CACHE.update({"at": now, "value": value})
    return value

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".css", ".scss", ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log", ".sql", ".sh", ".ps1", ".bat", ".java", ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".rb", ".php", ".swift", ".kt"}

SYSTEM = """You are Qwen, a local coding agent running on Windows. Work as a careful, capable collaborator: inspect before changing, explain important decisions, use tools when useful, and verify your work. You have local filesystem and PowerShell tools, plus any connected MCP tools. Never claim a tool action succeeded unless its result confirms it.

Execution rules:
- When the user asks you to create, build, implement, change, or fix something, perform the work with tools. Do not merely describe steps or paste the intended artifact into chat.
- Put generated code and content into real files with write_file (or a scaffolding command that creates files). Creating an empty directory is only setup and never completes a build task.
- Keep tool calls focused. Do not spend a long generation writing source code into your chat response when that code belongs in a file.
- Before finishing an implementation task, inspect the created files and run a relevant verification command when possible. State exactly what was created and tested."""

BUILT_IN_TOOLS = [
    {"type": "function", "function": {"name": "list_files", "description": "List files and folders at a Windows path.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a text file at a Windows path.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "write_file", "description": "Create or replace a text file with exact content.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a PowerShell command as the current Windows user and return its output.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "get_terminal_output", "description": "Read the latest output and status from the app's integrated project terminal.", "parameters": {"type": "object", "properties": {}}}}
]

MCP_LIBRARY = [
    {"id": "filesystem", "name": "Filesystem", "description": "Give Qwen access to a chosen directory through an MCP server.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "C:\\path\\to\\workspace"]},
    {"id": "github", "name": "GitHub", "description": "Work with repositories, issues, and pull requests. Requires GitHub authentication.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
    {"id": "playwright", "name": "Playwright", "description": "Automate browser-based research and testing locally.", "command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
    {"id": "postgres", "name": "PostgreSQL", "description": "Connect Qwen to a PostgreSQL database using a server you configure.", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://user:password@localhost/database"]}
]

def load_mcps():
    try:
        return json.loads(MCP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

def save_mcps(mcps):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MCP_FILE.write_text(json.dumps(mcps, indent=2), encoding="utf-8")

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
            if attachment.get("kind") == "text" and attachment.get("extractedText"):
                message["content"] += f"\n\n[Attached file: {attachment['name']}]\n{attachment['extractedText']}"
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
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], capture_output=True, text=True, timeout=30)
    try: return max(0.0, float(result.stdout.strip()))
    except ValueError: return 0.0

def sample_video_frames(source, target_dir, maximum=8):
    duration = video_duration(source)
    interval = max(duration / maximum, 1.0) if duration else 2.0
    pattern = target_dir / "frame-%02d.jpg"
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(source), "-vf", f"fps=1/{interval:.3f},scale='min(1280,iw)':-2", "-frames:v", str(maximum), "-q:v", "3", str(pattern)], capture_output=True, text=True, timeout=180)
    if result.returncode: raise RuntimeError((result.stderr or "FFmpeg could not sample this video.")[-1000:])
    return [str(path) for path in sorted(target_dir.glob("frame-*.jpg"))], duration

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
        kind = "image" if extension in IMAGE_EXTENSIONS else "video" if extension in VIDEO_EXTENSIONS else "text" if extension in TEXT_EXTENSIONS else "file"
        attachment = {"id": identifier, "threadId": thread_id, "name": source.name, "kind": kind, "mimeType": mime, "size": size, "createdAt": time.time(), "storedPath": str(target), "derivedFrames": [], "extractedText": "", "status": "ready"}
        if kind == "text":
            attachment["extractedText"] = target.read_text(encoding="utf-8", errors="replace")[:120000]
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

def project_workspace():
    project = active_project()
    if project and Path(project["path"]).is_dir(): return Path(project["path"])
    return ROOT

def resolve_workspace_path(value, workspace):
    path = Path(value)
    return path if path.is_absolute() else workspace / path

def mcp_id(name):
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "mcp"

def bridge(payload, timeout=45):
    result = subprocess.run(["node", str(MCP_BRIDGE)], input=json.dumps(payload), text=True, capture_output=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "MCP bridge failed").strip()[-1000:])
    return json.loads(result.stdout)

def connected_mcp_tools():
    tools, mapping = [], {}
    for config in load_mcps():
        if not config.get("enabled") or config.get("transport") != "stdio":
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
        result = subprocess.run(["powershell", "-NoProfile", "-Command", arguments.get("command", "")], cwd=workspace, capture_output=True, text=True, timeout=900)
        return f"exit_code={result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"[-12000:]
    if name == "get_terminal_output":
        with TERMINAL_LOCK:
            latest = max(TERMINAL_RUNS.values(), key=lambda item: item.get("createdAt", 0), default=None)
            return json.dumps(terminal_payload(latest), ensure_ascii=False)[-12000:] if latest else "No terminal commands have been run yet."
    return f"Unknown tool: {name}"

def add_job_event(job, kind, text, detail=None):
    with JOBS_LOCK:
        now = time.time()
        job["updatedAt"] = now
        job["events"].append({"at": round(now), "kind": kind, "text": text, "detail": detail})

def job_payload(job):
    return {key: value for key, value in job.items() if not key.startswith("_")}

def task_needs_artifacts(messages):
    latest = next((str(item.get("content", "")) for item in reversed(messages) if item.get("role") == "user"), "")
    return bool(re.search(r"(?i)\b(build|create|make|implement|code|develop|scaffold|set up|setup|write|design|fix|update|change)\b", latest))

def command_creates_artifacts(command):
    return bool(re.search(r"(?i)(set-content|out-file|add-content|npm\s+create|npx\s+create-|create-vite|create-next-app|new-item\s+[^\r\n]*-itemtype\s+file|(?:^|\s)>\s*[^&])", command or ""))

def update_job_activity(job, phase, text, **metrics):
    with JOBS_LOCK:
        job["phase"] = phase
        job["activity"] = text
        job["updatedAt"] = time.time()
        if metrics:
            job.setdefault("metrics", {}).update(metrics)

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
            stage = "Qwen is writing its response." if message["content"] else "Qwen is analyzing the request and deciding what to do."
            update_job_activity(job, "generating", stage, streamChunks=chunks, generatedCharacters=len(message["content"]), thinkingCharacters=len(message["thinking"]), elapsedSeconds=round(time.time() - started, 1), lastChunkAt=time.time())
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

def run_terminal_command(run_id, command, workspace):
    run = TERMINAL_RUNS[run_id]
    try:
        process = subprocess.Popen(
            ["powershell", "-NoLogo", "-NoProfile", "-Command", command],
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        with TERMINAL_LOCK:
            run["process"] = process
            run["pid"] = process.pid
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
        else: explanation = "Running a PowerShell command needed for the current task."
        return explanation, {"Component": "PowerShell", "Action": "Run command", "Command": command}
    if name == "get_terminal_output":
        return "Checking the integrated terminal to see what the latest command is doing.", {"Component": "Integrated terminal", "Action": "Read latest output"}
    return f"Using the {name} tool.", {"Component": "Agent tool", "Tool": name, "Input": redact_text(json.dumps(arguments, ensure_ascii=False))[:1200]}

def describe_tool_result(name, arguments, output, ok):
    if not ok:
        return "That action failed, so Qwen will receive the error and can choose a different approach.", {"Result": "Failed", "Error": redact_text(output)[:1200]}
    if name == "write_file":
        return f"Saved {arguments.get('path', 'the file')} successfully.", {"Result": "Success", "Change made": "File written to disk"}
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
        return f"PowerShell finished with exit code {exit_code}. Qwen can now inspect the result and choose the next action.", detail
    if name == "get_terminal_output":
        return "The latest integrated terminal output was returned to Qwen.", {"Result": "Success", "Output preview": redact_text(output)[:1200]}
    return "The tool finished and returned its result to Qwen.", {"Result": "Success", "Output preview": redact_text(output)[:1200]}

def run_agent_job(job_id, incoming):
    job = JOBS[job_id]
    try:
        messages = incoming.get("messages", [])
        mode = incoming.get("mode", "fast")
        if not messages: raise ValueError("Add a message first.")
        requires_artifacts = task_needs_artifacts(messages)
        with JOBS_LOCK: job["requiresArtifacts"] = requires_artifacts
        add_job_event(job, "started", "The desktop app accepted your request and created a background agent job.", {"Component": "Qwen Studio", "Action": "Create job", "Job ID": job_id[:12]})
        update_job_activity(job, "setup", "Preparing the project and tools.")
        workspace = project_workspace()
        project = active_project()
        add_job_event(job, "setup", "Opening the active project and checking which computer tools and MCP connections Qwen can use.", {"Project": project["name"] if project else "Qwen Studio folder", "Working folder": str(workspace), "Built-in tools": "Read files, write files, list folders, PowerShell", "MCP connections": len(load_mcps())})
        mcp_tools, mcp_mapping = connected_mcp_tools()
        if mcp_tools: add_job_event(job, "mcp", f"Loaded {len(mcp_tools)} MCP tool{'s' if len(mcp_tools) != 1 else ''}.")
        workspace_prompt = f"\n\nThe active project folder is: {workspace}. Resolve relative file paths and PowerShell work inside this folder."
        conversation = [{"role": "system", "content": SYSTEM + workspace_prompt}] + messages
        profile = PROFILES.get(mode, PROFILES["fast"])
        options = {"temperature": profile["temperature"], "num_ctx": profile["num_ctx"], "num_predict": -1}
        think = profile["think"]
        reported_omitted = 0
        step = 0
        while True:
            request_conversation, omitted = trim_messages(conversation, profile["num_ctx"])
            if omitted > reported_omitted:
                add_job_event(job, "context", f"Kept the newest conversation turns and omitted {omitted} older message{'s' if omitted != 1 else ''} to keep Qwen responsive.", {"Profile": profile["label"], "Context limit": f"{profile['num_ctx']:,} tokens", "Older messages omitted": omitted})
                reported_omitted = omitted
            add_job_event(job, "reasoning", "Sending the conversation and available tools to Qwen through Ollama. Waiting for Qwen to choose the next action.", {"Component": f"Ollama → {MODEL}", "Agent step": step + 1, "Mode": f"{profile['label']} — thinking {'enabled' if think else 'disabled'}", "Context limit": f"{profile['num_ctx']:,} tokens"})
            update_job_activity(job, "model", "Ollama is loading the conversation into Qwen. This run has no automatic time limit.", agentStep=step + 1, unlimitedRun=True)
            payload = {"model": MODEL, "messages": request_conversation, "tools": BUILT_IN_TOOLS + mcp_tools, "options": options, "think": think, "keep_alive": "30m"}
            message, result = stream_ollama_chat(payload, job)
            step += 1
            calls = message.get("tool_calls", [])
            if not calls:
                if requires_artifacts and not job.get("artifacts"):
                    add_job_event(job, "guardrail", "Qwen tried to finish before creating any files. The app rejected that answer and told Qwen to continue the actual work.", {"Requirement": "Create at least one real file", "Current artifacts": 0, "Next action": "Use file or scaffolding tools, then verify the result"})
                    conversation.append(message)
                    conversation.append({"role": "user", "content": "You have not created any files yet. Continue the task now using tools. Write the requested artifacts to disk, inspect them, and verify the result before giving a final answer. An empty directory does not count as completion."})
                    continue
                with JOBS_LOCK:
                    job["status"] = "complete"; job["message"] = message; job["finishedAt"] = time.time()
                if incoming.get("threadId"):
                    append_thread_message(incoming["threadId"], "assistant", message.get("content", ""))
                add_job_event(job, "complete", "Qwen finished generating the answer.", {"Component": "Agent loop", "Result": "No more tool calls requested", **performance_details(result)})
                update_job_activity(job, "complete", "Finished.")
                return
            conversation.append(message)
            for call in calls:
                fn = call.get("function", {}); name = fn.get("name", ""); args = fn.get("arguments", {})
                if isinstance(args, str):
                    try: args = json.loads(args)
                    except json.JSONDecodeError: args = {"raw": args}
                explanation, detail = describe_tool(name, args)
                add_job_event(job, "tool", explanation, detail)
                update_job_activity(job, "tool", explanation)
                try:
                    output = run_tool(name, args, mcp_mapping, workspace); ok = True
                except Exception as error:
                    output, ok = f"Tool error: {error}", False
                conversation.append({"role": "tool", "content": output})
                if ok and (name == "write_file" or (name == "run_command" and command_creates_artifacts(args.get("command", "")))):
                    artifact = args.get("path") if name == "write_file" else "Files created by PowerShell scaffolding command"
                    with JOBS_LOCK:
                        if artifact not in job["artifacts"]: job["artifacts"].append(artifact)
                        job["metrics"]["artifactsCreated"] = len(job["artifacts"])
                result_text, result_detail = describe_tool_result(name, args, output, ok)
                add_job_event(job, "tool_complete" if ok else "tool_error", result_text, result_detail)
    except (HTTPError, URLError) as error:
        with JOBS_LOCK: job["status"] = "error"; job["error"] = f"Could not reach Ollama: {getattr(error, 'reason', error)}"; job["finishedAt"] = time.time()
        add_job_event(job, "error", job["error"])
    except Exception as error:
        stopped = bool(job.get("cancelRequested"))
        with JOBS_LOCK:
            job["status"] = "stopped" if stopped else "error"; job["error"] = "Stopped by user." if stopped else str(error); job["finishedAt"] = time.time()
        add_job_event(job, "stopped" if stopped else "error", job["error"])
    finally:
        with JOBS_LOCK: job["_response"] = None
        if AGENT_LOCK.locked():
            AGENT_LOCK.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def send_file(self, path, content_type):
        data = Path(path).read_bytes(); self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(data))); self.send_header("Cache-Control", "private, max-age=3600"); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        route = urlparse(self.path).path
        if route == "/api/status":
            project = active_project()
            with JOBS_LOCK:
                running = sum(1 for job in JOBS.values() if job.get("status") == "running")
            self.send_json(200, {"model": MODEL, "workspace": str(project_workspace()), "project": project, "mcpCount": len(load_mcps()), "runningJobs": running, "runtime": ollama_model_info(), "profiles": PROFILES}); return
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
        if route == "/api/mcps": self.send_json(200, {"connections": load_mcps()}); return
        if route == "/api/mcp-library": self.send_json(200, {"items": MCP_LIBRARY}); return
        file_path = ROOT / ("index.html" if route == "/" else route.lstrip("/"))
        if not file_path.is_file() or ROOT not in file_path.resolve().parents: self.send_error(404); return
        content_type = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}.get(file_path.suffix, "application/octet-stream")
        data = file_path.read_bytes(); self.send_response(200); self.send_header("Content-Type", f"{content_type}; charset=utf-8"); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        route = urlparse(self.path).path
        try:
            if route == "/api/projects/create":
                incoming = self.read_json(); parent = Path(incoming.get("parent", "").strip()); name = re.sub(r"\s+", " ", incoming.get("name", "")).strip()
                if not parent.is_dir(): self.send_json(400, {"error": "Choose an existing parent folder."}); return
                if not name or len(name) > 80 or name in (".", "..") or re.search(r'[<>:"/\\|?*]', name): self.send_json(400, {"error": "Use a project name without Windows path characters."}); return
                path = parent / name
                if path.exists(): self.send_json(409, {"error": "A file or folder with that project name already exists."}); return
                path.mkdir()
                state = load_project_state(); item = {"id": uuid.uuid4().hex[:12], "name": name, "path": str(path.resolve())}
                state["items"].append(item); state["active"] = item["id"]; save_project_state(state)
                self.send_json(201, {"project": item, "state": state}); return
            if route == "/api/projects":
                incoming = self.read_json(); raw_path = incoming.get("path", "").strip(); path = Path(raw_path)
                if not raw_path or not path.is_dir(): self.send_json(400, {"error": "Choose an existing folder."}); return
                state = load_project_state(); resolved = str(path.resolve())
                existing = next((item for item in state["items"] if item["path"].lower() == resolved.lower()), None)
                if existing: state["active"] = existing["id"]
                else:
                    item = {"id": uuid.uuid4().hex[:12], "name": incoming.get("name", "").strip() or path.name, "path": resolved}
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
            if route.startswith("/api/projects/") and route.endswith("/activate"):
                identifier = unquote(route.split("/")[3]); state = load_project_state()
                if not any(item["id"] == identifier for item in state["items"]): self.send_json(404, {"error": "Project not found."}); return
                state["active"] = identifier; save_project_state(state); self.send_json(200, state); return
            if route == "/api/mcps":
                incoming = self.read_json(); name = incoming.get("name", "").strip(); command = incoming.get("command", "").strip()
                if not name or not command: self.send_json(400, {"error": "Name and command are required."}); return
                configs = load_mcps(); base = mcp_id(name); identifier = base; index = 2
                while any(item["id"] == identifier for item in configs): identifier = f"{base}-{index}"; index += 1
                configs.append({"id": identifier, "name": name, "transport": "stdio", "command": command, "args": incoming.get("args", []), "env": incoming.get("env", {}), "enabled": True})
                save_mcps(configs); self.send_json(201, {"connections": configs}); return
            if route.startswith("/api/mcps/") and route.endswith("/test"):
                identifier = unquote(route.split("/")[3]); config = next((item for item in load_mcps() if item["id"] == identifier), None)
                if not config: self.send_json(404, {"error": "Connection not found."}); return
                result = bridge({"action": "list", "config": config}); self.send_json(200, {"tools": result.get("tools", [])}); return
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
                    JOBS[job_id] = {"id": job_id, "status": "running", "phase": "queued", "activity": "Starting the local agent.", "events": [], "message": None, "error": None, "createdAt": now, "updatedAt": now, "finishedAt": None, "metrics": {}, "artifacts": [], "requiresArtifacts": False, "cancelRequested": False, "_response": None}
                threading.Thread(target=run_agent_job, args=(job_id, incoming), daemon=True).start()
            except Exception:
                AGENT_LOCK.release()
                raise
            self.send_json(202, {"jobId": job_id, "threadId": thread_id})
        except (HTTPError, URLError) as error: self.send_json(502, {"error": f"Could not reach Ollama: {getattr(error, 'reason', error)}"})
        except Exception as error: self.send_json(500, {"error": str(error)})
    def do_DELETE(self):
        route = urlparse(self.path).path
        if route.startswith("/api/jobs/"):
            job_id = unquote(route.rsplit("/", 1)[-1])
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                response = job.get("_response") if job else None
                if job: job["cancelRequested"] = True
            if not job: self.send_json(404, {"error": "Job not found."}); return
            if response:
                try: response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
                except Exception: pass
                try: response.close()
                except Exception: pass
            self.send_json(200, {"stopping": True}); return
        if route.startswith("/api/terminal/"):
            run_id = unquote(route.rsplit("/", 1)[-1])
            with TERMINAL_LOCK:
                run = TERMINAL_RUNS.get(run_id)
                process = run.get("process") if run else None
                if run: run["stopRequested"] = True
            if not run: self.send_json(404, {"error": "Terminal command not found."}); return
            if process and process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
            self.send_json(200, {"stopping": True}); return
        if route.startswith("/api/projects/"):
            identifier = unquote(route.rsplit("/", 1)[-1]); state = load_project_state()
            state["items"] = [item for item in state["items"] if item["id"] != identifier]
            if state.get("active") == identifier: state["active"] = state["items"][0]["id"] if state["items"] else None
            save_project_state(state); self.send_json(200, state); return
        if route.startswith("/api/threads/"):
            thread_id = unquote(route.rsplit("/", 1)[-1])
            with THREADS_LOCK:
                state = load_thread_state(); before = len(state["items"]); state["items"] = [item for item in state["items"] if item.get("id") != thread_id]
                if len(state["items"]) == before: self.send_json(404, {"error": "Chat not found."}); return
                save_thread_state(state)
            self.send_json(200, {"deleted": True}); return
        if route.startswith("/api/attachments/"):
            attachment_id = unquote(route.rsplit("/", 1)[-1]); attachment = attachment_by_id(attachment_id)
            if not attachment: self.send_json(404, {"error": "Attachment not found."}); return
            with ATTACHMENTS_LOCK:
                state = load_attachment_state(); state["items"] = [item for item in state["items"] if item.get("id") != attachment_id]; save_attachment_state(state)
            target = (ATTACHMENTS_DIR / attachment_id).resolve()
            if target.parent == ATTACHMENTS_DIR.resolve() and target.is_dir(): shutil.rmtree(target)
            self.send_json(200, {"deleted": True}); return
        if not route.startswith("/api/mcps/"): self.send_error(404); return
        identifier = unquote(route.rsplit("/", 1)[-1]); configs = [item for item in load_mcps() if item["id"] != identifier]; save_mcps(configs); self.send_json(200, {"connections": configs})

if __name__ == "__main__":
    print(f"Qwen Local Agent: http://{HOST}:{PORT} | model: {MODEL}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
