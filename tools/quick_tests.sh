#!/usr/bin/env bash
# Fast checks (about 15 s) that Claude's finish check runs after a turn that edited app code
# (.claude/quick-tests.json). The full suites stay in CLAUDE.md "Build & test" and CI.
#   tools/quick_tests.sh py    core unit tests on Windows Python (from WSL)
#   tools/quick_tests.sh js    the window's JavaScript and the look checklist (jsdom)
set -e
cd "$(dirname "$0")/.."
case "${1:-py}" in
  js) npm run --silent smoke && exec npm run --silent look ;;
  py)
    . tools/winpy.sh
    files=()
    for t in text replacements voice_commands platform_contract config meetings mcp window_api app \
             transcribe commands snippets segclean routing meeting_notes export insights sessions; do
      files+=("$APP_W\\tests\\test_$t.py")
    done
    WTIMEOUT=110 wtest "${files[@]}" -q -x -m "not gpu and not win" ;;
esac
