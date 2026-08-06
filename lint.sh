#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 [--dir DIR] file1.html [file2.html ...]" >&2
  exit 2
}

MODE="files"
DIR=""

if [[ "${1:-}" == "--dir" ]]; then
  MODE="dir"
  DIR="${2:-}"; [[ -n "$DIR" ]] || usage
  shift 2
fi

FILES=()
if [[ "$MODE" == "dir" ]]; then
  while IFS= read -r -d '' f; do FILES+=("$f"); done < <(find "$DIR" -type f -name '*.html' -print0)
else
  [[ $# -gt 0 ]] || usage
  FILES=("$@")
fi

lint_file() {
  local file="$1"

  awk -v FILE="$file" '
    function emit(ln, rule, msg) {
      printf "%s:%d:%s:%s\n", FILE, ln, rule, msg
    }

    function count_char(str, re) {
      gsub(re, "", str)
      return 0
    }

    # Lint delimiters + quote balance inside a region string (no HTML parsing; char-by-char)
    function lint_region(region_text, start_ln, region_name,   in_squote, in_dquote, prev, n, i, ch, line_no, sp, stack, open_expected) {
      in_squote=0; in_dquote=0; prev=""
      line_no=0

      sp=0

      n=length(region_text)
      for (i=1; i<=n; i++) {
        ch=substr(region_text, i, 1)

        if (ch=="\n") { line_no++; continue }

        # quote toggling (backslash-aware, best-effort)
        if (!in_dquote && ch=="\047") { # single quote
          if (prev!="\\") in_squote = !in_squote
          prev=ch
          continue
        }
        if (!in_squote && ch=="\"") {
          if (prev!="\\") in_dquote = !in_dquote
          prev=ch
          continue
        }

        if (in_squote || in_dquote) {
          prev=ch
          continue
        }

        if (ch=="(") { sp++; stack[sp]="("; }
        else if (ch==")") {
          if (sp<=0) { emit(start_ln+line_no, "DELIM.UNDERFLOW", "Unmatched ) in " region_name); }
          else if (stack[sp]!="(") { emit(start_ln+line_no, "DELIM.MISMATCH", "Mismatched ) in " region_name); sp--; }
          else { sp--; }
        }
        else if (ch=="{") { sp++; stack[sp]="{"; }
        else if (ch=="}") {
          if (sp<=0) { emit(start_ln+line_no, "DELIM.UNDERFLOW", "Unmatched } in " region_name); }
          else if (stack[sp]!="{") { emit(start_ln+line_no, "DELIM.MISMATCH", "Mismatched } in " region_name); sp--; }
          else { sp--; }
        }
        else if (ch=="[") { sp++; stack[sp]="["; }
        else if (ch=="]") {
          if (sp<=0) { emit(start_ln+line_no, "DELIM.UNDERFLOW", "Unmatched ] in " region_name); }
          else if (stack[sp]!="[") { emit(start_ln+line_no, "DELIM.MISMATCH", "Mismatched ] in " region_name); sp--; }
          else { sp--; }
        }

        prev=ch
      }

      if (in_squote) emit(start_ln, "QUOTE.UNCLOSED", "Unclosed single quote in " region_name)
      if (in_dquote) emit(start_ln, "QUOTE.UNCLOSED", "Unclosed double quote in " region_name)
      if (sp>0) emit(start_ln, "DELIM.UNCLOSED", "Unclosed opening delimiter(s) in " region_name)
    }

    BEGIN {
      in_style=0; in_script=0
      style_ln=0; script_ln=0
      style_buf=""; script_buf=""
    }

    {
      # literal << anywhere
      if (index($0, "<<")>0) {
        emit(NR, "SYM.DOUBLE_LESSTHAN", "Found literal \"<<\"")
      }
      
      if (index($0, "<<")>0) {
        emit(NR, "SYM.DOUBLE_GREATERTHAN", "Found literal \">>\"")
      }

      if (!in_style && $0 ~ /<style([[:space:]]|>)/) {
        in_style=1
        style_ln=NR
        # take remainder after opening tag
        sub(/.*<style[^>]*>/, "")
        style_buf = $0 "\n"
        next
      }

      if (in_style) {
        if ($0 ~ /<\/style>/) {
          sub(/<\/style>.*/, "")
          style_buf = style_buf $0 "\n"
          in_style=0
          lint_region(style_buf, style_ln, "STYLE")
          style_buf=""
          next
        } else {
          style_buf = style_buf $0 "\n"
          next
        }
      }

      if (!in_script && $0 ~ /<script([[:space:]]|>)/) {
        in_script=1
        script_ln=NR
        sub(/.*<script[^>]*>/, "")
        script_buf = $0 "\n"
        next
      }

      if (in_script) {
        if ($0 ~ /<\/script>/) {
          sub(/<\/script>.*/, "")
          script_buf = script_buf $0 "\n"
          in_script=0
          lint_region(script_buf, script_ln, "SCRIPT")
          script_buf=""
          next
        } else {
          script_buf = script_buf $0 "\n"
          next
        }
      }
    }

    END {
      if (in_style) emit(style_ln, "BLOCK.UNCLOSED", "Unclosed <style> block")
      if (in_script) emit(script_ln, "BLOCK.UNCLOSED", "Unclosed <script> block")
    }
  ' "$file"
}

for f in "${FILES[@]}"; do
  [[ -f "$f" ]] || continue
  lint_file "$f"
done
