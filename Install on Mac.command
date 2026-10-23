#!/bin/sh
# Unsigned: macOS blocks a double-click on it when it came from the internet. Run it from Terminal instead:
#   sh "Install on Mac.command"        (or: System Settings > Privacy & Security > Open Anyway)
cd "$(dirname "$0")" || exit 1
echo "AI Remove for LightCraft and Chromaforge - installation"
echo "Downloads Python, PyTorch and the AI models (5 to 30 GB, depending on your choices)."
echo
sh ./installer/bootstrap.sh "$@"
echo
echo "You can close this window."
