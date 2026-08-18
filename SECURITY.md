# Security policy

Qwen Studio can read and write files and run the native shell with the permissions of the Windows, macOS, or Linux user who launched it. Only link folders you intend the model to access, inspect important commands, and treat third-party MCP servers as executable software.

The desktop webview connects to an authenticated, randomly allocated loopback endpoint. The API token is regenerated for every launch, browser origins outside the Tauri webview are rejected, and a content-security policy restricts loaded resources. These controls prevent unrelated local web pages from driving the backend; they do not protect against other processes already running with the same user privileges.

Secrets should stay in local environment variables or MCP environment configuration. Never paste credentials into chat or commit `.env`. Copied attachments and chat metadata are stored in the configured application-data directory (`%APPDATA%` on Windows, Application Support on macOS, or XDG data on Linux).

To report a vulnerability, contact the repository maintainer privately through the GitHub security advisory feature. Do not include working exploits or secrets in a public issue.
