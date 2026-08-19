# Setup and troubleshooting

## Local setup

Install Python, Node.js, Ollama, and FFmpeg, then verify them with `python --version`, `node --version`, `ollama --version`, and `ffmpeg -version`. Pull the default model with `ollama pull qwen3:8b`, run `npm install`, and launch with `npm start`.

The desktop process chooses an unused local port on every launch and protects it with a random per-launch token. It starts Python and local Ollama in the background without opening terminal windows. This prevents a new UI from accidentally connecting to an older packaged backend, which was the primary cause of repeated stale “Failed to fetch” states.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `QWEN_MODEL` | `qwen3:8b` | Ollama model for Balanced and Deep modes. The model picker in Settings overrides this default and persists across restarts. |
| `QWEN_FAST_MODEL` | `qwen2.5:1.5b` | Lightweight Ollama model used by Fast mode. The model picker in Settings overrides this default. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local Ollama API base URL. |
| `OLLAMA_COMMAND` | platform Ollama executable | Optional Ollama executable override. Automatic startup is disabled for non-loopback `OLLAMA_URL` values. |
| `QWEN_DATA_DIR` | `%APPDATA%\QwenLocalAgent` | Persistent chats, projects, attachments, and MCP configuration. |
| `QWEN_PORT` | `8000` for manual server use | Backend loopback port. Desktop mode chooses a free port automatically. |
| `QWEN_PYTHON` | auto-detected (`py`/`python`/`python3`) | Optional absolute Python executable when the platform default is unavailable. |
| `CODEX_COMMAND` | `codex` | Optional Codex CLI executable used by the Autopilot supervisor. |
| `CODEX_ESTIMATED_RUN_COST_USD` | `0.25` | Conservative per-review budget estimate used by the local guardrail. |

For source development, place these values in a repository `.env`. A packaged app also reads `.env` from Tauri's platform app-data directory for the `local.qwen.studio` identifier. Existing process environment variables take precedence.

## Common failures

- **Local runtime offline:** wait briefly while Qwen Studio starts local Ollama. If it remains offline, start Ollama manually and confirm `ollama list` contains the configured model.
- **Model not installed:** open Settings and pick one of the installed models, or run `ollama pull <model>` for the model shown in Settings. Sending stays disabled until the selected model is available.
- **Python backend will not start:** open Tauri's platform app-data folder for `local.qwen.studio` and inspect `qwen-backend.log`. Set `QWEN_PYTHON` to a working Python executable if auto-detection fails.
- **First response is slow:** the first request may load the selected model into memory. Fast mode uses the lightweight `qwen2.5:1.5b`; Balanced and Deep use `qwen3:8b`.
- **Video failed:** install FFmpeg and confirm both `ffmpeg` and `ffprobe` are on `PATH`.
- **MCP failed:** use Test in the MCP view. Confirm the command works in your native shell and required tokens are present in its environment JSON.
- **Build has old behavior:** rebuild with `npm run dist` and launch the new executable. The dynamic backend port prevents cross-version backend reuse.
- **Autopilot unavailable:** install the Codex CLI and run `codex login status`. If using the project `.env` credential, remember that API-key supervision is metered and uses the Settings budget.
