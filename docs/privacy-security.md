# Privacy and security

Qwen Studio is local-first: chat/model requests go to the configured Ollama URL, and application state stays in the configured data directory. The app does not need an OpenAI key.

Attachments are copied into local application data. Deleting an attachment removes its copied directory; unlinking a project never deletes the project folder. MCP servers may communicate externally depending on their implementation.

## Current trust boundary

Built-in file and PowerShell tools run with the same Windows permissions as the person who launched the app. The current release does not yet pause each write or command for approval.

- Use dedicated project folders and source control.
- Do not run the app elevated.
- Review important file and system changes.
- Keep secrets out of prompts and repositories.
- Only connect trusted MCP servers.

Read-only/project-write/full-access profiles and interactive approvals are tracked before a stable 1.0 release.
