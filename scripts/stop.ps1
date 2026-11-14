# Stops the chat page, voice engine and app builder. Your chats and settings are kept.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\stop.ps1
#
# Ollama keeps running in the Windows tray (near the clock). Right-click its icon to quit it.

Set-Location (Split-Path $PSScriptRoot -Parent)
docker compose stop
Write-Host "Stopped. Start again with scripts\start.ps1"
