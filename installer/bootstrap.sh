#!/bin/sh
# AI Remove for LightCraft and Chromaforge - macOS / Linux bootstrap.
# Gets uv (a small Python manager, into <install>/bin) if it is missing, then runs install.py on a Python 3.12 that
# uv keeps in <install>/python (with Tk, which some Linux distributions' Python lacks). Arguments go to install.py
# (--dir DIR, --models ..., --yes, --uninstall, ...).
set -e
PKG="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${AIREMOVE_HOME:-$HOME/AIRemove}"
prev=""
for a in "$@"; do
  if [ "$prev" = "--dir" ]; then DIR="$a"; fi
  prev="$a"
done
case "$DIR" in
  "~"*) DIR="$HOME${DIR#\~}" ;;
  /*) ;;
  *) DIR="$PWD/$DIR" ;;
esac
BIN="$DIR/bin"

find_uv() {
  for p in "$BIN/uv" "$BIN/bin/uv"; do
    if [ -x "$p" ]; then echo "$p"; return 0; fi
  done
  command -v uv 2>/dev/null || true
}
UV="$(find_uv)"
if [ -z "$UV" ]; then
  echo "Downloading uv (a Python manager, ~20 MB)..."
  mkdir -p "$BIN"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN" UV_NO_MODIFY_PATH=1 sh
  else
    wget -qO- https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$BIN" UV_NO_MODIFY_PATH=1 sh
  fi
  UV="$(find_uv)"
  if [ -z "$UV" ]; then echo "ERROR: uv was not installed (internet connection?)"; exit 1; fi
fi
export UV_PYTHON_INSTALL_DIR="$DIR/python" UV_PYTHON_PREFERENCE=only-managed AIREMOVE_UV="$UV" \
  AIREMOVE_HOME="$DIR" PYTHONIOENCODING=utf-8
exec "$UV" run --no-project --python 3.12 "$PKG/installer/install.py" "$@"
