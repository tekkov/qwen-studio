# Qwen Studio product audit

Audit date: 2026-08-16; implementation status updated after the first remediation pass.

## Remediation status

The P0 foundation is now substantially stronger than the initial assessment below: projects can be created or linked; project-scoped threads persist and can be renamed or archived; image, text/code, and sampled-video attachments reach Ollama; Fast/Balanced/Deep profiles use detected runtime metadata and bounded context; the desktop backend uses a fresh port per launch; and deterministic API/storage tests plus real vision/tool-use tests pass. Public-repository basics now include MIT licensing, CI, contribution/security guidance, and focused documentation.

Remaining blockers for a stable 1.0 are interactive permission/approval profiles, persistent jobs and restart recovery, Markdown/code rendering, a Git diff/review surface, richer MCP transports/auth, and packaged visual accessibility testing.

## Executive assessment

The initial audit found that Qwen Studio proved the core local-agent loop but was not yet a Codex-class desktop product or public-repository-ready application. The remediation status above records what has since been implemented.

The largest gaps are architectural rather than cosmetic: conversations exist only in renderer memory, attachments are absent, model capabilities are hard-coded, tool execution has no permission boundary, jobs disappear on restart, the terminal is a command runner rather than a PTY, and the repository lacks Git history, CI, licensing, contribution guidance, and a release process.

## Installed runtime capability

| Capability | Installed runtime | Current app support | Audit decision |
| --- | --- | --- | --- |
| Text generation | `qwen3.8:27b`, Q4_K_M | Yes | Keep and optimize profiles. |
| Tool calling | Reported by Ollama | Yes, basic loop | Add permissions, richer tools, and durable events. |
| Thinking | Reported by Ollama | Fast off / Deep on | Add Balanced mode and explicit budgets. |
| Vision | Reported by Ollama with CLIP projector | No | Add image attachments through Ollama `images`. |
| Video | No direct Ollama chat transport | No | Sample frames with local FFmpeg and send bounded image sequences. |
| Native context | 262,144 tokens | Hard-coded 8,192 / 32,768 | Detect capability; use practical adaptive bounds. |
| MCP | stdio only | Partial | Add health, enablement, approvals, HTTP, and auth. |

## Performance findings

- Hardware is an RTX 5060 with 8 GB VRAM, 32 GB system RAM, and a 10-core Intel Core Ultra 5 225F.
- The 27.3B Q4 model occupies most available VRAM and spills substantial work outside VRAM, so generation around 4–5 TPS is expected on this machine.
- Cold prompt evaluation has reached multiple minutes while warm tool turns are materially faster.
- Raising every chat to the native 262K context would sharply increase KV-cache and prompt-evaluation cost. The app should expose adaptive practical profiles rather than advertising the model maximum as the default.
- The current app records generation TPS but not first-token latency, prompt TPS, queue time, or context utilization.

## Functional gaps

### P0 blockers

- No persistent chats, thread titles, thread search, archive, pin, or per-project conversation history.
- No upload button, drag-and-drop, attachment preview, image payload, video frame sampling, or document extraction.
- No markdown renderer, syntax-highlighted code blocks, copy actions, or clickable artifact summary.
- No durable job store or recovery after backend restart.
- No model capability discovery; model name and context profiles are hard-coded.
- No permission profiles or approvals despite commands running as the current Windows user.
- No structured file-change ledger or Git diff/review surface.
- Blocking browser alerts and unsafe string interpolation remain in UI paths.
- The app is a small monolithic Python server and renderer script with no schema/versioning boundary.

### P1 parity gaps

- No project instructions, nested guidance, reusable workflow skills, hooks, or environment actions.
- No Streamable HTTP MCP, OAuth, per-tool enablement, or tool approval policy.
- No real PTY resizing/stdin, background process list, or terminal-to-thread ownership.
- No worktrees, review mode, rollback, branch context, browser testing, image generation, or remote executor.

### Open-source blockers

- The directory is not initialized as a Git repository.
- No application license, contributor guide, code of conduct, CI, issue templates, changelog, or release checks.
- `.env` exists locally; ignore and secret-scanning rules must be verified before Git initialization.
- The package metadata lacks author/repository fields and the current build disables ASAR.
- Documentation does not yet describe every endpoint, persistence file, permission risk, or troubleshooting path.

## Target architecture

Use durable primitives similar to a rich agent client:

- **Project**: one or more folders, a primary working directory, instructions, settings, and threads.
- **Thread**: persistent conversation metadata and ordered turns, scoped to a project.
- **Turn**: one user request plus attachments, run state, tool events, metrics, and final response.
- **Artifact**: a verified file change or generated output with path, type, size, and verification evidence.
- **Attachment**: immutable copied input with original name, media type, size, processing status, and derived frames/text.
- **Process**: terminal or agent command with streamed output, owner thread, PID, status, and stop semantics.

Persist metadata with versioned JSON initially, behind storage functions that can migrate to SQLite without changing HTTP contracts. Store copied attachments under the application data directory, never inside the packaged application folder.

## UX direction

The interface should use precision-and-density with a restrained refined flavor: compact project/thread rail, clear active context, low-noise surfaces, one cobalt accent, and status color only for meaning. The signature move is a thin active-context rail that connects project, thread, and run state.

Every long-running state must answer four questions without expansion: what is happening, where it is happening, what changed most recently, and what the user can do next.

## Verification policy

A feature is complete only after:

1. Unit coverage for parsing, persistence, and state transitions.
2. API integration coverage for happy, empty, error, and cancellation states.
3. At least one real-model smoke test for model-facing behavior.
4. Packaged executable verification that required assets and runtime files are present.
5. Documentation synchronized with the actual behavior.
