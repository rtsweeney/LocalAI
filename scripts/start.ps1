# Starts your AI home and downloads the starter models the first time.
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
#
# The first run downloads about 25 GB (three models plus the Docker images), so it can take
# a while. Later runs take seconds.

Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Up($url) {
    try { Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 | Out-Null; return $true }
    catch { return ($null -ne $_.Exception.Response) }   # any answer at all means it is running
}

Step "1/3  Ollama (the model runner)"
if (-not (Up "http://127.0.0.1:11434")) {
    Write-Host "Ollama is not running. Start 'Ollama' from the Start menu, then run this again." -ForegroundColor Red
    exit 1
}
# The starter models. Change these any time; see docs\03-models.md.
$models = @(
    @{ name = "gpt-oss:20b";          why = "main model: chat and the app builder" },
    @{ name = "gemma4:12b";           why = "smaller and quicker: everyday chat and the news desk" },
    @{ name = "qwen3-embedding:0.6b"; why = "tiny helper that groups similar news headlines" }
)
$have = (ollama list) -join "`n"
foreach ($m in $models) {
    if ($have -match [regex]::Escape($m.name)) {
        Write-Host "Already have $($m.name)"
    } else {
        Write-Host "Downloading $($m.name) ($($m.why))"
        ollama pull $m.name
    }
}

Step "2/3  Docker (chat page, voice engine, app builder)"
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker is not running. Open 'Docker Desktop' from the Start menu, wait for" -ForegroundColor Red
    Write-Host "'Engine running', then run this again." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".env")) {
    Write-Host "No .env file. Run scripts\setup.ps1 first." -ForegroundColor Red
    exit 1
}
docker compose up -d
if ($LASTEXITCODE -ne 0) { exit 1 }

Step "3/3  Waiting for the pages to wake up (the first start can take a few minutes)"
$pages = @(
    @{ name = "Chat home page";  url = "http://localhost:3000" },
    @{ name = "App builder";     url = "http://localhost:3001/canvas" },
    @{ name = "Voice engine";    url = "http://localhost:8880/health" }
)
foreach ($p in $pages) {
    $ok = $false
    foreach ($attempt in 1..36) { if (Up $p.url) { $ok = $true; break }; Start-Sleep -Seconds 5 }
    if ($ok) { Write-Host ("  READY     {0,-16} {1}" -f $p.name, $p.url) -ForegroundColor Green }
    else     { Write-Host ("  NOT YET   {0,-16} {1}   (see docs\09-troubleshooting.md)" -f $p.name, $p.url) -ForegroundColor Yellow }
}
Write-Host "`nOpen http://localhost:3000 in your browser. The first account you create is the owner."
