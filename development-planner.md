# Formatting practices (keep consistent)
- Use H1 for top-level sections, H2 for subgroups, H3 for task headers.
- Keep bullets concise; prefer past-tense summaries in Completed, imperative in Current.
- Include file paths in `backticks`; avoid line breaks inside bullets unless needed.
- When priorities are empty, note `None` under Current priorities.
- Add new sessions at the top of Completed with date-stamped headers.

# Current priorities

## P0 (current)
- None

## P1 (phase 2)
- None

## P2 (future)

### P2-01 — Browser, computer, and remote execution
- Add explicitly permissioned browser testing, screenshot feedback, and remote executor architecture.
- Keep local-only operation as the default and document every optional dependency.
- Verify browser unavailable, browser available, permission denied, and remote disconnect states.

# Completed Action Items

## Session 2026-08-18 (release documentation and gate parity)
- Added in-app model switching: a Settings picker lists installed Ollama models, persists Balanced/Deep and Fast selections, overrides the `QWEN_MODEL`/`QWEN_FAST_MODEL` defaults, and validates names through new `/api/models` endpoints in `server.py`, `app.js`, and `index.html`.
- Added missing `CHANGELOG.md` entries for 0.4.1, 0.4.2, and 0.4.3 from the tagged Git history, and made `scripts/release_audit.py` fail when the current package version has no changelog entry.
- Added `mcp-bridge.mjs` and the release scripts to the `npm run check` syntax gates, the missing `repository` field to `package.json`, `OLLAMA_COMMAND` to `.env.example`, and refreshed the stale remediation status in `docs/product-audit.md`.
- Verified `npm run check` with 34 tests, `npm run audit:release`, `npm run check:native`, live backend boot with token enforcement, and MCP client import resolution.

## Session 2026-08-17 (full acceptance audit and release pass)
- Completed semantic context compaction that preserves system instructions and recent tool facts, with queue wait, context utilization, output-token controls, and unlimited local model output in `server.py`, `app.js`, and `run-status.css`.
- Completed transparent recovery states with repeated-failure counters, safe blocked escalation, checkpoint persistence, Codex diagnosis hooks, idle-only continuation, configured process detection, and resumable disk-state recovery in `server.py`.
- Completed visible changed-file review buttons, blocked-state copy, inline notices, safe dynamic DOM rendering, markdown/code copy controls, keyboard-friendly controls, reduced-motion handling, and responsive layout coverage in `app.js`, `index.html`, and CSS files.
- Completed MCP diagnostics, bearer/OAuth-compatible header metadata, enable/disable controls, stdio/Streamable HTTP support, project workflow discovery, and secret-redacted connection responses in `server.py`, `mcp-bridge.mjs`, and `app.js`.
- Completed reviewable permissions, project defaults, Git branch/status/diff/file/worktree review, test-result recording, terminal process visibility, and no-automatic-destructive-Git behavior in `server.py` and `app.js`.
- Completed release hardening with `scripts/release_audit.py`, issue templates, changelog, documentation link checks, secret-pattern scanning, package parity verification, and release guidance in `README.md` and `docs/`.
- Verified `npm run check` with 31 tests, `npm run audit:release`, planner lint, JavaScript/Python syntax checks, the real `qwen3.8:27b` tool smoke with 20 events and a verified file, and Codex supervisor smoke from the installed authenticated CLI.
- Verified desktop and narrow browser states: no horizontal overflow at a 390px viewport, 58 focusable controls, reduced-motion rules present, and no browser console warnings or errors.
- Rebuilt `dist/Qwen Studio 0.4.0.exe`; hashes for packaged `server.py`, `app.js`, `index.html`, `run-status.css`, and `mcp-bridge.mjs` match the source tree. The obsolete `0.3.0` executable remains removed.

## Session 2026-08-17 (Codex supervisor foundation)
- Completed persistent project-scoped chat organization with switching, pin/archive/rename/delete actions, resumable run summaries, and packaged-source parity.
- Completed multimodal intake for images, videos, DOCX, PDF detection, size limits, and unsupported-format guidance.
- Added safe Codex CLI authentication status, `.env` API-key availability detection, redacted supervisor metadata, review budgets, and opt-in supervision.
- Added persisted job checkpoints, resumable requests, interrupted-job recovery, direct run evidence, artifact/change verification, Autopilot controls, Codex JSONL milestone/failure/final review events, and a non-destructive watchdog.
- Added read-only Git review, project-write/read-only/full-access profiles, live approval cards, Streamable HTTP MCP configuration, secret-redacted connection cards, low-resource mode, project file review, inline notices, durable per-project permissions, safe pause/resume, MCP enable/disable, Git diff/worktree review, and unlimited output-token settings.
- Verified the foundation with 26 isolated tests, JavaScript syntax/export checks, and a real read-only Codex supervisor smoke test without exposing credentials.

## Session 2026-08-17 (agent visibility, steering, and project organization)
- Added always-visible run evidence, streamed PowerShell output, live response previews, per-step token/context accounting, automatic empty-response recovery, queued steering, nested project/chat trees, and project manifests.
- Increased practical context profiles to 32K Fast, 64K Balanced, and 128K Deep while keeping output, run time, and tool steps uncapped.
- Verified the changes with 12 deterministic tests and syntax checks.

## Session 2026-08-16 (persistent product foundation and release hardening)
- Added unlimited Ollama output, context trimming, project creation, persistent project-scoped chats, native thread navigation, image/code/text/video attachments, FFmpeg frame sampling, bounded storage, Fast/Balanced/Deep profiles, Ollama capability detection, TPS evidence, fresh per-launch ports, real vision and coding-agent smoke tests, MIT licensing, Windows CI, contributor/security guidance, and secret/generated-file ignore rules.

## Session 2026-08-16 (runtime foundation and initial audit)
- Added tracked background agent runs, streaming activity, cancellation, artifact enforcement, linked local projects, stdio MCP configuration, integrated PowerShell terminal, verified completion guards, and automated agent-loop tests.
- Verified the real `qwen3.8:27b` model can write, list, read, and confirm a file before completing a task.
- Audited the installed model as a 27.3B Q4 vision/tool/thinking model with native 262,144-token context and identified the persistence, multimodal, approval, Git, release, and documentation work that followed.
