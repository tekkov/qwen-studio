# Architecture

Qwen Studio is a small local desktop stack:

1. Electron owns the native window, file/folder pickers, and a fresh loopback port.
2. The Python HTTP server owns persistent state, the agent loop, terminal processes, attachments, and Ollama requests.
3. Ollama runs the selected Qwen model and streams content, thinking, tool calls, and performance counters.
4. The MCP bridge launches configured stdio servers and maps their tools into Ollama's function-calling format.

## Durable entities

- **Project:** a linked or newly created local folder and active workspace.
- **Thread:** a project-scoped persistent conversation with title, mode, timestamps, and ordered messages.
- **Job:** an in-memory active agent run with plain-language events, detailed tool evidence, metrics, stop state, and artifacts.
- **Attachment:** a copied immutable input. Text is bounded to 120,000 characters; images are base64-encoded for Ollama; videos are sampled to at most eight 1280-pixel-wide JPEG frames.
- **Terminal run:** a PowerShell process, output buffer, PID, status, and stop state scoped to the active project.

Metadata is currently versioned JSON under `%APPDATA%\QwenLocalAgent`; attachments live below its `attachments` directory. Threads and attachments use lock-protected atomic replacement. Jobs remain memory-only and do not recover after a backend restart.

## Agent loop

The server sends the system instructions, trimmed conversation, built-in tools, and connected MCP tools to `/api/chat`. Qwen may request up to 12 tool steps. Build requests cannot complete until a real artifact has been observed. Tool results are returned to the model and translated into plain-language run events for the UI.

Fast uses 8,192 tokens without thinking, Balanced uses 16,384 without thinking, and Deep uses 32,768 with thinking. Output generation and agent tool steps are uncapped, and model requests have no automatic time limit. A run continues until Qwen finishes, the user presses Stop, or the local runtime returns an actual error. Older messages are re-trimmed before every agent step when needed but remain in persistent chat history; system instructions are always retained.
