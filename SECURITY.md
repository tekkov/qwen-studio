# Security policy

Qwen Studio can read and write files and run PowerShell with the permissions of the Windows user who launched it. Only link folders you intend the model to access, inspect important commands, and treat third-party MCP servers as executable software.

Secrets should stay in local environment variables or MCP environment configuration. Never paste credentials into chat or commit `.env`. Copied attachments and chat metadata are stored locally under `%APPDATA%\QwenLocalAgent` by default.

To report a vulnerability, contact the repository maintainer privately through the GitHub security advisory feature. Do not include working exploits or secrets in a public issue.
