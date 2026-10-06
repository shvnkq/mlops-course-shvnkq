$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
$OutputEncoding = [Console]::OutputEncoding
$Host.UI.RawUI.WindowTitle = 'HW5 LoRA - training progress'
$hw5Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $hw5Root
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONHASHSEED = '42'
& (Join-Path $hw5Root '.venv\Scripts\python.exe') -u -X utf8 (Join-Path $PSScriptRoot 'run_hw5.py')
if ($LASTEXITCODE -ne 0) { Write-Host "Training failed. See runs\training.log" -ForegroundColor Red }
