#!/usr/bin/env python3
"""
Remove comments from:
- HTML: <!-- ... -->
- Inline CSS: /* ... */ inside <style>...</style>
- Inline JS:  //... and /* ... */ inside <script>...</script>

Usage:
  python uncomment.py input.html output.html
"""

import re
import sys
from pathlib import Path


# --- Comment stripping helpers ---

def strip_html_comments(s: str) -> str:
    # Non-greedy match; remove HTML comments: <!-- ... -->
    return re.sub(r"<!--.*?-->", "", s, flags=re.DOTALL)


def strip_css_comments(s: str) -> str:
    # Remove /* ... */ in CSS
    return re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)


def strip_js_comments(s: str) -> str:
    """
    Remove JS comments while attempting to preserve strings.
    Handles:
      - // line comments
      - /* block comments */
    Tries to not remove comment markers inside single/double/backtick strings.
    Also avoids breaking common regex literals less reliably; this is a pragmatic stripper.
    """
    out = []
    i = 0
    n = len(s)

    in_single = False
    in_double = False
    in_template = False

    in_line_comment = False
    in_block_comment = False

    escape = False

    while i < n:
        ch = s[i]
        nxt = s[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if in_single:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
            i += 1
            continue

        if in_template:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "`":
                in_template = False
            i += 1
            continue

        # Not inside a string/template/comment
        if ch == "'" :
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "`":
            in_template = True
            out.append(ch)
            i += 1
            continue

        # Start comments
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


# --- Main HTML transformation ---

def strip_comments_in_html(html: str) -> str:
    # 1) Remove HTML comments first
    html = strip_html_comments(html)

    # 2) Strip <style>...</style> CSS comments (keep tags)
    def css_repl(match: re.Match) -> str:
        open_tag = match.group(1)
        body = match.group(2)
        close_tag = match.group(3)
        return f"{open_tag}{strip_css_comments(body)}{close_tag}"

    html = re.sub(
        r"(<style\b[^>]*>)(.*?)(</style>)",
        css_repl,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 3) Strip <script>...</script> JS comments (keep tags)
    def js_repl(match: re.Match) -> str:
        open_tag = match.group(1)
        body = match.group(2)
        close_tag = match.group(3)
        return f"{open_tag}{strip_js_comments(body)}{close_tag}"

    html = re.sub(
        r"(<script\b[^>]*>)(.*?)(</script>)",
        js_repl,
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # 4) Optional: strip CSS/JS comments inside HTML attributes is not done
    #    (e.g., style="/*...*/" or onclick="...//...") because parsing those safely
    #    across JS/CSS grammars is brittle. Most people keep comments inside tags.

    return html


def main():
    if len(sys.argv) != 3:
        print("Usage: python strip_comments.py input.html output.html")
        sys.exit(1)

    inp = Path(sys.argv[1])
    outp = Path(sys.argv[2])

    html = inp.read_text(encoding="utf-8")
    cleaned = strip_comments_in_html(html)
    outp.write_text(cleaned, encoding="utf-8")


if __name__ == "__main__":
    main()
