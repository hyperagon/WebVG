#!/usr/bin/env python3
# html_lint.py
import re
import sys
from html.parser import HTMLParser

VOID_TAGS = {
    "area","base","br","col","embed","hr","img","input","link","meta",
    "param","source","track","wbr"
}

OPEN_TAG_RE = re.compile(r"<\s*([a-zA-Z][\w:-]*)\b")
CLOSE_TAG_RE = re.compile(r"<\s*/\s*([a-zA-Z][\w:-]*)\s*>")

# Best-effort JS/CSS syntax checks via stdlib regex heuristics only.
# (We still do real HTML checking + we *allow* standalone "<" in JS/CSS content.)
def lint_js_code(code, context):
    # If literal closing script/style tags appear inside the code, they can break HTML parsing
    # (e.g., onclick="... </script> ...").
    for tag in ("script", "style"):
        if re.search(rf"</\s*{tag}\s*>", code, flags=re.I):
            yield f"{context}: contains literal </{tag}> inside JS context; this can prematurely terminate the parent tag."

    # Basic bracket balance (not full JS correctness, but catches common mistakes)
    pairs = {"(":")", "[":"]", "{":"}"}
    stack = []
    strings = []
    in_single = in_double = in_template = False
    escape = False

    for ch in code:
        if escape:
            escape = False
            continue
        if ch == "\\" and (in_single or in_double or in_template):
            escape = True
            continue

        # crude string tracking so we don’t count braces inside strings
        if in_template:
            if ch == "`":
                in_template = False
            elif ch == "$":
                # ${ ... } inside template: ignore (still inside template)
                pass
            continue
        if in_single:
            if ch == "'":
                in_single = False
            continue
        if in_double:
            if ch == '"':
                in_double = False
            continue

        if ch == "'":
            in_single = True
            continue
        if ch == '"':
            in_double = True
            continue
        if ch == "`":
            in_template = True
            continue

        if ch in pairs:
            stack.append(ch)
        elif ch in pairs.values():
            if not stack:
                yield f"{context}: unmatched closing bracket '{ch}' in JS (heuristic)."
            else:
                open_ch = stack.pop()
                if pairs[open_ch] != ch:
                    yield f"{context}: mismatched brackets in JS (heuristic): expected {pairs[open_ch]}, got {ch}."

    if stack:
        yield f"{context}: unclosed bracket(s) in JS (heuristic)."

    # Specific request: "< can be alone inside CSS or JS" -> DO NOT flag it.
    # We simply avoid treating a bare "<" as an error.

def lint_css_code(code, context):
    # Similar tag-break check for </style> inside style content.
    for tag in ("style", "script"):
        if re.search(rf"</\s*{tag}\s*>", code, flags=re.I):
            yield f"{context}: contains literal </{tag}> inside CSS context; this can prematurely terminate the parent tag."

    # Heuristic: basic { ... } balance
    stack = 0
    in_single = in_double = False
    escape = False

    for i, ch in enumerate(code):
        if escape:
            escape = False
            continue
        if ch == "\\" and (in_single or in_double):
            escape = True
            continue

        if in_single:
            if ch == "'":
                in_single = False
            continue
        if in_double:
            if ch == '"':
                in_double = False
            continue

        if ch == "'":
            in_single = True
            continue
        if ch == '"':
            in_double = True
            continue

        if ch == "{":
            stack += 1
        elif ch == "}":
            stack -= 1
            if stack < 0:
                yield f"{context}: unmatched '}}' in CSS (heuristic)."
                stack = 0

    if stack != 0:
        yield f"{context}: unbalanced '{{' / '}}' in CSS (heuristic)."

