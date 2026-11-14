# One-time setup for your AI home. Run it from the LocalAI folder:
#
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
#
# What it does, in order:
#   1. Checks your graphics card.
#   2. Installs the programs (Ollama, Docker Desktop, Python, Git, Tailscale) with winget,
#      the installer that comes with Windows. Anything already installed is left alone.
#   3. Tells Ollama to give models a longer memory (needed by the app builder).
#   4. Creates your private settings file (.env) and the folder for apps the AI builds.
#
# It is safe to run more than once.

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "1/4  Checking your graphics card"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpu = (nvidia-smi --query-gpu=name,memory.total --format=csv,noheader) | Select-Object -First 1
    Write-Host "Found: $gpu"
    Write-Host "The second number is your VRAM in MiB. 16 GB shows as roughly 16000 MiB."
} else {
    Write-Host "nvidia-smi was not found." -ForegroundColor Yellow
    Write-Host "If you have an NVIDIA card, install its driver from https://www.nvidia.com/drivers"
    Write-Host "then run this script again. Continuing anyway."
}

Step "2/4  Installing programs (each may show a Windows permission prompt)"
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again." -ForegroundColor Red
    exit 1
}
$programs = @(
    @{ id = "Ollama.Ollama";         why = "runs the AI models on your graphics card" },
    @{ id = "Docker.DockerDesktop";  why = "runs the chat page, voice engine and app builder" },
    @{ id = "Python.Python.3.12";    why = "runs the small tools in this folder" },
    @{ id = "Git.Git";               why = "downloads updates to this folder" },
    @{ id = "Tailscale.Tailscale";   why = "private connection from your iPhone" }
)
foreach ($p in $programs) {
    Write-Host "`n$($p.id): $($p.why)"
    winget install --exact --id $p.id --accept-source-agreements --accept-package-agreements
    # winget returns a non-zero code when the program is already installed. That is fine.
}

Step "3/4  Giving models a longer memory"
# "Context length" is how much text a model can keep in mind at once, counted in tokens
# (a token is about three quarters of a word). Ollama's default is too small for the app
# builder, whose instructions alone are thousands of tokens long.
[Environment]::SetEnvironmentVariable("OLLAMA_CONTEXT_LENGTH", "32768", "User")
Write-Host "Set OLLAMA_CONTEXT_LENGTH=32768 for your Windows account."

Step "4/4  Creating your private settings"
if (-not (Test-Path ".env")) {
    $bytes = New-Object byte[] 32
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secret = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    (Get-Content ".env.example") -replace "^WEBUI_SECRET_KEY=.*", "WEBUI_SECRET_KEY=$secret" |
        Set-Content ".env" -Encoding ascii
    Write-Host "Created .env with a fresh random secret."
} else {
    Write-Host ".env already exists. Left as it is."
}
New-Item -ItemType Directory -Force -Path "apps" | Out-Null
Write-Host "Apps the AI builds will appear in: $(Resolve-Path 'apps')"

Write-Host "`nSetup finished." -ForegroundColor Green
Write-Host "Next:"
Write-Host "  1. RESTART YOUR PC. Docker and the new settings need it."
Write-Host "  2. Open Docker Desktop once from the Start menu and accept its terms."
Write-Host "     Wait until it says 'Engine running'."
Write-Host "  3. Run:  powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1"
