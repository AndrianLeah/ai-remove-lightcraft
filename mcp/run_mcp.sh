#!/bin/sh
# AI Remove MCP server (stdio) for macOS and Linux. Finds a Python: the installed AI Remove's, a system Python 3.8+,
# or uv (fetched quietly into ~/AIRemove/bin when missing). Only the protocol may go to stdout.
HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/airemove_mcp.py"
HOME_DIR="${AIREMOVE_HOME:-$HOME/AIRemove}"
for py in "$HERE/../venv/bin/python" "$HOME_DIR/venv/bin/python"; do
  if [ -x "$py" ]; then exec "$py" "$SERVER" "$@"; fi
done
# macOS: /usr/bin/python3 without the developer tools only asks to install them, so it is used only when they are there
if command -v python3 >/dev/null 2>&1; then
  P="$(command -v python3)"
  if [ "$(uname)" != "Darwin" ] || [ "$P" != "/usr/bin/python3" ] || xcode-select -p >/dev/null 2>&1; then
    if "$P" -c 'import sys; sys.exit(sys.version_info < (3, 8))' 2>/dev/null; then exec "$P" "$SERVER" "$@"; fi
  fi
fi
UV=""
for p in "$HOME_DIR/bin/uv" "$HOME_DIR/bin/bin/uv"; do
  if [ -x "$p" ]; then UV="$p"; break; fi
done
if [ -z "$UV" ]; then UV="$(command -v uv 2>/dev/null || true)"; fi
if [ -z "$UV" ]; then
  mkdir -p "$HOME_DIR/bin"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$HOME_DIR/bin" UV_NO_MODIFY_PATH=1 sh >&2
  for p in "$HOME_DIR/bin/uv" "$HOME_DIR/bin/bin/uv"; do
    if [ -x "$p" ]; then UV="$p"; break; fi
  done
fi
UV_PYTHON_INSTALL_DIR="$HOME_DIR/python" exec "$UV" run --no-project --python 3.12 --python-preference only-managed \
  "$SERVER" "$@"
