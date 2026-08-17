# Qwen Studio 🧠⚡

> A local-first desktop AI coding studio for Qwen + Ollama — private by default, powerful on purpose.

[![CI](https://github.com/tekkov/qwen-studio/actions/workflows/ci.yml/badge.svg)](https://github.com/tekkov/qwen-studio/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/platform-Windows-0078D6.svg)](#requirements)
[![Powered by Ollama](https://img.shields.io/badge/powered%20by-Ollama-black.svg)](https://ollama.com/)

Qwen Studio turns a local Qwen model into a friendly, transparent coding partner. Chat normally, organize work into projects, inspect live tool activity, use a real terminal, connect MCP servers, and keep your files on your own machine. 🏠🔒

No hosted AI account is required for normal local work. No mystery cloud sync. No black-box “trust me” button. Just a desktop app, your model, your files, and useful receipts for what happened.

## ✨ What makes it fun

- 💬 **General chats + project chats** — brainstorm freely or give a conversation a dedicated folder.
- 🛠️ **Real computer tools** — read/write files, run PowerShell, inspect Git, and review changed files.
- 👀 **Receipts, not vibes** — live phases, commands, process IDs, output, approvals, checkpoints, and final status.
- 🧭 **Three response modes** — Fast, Balanced, and Deep profiles for different kinds of work.
- 📎 **Multimodal intake** — attach source files, text, images, and videos for Qwen to inspect.
- 🔌 **MCP-ready** — connect local stdio or Streamable HTTP MCP servers.
- 🖥️ **Integrated terminal** — a project-aware PowerShell terminal lives where the work happens.
- 🧯 **Recoverable by design** — pause, stop, resume, steer, and safely surface blocked work.
- 🤖 **Optional Autopilot** — Codex can review milestones and failures while Qwen remains the primary worker.

## 🎬 The vibe

Qwen Studio is built for the moment when you want an AI coding tool that feels like a studio, not a slot machine:

```text
You:   “Make the landing page feel less generic.”
Qwen:  “I’ll inspect the current layout first, then propose a direction.”
       ├─ reads the relevant files
       ├─ shows the command/tool activity
       ├─ makes the change in your workspace
       └─ reports what changed and what was verified
```

## 🚀 Quick start

### Requirements

- Windows 10/11
- Python 3.11+
- Node.js 20+
- [Ollama](https://ollama.com/)
- FFmpeg (needed for video attachments)

### Install and run

```powershell
git clone https://github.com/tekkov/qwen-studio.git
cd qwen-studio
npm install
ollama pull qwen3.8:27b
npm start
```

The app starts a private loopback backend and opens the desktop UI. To use another compatible model, set `QWEN_MODEL` in your environment or copy `.env.example` to `.env`.

### Verify the checkout

```powershell
npm run check
npm run audit:release
```

### Build a portable Windows app

```powershell
npm run dist
```

## 🗺️ How it fits together

```text
Electron shell
    │
    ├─ Qwen Studio UI (HTML/CSS/vanilla JS)
    │       ├─ General + project chat threads
    │       ├─ Attachments, terminal, MCPs, Git review
    │       └─ Live run status + recovery controls
    │
    └─ Local Python backend
            ├─ Ollama chat + tool loop
            ├─ Persistent local state
            ├─ PowerShell / filesystem tools
            └─ Optional Codex supervision
```

See [the architecture guide](docs/architecture.md) for storage, request flow, and safety boundaries.

## 🧪 Project status

This is an active open-source project. The core desktop flow is working, and the roadmap is intentionally practical:

- Better approval UX for external and destructive actions
- More platform support beyond Windows
- More model/provider adapters
- Polished onboarding and first-run diagnostics
- Community-contributed MCP templates and UI improvements

Ideas, bug reports, screenshots, and “this would be cool if…” discussions are very welcome. 🌱

## 🤝 Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md), then open an issue or pull request. Small improvements count: documentation, test coverage, accessibility fixes, clearer errors, and delightful UI details are all valuable.

Please include:

1. What user problem does this solve?
2. What changed and where?
3. What did you test?
4. Any safety, privacy, or compatibility tradeoffs?

## 🔐 Safety and privacy

Qwen Studio can read/write files and run PowerShell with the permissions of the Windows user who launched it. Only link folders you intend the model to access, inspect important commands, and treat third-party MCP servers as executable software.

Keep credentials in local environment variables or MCP configuration. Never commit `.env`, tokens, copied attachments, or application data. See [SECURITY.md](SECURITY.md) for the full policy.

## 📚 Docs

- [Setup and troubleshooting](docs/setup.md)
- [Architecture and storage](docs/architecture.md)
- [Testing and benchmarks](docs/testing.md)
- [Privacy and security](docs/privacy-security.md)
- [Product audit and roadmap](docs/product-audit.md)
- [Contributing](CONTRIBUTING.md)
- [Changelog](CHANGELOG.md)

## 📄 License

Qwen Studio is released under the [MIT License](LICENSE). Built with ❤️ for local-first software, curious builders, and people who like knowing what their tools are doing.
