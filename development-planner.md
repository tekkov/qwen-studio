# Formatting practices (keep consistent)
- Use H1 for top-level sections, H2 for subgroups, H3 for task headers.
- Keep bullets concise; prefer past-tense summaries in Completed, imperative in Current.
- Include file paths in backticks; avoid line breaks inside bullets unless needed.
- When priorities are empty, note `None` under Current priorities.
- Add new sessions at the top of Completed with date-stamped headers.

# Current priorities

## P0 (current)

### P0-01 — Persistent projects and chat threads
- Add pin/delete controls and preserve completed run summaries across restarts.
- Verify project switching and the packaged thread experience.

### P0-02 — Multimodal attachments
- Add document extraction for PDF/DOCX and explicit unsupported-format guidance.
- Verify size limits and a real video-frame understanding prompt.

### P0-03 — Runtime speed and context efficiency
- Add output-token controls, queue-time/context-utilization metrics, and higher-quality semantic compaction.
- Verify cold/warm benchmarks, stalled streams, and duplicate-run protection.

### P0-04 — Product shell and agent transparency
- Replace blocking alerts and fragile `innerHTML` interpolation with accessible inline feedback and safe DOM rendering.
- Add markdown/code rendering, copy controls, artifact links, empty/loading/error states, and responsive behavior.
- Verify: keyboard navigation, reduced motion, narrow layout, long content, error states, and packaged visual smoke test.

### P0-05 — Test and open-source release baseline
- Expand integration coverage for cancellation, terminal processes, MCP failures, attachment limits, and packaged startup.
- Add issue templates and release notes, then initialize Git after a final secret scan.
- Verify: clean clone setup, tests, package build, secret scan, and documentation link audit.

## P1 (phase 2)

### P1-01 — Permission and approval model
- Add read-only, project-write, and full-access profiles with explicit approvals for external, destructive, and network actions.
- Add a reviewable command/file-change approval surface and durable per-project defaults.
- Verify: denied path, approved path, destructive action, network action, and MCP write-action tests.

### P1-02 — Git and code review workspace
- Add repository status, diff inspection, file review, rollback-safe patch previews, and test-result summaries.
- Add branch and worktree awareness without running destructive Git commands automatically.
- Verify: clean repo, dirty repo, non-repo folder, multi-repository project, and binary diff states.

### P1-03 — MCP and reusable workflow expansion
- Add Streamable HTTP MCP, OAuth/bearer configuration, enable/disable controls, tool approval modes, and diagnostics.
- Add project instruction discovery and reusable local workflow/skill loading.
- Verify: stdio, HTTP, auth-required, startup failure, timeout, and tool-deny tests.

## P2 (future)

### P2-01 — Browser, computer, and remote execution
- Add explicitly permissioned browser testing, screenshot feedback, and remote executor architecture.
- Keep local-only operation as the default and document every optional dependency.
- Verify: browser unavailable, browser available, permission denied, and remote disconnect states.

# Completed Action Items

## Session 2026-08-16 (persistent product foundation and release hardening)
- Removed automatic model and agent-step limits, enabled unlimited Ollama output, added per-step context trimming with preserved system instructions, and made slow-processing UI states truthful.
- Added project creation, persistent project-scoped chats, rename/archive controls, model mode persistence, and native thread navigation.
- Added image, code/text, and video attachment intake with previews, bounded extraction, FFmpeg frame sampling, local storage, and Ollama vision payloads.
- Added Fast/Balanced/Deep profiles, Ollama capability detection, practical context trimming, first-token timing, prompt processing speed, and generation TPS evidence.
- Replaced the shared fixed backend port with a fresh per-launch port so new UI builds cannot attach to stale packaged servers.
- Added eight passing automated tests, a passing real vision test at 4.03 TPS, and passing real coding-agent file-write/read smoke tests.
- Added MIT licensing, Windows CI, contributor/security guidance, focused documentation, and secret/generated-file ignore rules.

## Session 2026-08-16 (runtime foundation and initial audit)
- Added tracked background agent runs, streaming activity, cancellation, artifact enforcement, and performance metrics in `server.py` and `app.js`.
- Added linked local projects, stdio MCP configuration, and a project-scoped integrated PowerShell terminal.
- Added a verified completion guard and automated agent-loop tests in `tests/test_agent.py`.
- Verified the real `qwen3.8:27b` model can write, list, read, and confirm a file before completing a task.
- Audited the installed model as a 27.3B Q4_K_M vision/tool/thinking model with native 262,144-token context.
- Identified missing persistence, multimodal intake, approvals, Git review, release automation, and open-source documentation as product blockers.
