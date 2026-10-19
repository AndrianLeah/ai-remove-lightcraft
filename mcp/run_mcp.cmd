@echo off
setlocal
rem AI Remove MCP server (stdio) for Windows. Finds a Python: the installed AI Remove's, the py launcher, or uv
rem (fetched quietly into %USERPROFILE%\AIRemove\bin when missing). Only the protocol may go to stdout.
set "SERVER=%~dp0airemove_mcp.py"
if not defined AIREMOVE_HOME set "AIREMOVE_HOME=%USERPROFILE%\AIRemove"
if exist "%~dp0..\venv\Scripts\python.exe" (
  "%~dp0..\venv\Scripts\python.exe" "%SERVER%" %*
  exit /b
)
if exist "%AIREMOVE_HOME%\venv\Scripts\python.exe" (
  "%AIREMOVE_HOME%\venv\Scripts\python.exe" "%SERVER%" %*
  exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul
  if not errorlevel 1 (
    py -3 "%SERVER%" %*
    exit /b
  )
)
set "UV=%AIREMOVE_HOME%\bin\uv.exe"
if not exist "%UV%" set "UV=%AIREMOVE_HOME%\bin\bin\uv.exe"
if not exist "%UV%" for /f "delims=" %%u in ('where uv 2^>nul') do set "UV=%%u"
if not exist "%UV%" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:UV_INSTALL_DIR='%AIREMOVE_HOME%\bin'; $env:UV_NO_MODIFY_PATH='1'; irm https://astral.sh/uv/install.ps1 | iex" 1>&2
  set "UV=%AIREMOVE_HOME%\bin\uv.exe"
)
set "UV_PYTHON_INSTALL_DIR=%AIREMOVE_HOME%\python"
"%UV%" run --no-project --python 3.12 --python-preference only-managed "%SERVER%" %*
