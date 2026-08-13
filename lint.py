#!/usr/bin/env python3
import re
import sys
from pathlib import Path

# Only flag inline event handlers: onclick="...", oninput='...', etc.
ON_ATTR_RE = re.compile(r'\son[a-zA-Z]+\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', re.I | re.M)

def index_to_line_col(s: str, idx: int) -> tuple[int, int]:
    line = s.count("\n", 0, idx) + 1
    last_nl = s.rfind("\n", 0, idx)
    col = (idx + 1) if last_nl == -1 else (idx - last_nl)
    return line, col

def lint_file(path: Path) -> int:
    html = path.read_text(encoding="utf-8", errors="replace")
    errors = []

    for m in ON_ATTR_RE.finditer(html):
        line, col = index_to_line_col(html, m.start())
        attr = m.group(0).split("=", 1)[0].strip()
        errors.append((line, col, "ERROR_INLINE_EVENT", f"Inline event handler found: {attr}"))

    for line, col, code, msg in sorted(errors, key=lambda x: (x[0], x[1])):
        print(f"{path}:{line}:{col}  [{code}] {msg}")

    return 1 if errors else 0

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lint_html_errors_only_event_handlers.py path/to/file_or_dir", file=sys.stderr)
        sys.exit(2)

    target = Path(sys.argv[1])
    if target.is_dir():
        code = 0
        for p in sorted(target.rglob("*.html")):
            code = max(code, lint_file(p))
        sys.exit(code)
    else:
        sys.exit(lint_file(target))

if __name__ == "__main__":
    main()
