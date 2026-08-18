# Setup and troubleshooting

## Local setup

Install Python, Node.js, Ollama, and FFmpeg, then verify them with `python --version`, `node --version`, `ollama --version`, and `ffmpeg -version`. Pull the default model with `ollama pull qwen3.8:27b`, run `npm install`, and launch with `npm start`.

The desktop process chooses an unused local port on every launch. This prevents a new UI from accidentally connecting to an older packaged backend, which was the primary cause of repeated stale “Failed to fetch” states.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `QWEN_MODEL` | `qwen3.8:27b` | Ollama model name. Tool and vision capabilities are recommended. |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local Ollama API base URL. |
| `QWEN_DATA_DIR` | `%APPDATA%\QwenLocalAgent` | Persistent chats, projects, attachments, and MCP configuration. |
| `QWEN_PORT` | `8000` for manual server use | Backend loopback port. Desktop mode chooses a free port automatically. |
| `QWEN_PYTHON` | `py -3` on Windows, `python3` elsewhere | Optional absolute Python executable when the platform default is unavailable. |
| `CODEX_COMMAND` | `codex` | Optional Codex CLI executable used by the Autopilot supervisor. |
| `CODEX_ESTIMATED_RUN_COST_USD` | `0.25` | Conservative per-review budget estimate used by the local guardrail. |

For source development, place these values in a repository `.env`. A packaged app also reads `%APPDATA%\Qwen Studio\.env`. Existing process environment variables take precedence.

## Common failures

- **Local runtime offline:** start Ollama, then restart Qwen Studio. Confirm `ollama list` contains the configured model.
- **First response is slow:** a 27B Q4 model exceeds 8 GB VRAM and uses both CPU and GPU on this hardware. Keep Fast mode selected and leave the model warm. Qwen Studio does not automatically time out model work; use Stop if you intentionally want to end a run.
- **Video failed:** install FFmpeg and confirm both `ffmpeg` and `ffprobe` are on `PATH`.
- **MCP failed:** use Test in the MCP view. Confirm the command works in your native shell and required tokens are present in its environment JSON.
- **Build has old behavior:** rebuild with `npm run dist` and launch the new executable. The dynamic backend port prevents cross-version backend reuse.
- **Autopilot unavailable:** install the Codex CLI and run `codex login status`. If using the project `.env` credential, remember that API-key supervision is metered and uses the Settings budget.