def lint_html(text):
    problems = []

    class LintParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.tag_stack = []
            self.self_closing_override = set()  # not reliable in HTMLParser
            self.last_declared_script_style = False

        def _loc(self, line, offset):
            # HTMLParser gives 1-based line, offset within line
            return f"line {line}, col {offset+1}"

        def handle_starttag(self, tag, attrs):
            t = tag.lower()
            line, offset = self.getpos()

            # void tags should not have end tags (heuristic check later too)
            if t in VOID_TAGS:
                # If parser sees a start tag for a void tag, it will ignore any end tag in many cases.
                # We'll still flag if it later gets an explicit end tag.
                pass

            # Tag nesting sanity: cannot start a new <style> inside another <style>/<script>
            if t in ("script", "style"):
                # If already inside one, that's suspicious
                if any(x in ("script", "style") for x in self.tag_stack):
                    problems.append(f"HTML: nested <{t}> inside <{self.tag_stack[-1]}> {self._loc(line, offset)}")

            # Inline CSS/JS checks
            attr_dict = {k.lower(): v for (k, v) in attrs if k is not None}
            if "style" in attr_dict and attr_dict["style"] is not None:
                for m in lint_css_code(attr_dict["style"], context=f"<{t} style=\"...\"> {self._loc(line, offset)}"):
                    problems.append(m)

            for k, v in attr_dict.items():
                if k.startswith("on") and v is not None:
                    for m in lint_js_code(v, context=f"<{t} {k}=\"...\"> {self._loc(line, offset)}"):
                        problems.append(m)

            # Push to stack unless void
            if t not in VOID_TAGS:
                self.tag_stack.append(t)

        def handle_endtag(self, tag):
            t = tag.lower()
            line, offset = self.getpos()
            if t in ("script", "style"):
                # script/style content will be handled in handle_data when we're in it
                pass

            if not self.tag_stack:
                problems.append(f"HTML: unexpected closing </{t}> without an open tag {self._loc(line, offset)}")
                return

            # Pop until we find matching tag (HTMLParser may be forgiving; we warn)
            if self.tag_stack[-1] == t:
                self.tag_stack.pop()
            else:
                # find matching
                if t in self.tag_stack:
                    # mismatched nesting
                    exp = self.tag_stack[-1]
                    problems.append(
                        f"HTML: closing </{t}> mismatches currently open <{exp}> {self._loc(line, offset)}"
                    )
                    # pop everything until t
                    while self.tag_stack and self.tag_stack[-1] != t:
                        self.tag_stack.pop()
                    if self.tag_stack and self.tag_stack[-1] == t:
                        self.tag_stack.pop()
                else:
                    problems.append(f"HTML: closing </{t}> has no corresponding open tag {self._loc(line, offset)}")

        def handle_startendtag(self, tag, attrs):
            # self-closing tags like <br/> are okay; HTMLParser treats as startend.
            t = tag.lower()
            line, offset = self.getpos()
            attr_dict = {k.lower(): v for (k, v) in attrs if k is not None}
            if "style" in attr_dict and attr_dict["style"] is not None:
                for m in lint_css_code(attr_dict["style"], context=f"<{t}/ style=\"...\"> {self._loc(line, offset)}"):
                    problems.append(m)
            for k, v in attr_dict.items():
                if k.startswith("on") and v is not None:
                    for m in lint_js_code(v, context=f"<{t}/ {k}=\"...\"> {self._loc(line, offset)}"):
                        problems.append(m)

        def handle_data(self, data):
            # Capture inline JS/CSS inside <script>...</script> and <style>...</style>
            if not self.tag_stack:
                return
            cur = self.tag_stack[-1]
            if cur not in ("script", "style"):
                return

            # Heuristic: treat all text inside as code and lint it.
            # We don’t treat a standalone "<" as an error (per your requirement).
            line, offset = self.getpos()
            snippet = data.strip()
            if not snippet:
                return

            if cur == "script":
                for m in lint_js_code(snippet, context=f"<script> content {self._loc(line, offset)}"):
                    problems.append(m)
            elif cur == "style":
                for m in lint_css_code(snippet, context=f"<style> content {self._loc(line, offset)}"):
                    problems.append(m)

    parser = LintParser()
    parser.feed(text)

    # Unclosed tags
    for t in reversed(parser.tag_stack):
        problems.append(f"HTML: unclosed <{t}> at end of file")

    # Tag pairing basic sanity: warn if explicit closing tag exists for void tags (best-effort)
    # (HTMLParser is forgiving; still useful to catch common mistakes.)
    for m in re.finditer(r"</\s*([a-zA-Z][\w:-]*)\s*>", text):
        t = m.group(1).lower()
        if t in VOID_TAGS:
            # compute rough location
            before = text[:m.start()]
            line = before.count("\n") + 1
            col = len(before) - (before.rfind("\n") + 1)
            problems.append(f"HTML: void tag </{t}> should not be used {f'line {line}, col {col}'}")

    return problems

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 html_lint.py path/to/file.html")
        sys.exit(2)

    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    problems = lint_html(text)
    if not problems:
        print("OK: no problems found")
        return

    for p in problems:
        print(p)
    sys.exit(1)

if __name__ == "__main__":
    main()
