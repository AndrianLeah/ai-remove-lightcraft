@echo off
chcp 65001 >nul
title AI Remove for LightCraft and Chromaforge - installation
echo AI Remove for LightCraft and Chromaforge - installation
echo Downloads Python, PyTorch and the AI models (5 to 30 GB, depending on your choices).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\bootstrap.ps1" %*
echo.
pause
