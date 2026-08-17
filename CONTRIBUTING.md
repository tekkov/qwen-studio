# Contributing to Qwen Studio

Thank you for helping improve the local Qwen agent.

## Development

1. Install Python 3.11+, Node.js 20+, Ollama, and FFmpeg.
2. Run `ollama pull qwen3.8:27b` or set `QWEN_MODEL` to a compatible tool/vision model.
3. Run `npm install` and `npm start`.
4. Run `npm run check` before opening a pull request.

Keep changes focused, include tests for backend behavior, and never commit `.env`, tokens, copied attachments, or application data. Real-model tests are optional in CI but required when changing model payloads, tool calling, or multimodal behavior.

## Pull requests

Describe the user-facing outcome, safety impact, tests run, and any remaining limitations. UI changes should include screenshots. Security issues should follow [SECURITY.md](SECURITY.md), not public issues.
