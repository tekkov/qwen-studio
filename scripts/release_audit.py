"""Small, dependency-free release gate for the public repository."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", "node_modules", "dist", "frontend-dist", "target", ".venv", "__pycache__"}
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(OPENAI_API_KEY|CODEX_API_KEY)\s*=\s*[^\s<$][^\r\n]*"),
]

def files_to_scan():
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDED for part in path.parts):
            continue
        if path.name == ".env" or path.suffix.lower() in {".png", ".ico", ".exe", ".mp4", ".zip"}:
            continue
        yield path

def main():
    errors = []
    for path in files_to_scan():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            errors.append(f"Could not read {path.relative_to(ROOT)}: {error}")
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text) and path.name not in {".env.example", "release_audit.py"}:
                errors.append(f"Possible secret in {path.relative_to(ROOT)}")
                break
    readme = ROOT / "README.md"
    if readme.is_file():
        readme_text = readme.read_text(encoding="utf-8", errors="replace")
        for target in re.findall(r"\]\(([^)#]+)", readme_text):
            if target.startswith("http"):
                continue
            if not (ROOT / target).exists():
                errors.append(f"Broken README link: {target}")
    required = ["server.py", "index.html", "app.js", "tauri-bridge.js", "src-tauri/tauri.conf.json", "mcp-bridge.mjs", "LICENSE", ".env.example"]
    errors.extend(f"Missing release file: {item}" for item in required if not (ROOT / item).exists())
    if errors:
        print("Release audit failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print(f"Release audit passed: {sum(1 for _ in files_to_scan())} text files scanned; links, required files, and secret patterns are clean.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
