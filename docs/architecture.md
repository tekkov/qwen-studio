# Architecture

Qwen Studio is a small local desktop stack:

1. Electron owns the native window, file/folder pickers, and a fresh loopback port.
2. The Python HTTP server owns persistent state, the agent loop, terminal processes, attachments, and Ollama requests.
3. Ollama runs the selected Qwen model and streams content, thinking, tool calls, and performance counters.
4. The MCP bridge launches configured stdio servers and maps their tools into Ollama's function-calling format.

## Durable entities

- **Project:** a linked or newly created local folder and active workspace.
- **Thread:** a project-scoped persistent conversation with title, mode, timestamps, and ordered messages.
- **Job:** a persisted agent run with plain-language events, detailed tool evidence, metrics, checkpoints, resumable request state, stop/recovery state, supervisor findings, and artifacts.
- **Attachment:** a copied immutable input. Text is bounded to 120,000 characters; images are base64-encoded for Ollama; videos are sampled to at most eight 1280-pixel-wide JPEG frames.
- **Terminal run:** a PowerShell process, output buffer, PID, status, and stop state scoped to the active project.

Metadata is currently versioned JSON under `%APPDATA%\QwenLocalAgent`; attachments live below its `attachments` directory. Threads, attachments, and jobs use lock-protected atomic replacement. Interrupted jobs are restored as resumable checkpoints; completed tool actions are not replayed automatically.

## Agent loop

The server sends the system instructions, trimmed conversation, built-in tools, and connected MCP tools to `/api/chat`. Tool steps and model output are uncapped. Build requests cannot complete until a real artifact has been observed, and empty final answers are rejected. Tool results become direct run events with commands, process IDs, streamed PowerShell output, live response previews, and per-step token evidence.

Every turn includes a bounded top-level project manifest plus excerpts from key project files such as `AGENTS.md`, `README.md`, and `package.json`. Project-specific questions instruct Qwen to inspect authoritative files before answering. Messages sent during an active run stop the current model turn, enter a visible steering queue, and continue in order against the current on-disk project state.

Fast uses 32,768 tokens without thinking, Balanced uses 65,536 without thinking, and Deep uses 131,072 with thinking. Output generation and agent tool steps are uncapped, and model requests have no automatic time limit. A run continues until Qwen finishes, the user presses Stop, or the local runtime returns an actual error. Older messages are re-trimmed before every agent step when needed but remain in persistent chat history; system instructions are always retained.

## Supervised Autopilot

Autopilot is an optional Codex CLI layer around the local worker. The server can run `codex exec --json` at kickoff, milestones, failure diagnosis, stall escalation, and final verification. JSONL command, file, MCP, message, usage, and completion events are normalized into the same visible job timeline. Qwen stays responsible for the main implementation loop; Codex reviews the current on-disk state and may make narrowly scoped repairs according to the selected sandbox.

Codex credentials are never placed in model prompts or event details. When an `OPENAI_API_KEY` is available, the supervisor passes it only to the Codex child process and labels the effective mode as metered API usage. A local daily budget and per-job review limit prevent unbounded supervisor calls. If Codex fails, Qwen can finish with a visible warning rather than silently claiming a clean review.
