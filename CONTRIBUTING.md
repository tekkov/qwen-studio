# Contributing to Qwen Studio 🤝

Thank you for helping improve the local Qwen agent. Whether you found a bug, wrote a test, improved a sentence, or made the interface feel more human: welcome aboard. 🚀

## Development

1. Install Python 3.11+, Node.js 20+, Ollama, and FFmpeg.
2. Run `ollama pull qwen3:8b` or set `QWEN_MODEL` to a compatible tool/vision model.
3. Run `npm install` and `npm start`.
4. Run `npm run check` before opening a pull request.

Keep changes focused, include tests for backend behavior, and never commit `.env`, tokens, copied attachments, or application data. Real-model tests are optional in CI but required when changing model payloads, tool calling, or multimodal behavior.

## Issue and PR etiquette

- Search existing issues before opening a duplicate.
- Use the bug and feature templates when they fit.
- Include screenshots or a short recording for UI changes.
- Keep secrets, personal files, and private model output out of screenshots.
- Prefer small, reviewable pull requests with a clear user-facing result.
- Emoji are encouraged when they add signal or joy; clarity still wins. ✨

## Pull requests

Describe the user-facing outcome, safety impact, tests run, and any remaining limitations. UI changes should include screenshots. Security issues should follow [SECURITY.md](SECURITY.md), not public issues.
