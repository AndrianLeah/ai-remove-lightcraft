#!/bin/sh
# In a terminal: sh "Install on Linux.sh"   (or make it executable and run it)
cd "$(dirname "$0")" || exit 1
echo "AI Remove for LightCraft and Chromaforge - installation"
echo "Downloads Python, PyTorch and the AI models (5 to 30 GB, depending on your choices)."
echo
sh ./installer/bootstrap.sh "$@"
