# Changelog

## 0.4.3 — Tauri desktop shell

- Migrated the desktop shell from Electron to Tauri v2 with a bundled Python backend, per-launch loopback port, and per-launch API token.
- Hardened the Tauri runtime with single-instance enforcement, hidden console launches, backend restart monitoring, and automatic local Ollama startup.
- Switched Fast mode to the lightweight `qwen2.5:1.5b` model while Balanced and Deep stay on `qwen3:8b`.
- Added observable implementation progress and evidence states to run status reporting.

## 0.4.2 — Startup readiness

- Added Ollama preflight and model warm-up at startup so the first request responds faster.

## 0.4.1 — Release hygiene

- Aligned CI with the supported Windows platform path for native checks and builds.

## 0.4.0 — Supervisor foundation

- Added optional Codex Autopilot supervision with JSONL activity, milestone reviews, failure diagnosis, stall escalation, and final verification.
- Added persisted jobs, checkpoints, restart recovery, resume controls, artifact gates, and project change evidence.
- Added visible supervisor policy, budget, authentication status, recovery banners, watchdog events, and repeated-tool warnings.
- Added 19 deterministic tests and a real read-only Codex CLI supervisor smoke test.

## 0.3.0 — Agent visibility and project organization

- Added direct run commands, process output, live drafts, token metrics, steering queues, and nested project chats.
