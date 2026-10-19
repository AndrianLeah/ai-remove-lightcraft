# AI Remove for LightCraft - Windows bootstrap.
# Gets uv (a small Python manager, into <install>\bin) if it is missing, then runs install.py on a Python 3.12 that
# uv keeps in <install>\python - outside AppData on purpose: LightCraft has to start it. Arguments go to install.py
# (--dir DIR, --models ..., --yes, --uninstall, ...).
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$pkg = Split-Path -Parent $PSScriptRoot

$dir = $env:AIREMOVE_HOME
for ($i = 0; $i -lt $args.Count - 1; $i++) { if ($args[$i] -eq '--dir') { $dir = $args[$i + 1] } }
if (-not $dir) { $dir = Join-Path $env:USERPROFILE 'AIRemove' }
$dir = [IO.Path]::GetFullPath($dir.TrimEnd('\'))
$bin = Join-Path $dir 'bin'

function Find-Uv {
  foreach ($p in @((Join-Path $bin 'uv.exe'), (Join-Path $bin 'bin\uv.exe'))) { if (Test-Path $p) { return $p } }
  $c = Get-Command uv -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  return $null
}
$uv = Find-Uv
if (-not $uv) {
  Write-Host 'Downloading uv (a Python manager, ~20 MB)...'
  New-Item -ItemType Directory -Force $bin | Out-Null
  $env:UV_INSTALL_DIR = $bin
  $env:UV_NO_MODIFY_PATH = '1'
  Invoke-RestMethod 'https://astral.sh/uv/install.ps1' | Invoke-Expression
  $uv = Find-Uv
  if (-not $uv) { Write-Host 'ERROR: uv was not installed (internet connection?)'; exit 1 }
}
$env:UV_PYTHON_INSTALL_DIR = Join-Path $dir 'python'
$env:UV_PYTHON_PREFERENCE = 'only-managed'
$env:AIREMOVE_UV = $uv
$env:AIREMOVE_HOME = $dir
$env:PYTHONIOENCODING = 'utf-8'
& $uv run --no-project --python 3.12 (Join-Path $pkg 'installer\install.py') @args
exit $LASTEXITCODE
