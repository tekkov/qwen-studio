# Qwen Studio

Qwen Studio is a free, local-first desktop coding agent for Qwen models running through Ollama. It combines persistent project chats, real filesystem and PowerShell tools, image/video/file intake, MCP connections, a project terminal, and understandable live run activity in one Windows app.

No OpenAI key or hosted account is required. Your model requests stay between this app and your local Ollama service.

## What works

- Create projects or link existing folders; each project keeps its own chat history.
- Let Qwen list, read, and write files and run PowerShell inside the active project.
- Attach images, source/text files, and videos. Videos are sampled into bounded frames with FFmpeg for Qwen vision.
- Use Fast (8K), Balanced (16K), or Deep (32K thinking) profiles while displaying the model's native context separately.
- Follow live plain-language agent events, exact technical details, elapsed time, first-token activity, and final TPS metrics.
- Add local stdio MCP servers and inspect an integrated project terminal.
- Stop model runs and terminal processes.

The installed `qwen3.8:27b` is a 27.3B Q4 model with vision, tool use, thinking, and a 262,144-token native context window. Practical app profiles are intentionally smaller for responsiveness on consumer hardware.

## Quick start

Requirements: Windows 10/11, Python 3.11+, Node.js 20+, [Ollama](https://ollama.com/), and FFmpeg for video attachments.

```powershell
ollama pull qwen3.8:27b
npm install
npm start
```

The desktop app starts a private backend on a fresh loopback port and opens the UI. To use another compatible model, set `QWEN_MODEL` in your environment. The app does not require an API key.

Build a portable Windows executable with:

```powershell
npm run check
npm run dist
```

## Safety

The agent and integrated terminal run as your Windows user. They can modify files and execute commands. Use a dedicated project folder and review important changes. Third-party MCP servers are programs installed or launched on your computer; only connect ones you trust. A richer approval system is tracked as active roadmap work.

## Documentation

- [Setup and troubleshooting](docs/setup.md)
- [Architecture and storage](docs/architecture.md)
- [Testing and benchmarks](docs/testing.md)
- [Privacy and security](docs/privacy-security.md)
- [Product audit and roadmap](docs/product-audit.md)
- [Contributing](CONTRIBUTING.md)

## License

[MIT](LICENSE). Qwen and Ollama are separate projects with their own names, software, model, and license terms.
