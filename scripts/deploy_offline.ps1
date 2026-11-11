# Windows 10/11 x64 with Docker Desktop in Linux-container mode.
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
        throw 'Install and start Docker Desktop first.'
    }
    $engine = & docker.exe info --format '{{.OSType}}/{{.Architecture}}'
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop is not running.' }
    if ($engine.Trim() -notmatch '^linux/(amd64|x86_64)$') {
        throw 'This Windows x64 bundle requires Docker Desktop in Linux-container mode (WSL2 backend).'
    }
    & docker.exe compose version
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose v2 is required.' }
    if (-not (Test-Path -LiteralPath '.env')) {
        Copy-Item -LiteralPath '.env.example' -Destination '.env'
        Write-Host 'Created .env. Configure your LLM provider/API key, then run deploy.bat again.'
        exit 1
    }
    Write-Host 'Loading application and PostgreSQL images...'
    & docker.exe load --input 'images.tar'
    if ($LASTEXITCODE -ne 0) { throw 'Docker image import failed.' }
    Write-Host 'Starting ScholarFlow with local images and model files...'
    & docker.exe compose up -d --pull never
    if ($LASTEXITCODE -ne 0) { throw 'Compose startup failed. Check: docker compose logs model-init app' }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 5
            if ($health.status -eq 'ok' -and $health.service -eq 'ScholarFlow') {
                $ready = $true
                break
            }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { throw 'Service readiness timed out. Check: docker compose logs app' }
    & docker.exe compose ps -a
    Write-Host 'ScholarFlow is ready: http://localhost:8000'
    Write-Host 'Application logs: docker compose logs -f app'
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    Pop-Location
}
