# Privacy and security

Qwen Studio is local-first: chat/model requests go to the configured Ollama URL, and application state stays in the configured data directory. The app does not need an OpenAI key.

Attachments are copied into local application data. Deleting an attachment removes its copied directory; unlinking a project never deletes the project folder. MCP servers may communicate externally depending on their implementation.

The desktop UI talks to Python only over a randomly selected loopback port. Each launch creates a new API token, requests without it are rejected, and cross-origin access is restricted to the Tauri webview. The token is held in process memory rather than persistent configuration. A restrictive content-security policy limits what the desktop webview can load.

## Current trust boundary

Built-in file and native shell tools run with the same operating-system permissions as the person who launched the app. Project-write mode confines normal file work to the linked project, and commands classified as destructive, privileged, external, networked, or MCP-backed require approval. This is an application guardrail, not an operating-system sandbox.

- Use dedicated project folders and source control.
- Do not run the app elevated.
- Review important file and system changes.
- Keep secrets out of prompts and repositories.
- Only connect trusted MCP servers.

Use read-only mode when inspection is enough. Full-access mode should be reserved for work that genuinely needs files outside the active project.
