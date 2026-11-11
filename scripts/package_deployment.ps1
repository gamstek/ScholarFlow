# Export an offline bundle for Windows Docker Desktop or Linux amd64.
[CmdletBinding()]
param(
    [string]$Image = 'scholarflow:local',
    [string]$OutputDirectory = '',
    [ValidateSet('Windows', 'Linux')]
    [string]$Target = 'Windows'
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'dist' }
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath (Split-Path -Parent $OutputDirectory))) {
    throw 'The output parent directory must already exist.'
}

foreach ($command in @('docker.exe', 'tar.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is required." }
}
foreach ($name in @($Image, 'postgres:16-alpine')) {
    $info = & docker.exe image inspect $name --format '{{.Os}}/{{.Architecture}}'
    if ($LASTEXITCODE -ne 0) { throw "Local image not found: $name" }
    if ($info.Trim() -ne 'linux/amd64') { throw "Expected a linux/amd64 image: $name" }
}

$model = Join-Path $root 'embedding\bge-m3'
if (-not (Test-Path -LiteralPath (Join-Path $model '.scholarflow-model-ready.json'))) {
    throw 'Prepare and validate BGE-M3 with docker compose up -d before packaging.'
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$staging = Join-Path $OutputDirectory ('.stage-' + [guid]::NewGuid().ToString('N'))
$bundle = Join-Path $staging 'scholarflow-offline'
$extension = if ($Target -eq 'Windows') { '.zip' } else { '.tar.gz' }
$archive = Join-Path $OutputDirectory ('scholarflow-offline-' + $Target.ToLowerInvariant() + '-amd64-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + $extension)
New-Item -ItemType Directory -Path $bundle -Force | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $root 'compose.yaml') -Destination $bundle
    if ($Target -eq 'Windows') {
        Copy-Item -LiteralPath (Join-Path $root 'scripts\deploy_offline.ps1') -Destination (Join-Path $bundle 'deploy.ps1')
        Copy-Item -LiteralPath (Join-Path $root 'scripts\deploy_offline.bat') -Destination (Join-Path $bundle 'deploy.bat')
    } else {
        Copy-Item -LiteralPath (Join-Path $root 'scripts\deploy_offline.sh') -Destination (Join-Path $bundle 'deploy.sh')
    }
    Copy-Item -LiteralPath (Join-Path $root 'docs\offline-deployment.md') -Destination (Join-Path $bundle 'README.md')

    # Bundle a configuration template, never the live .env file.
    $template = Get-Content -LiteralPath (Join-Path $root '.env.example') -Raw -Encoding UTF8
    if ($template -match '(?m)^SCHOLARFLOW_IMAGE=') {
        $template = [regex]::Replace($template, '(?m)^SCHOLARFLOW_IMAGE=[^\r\n]*', ('SCHOLARFLOW_IMAGE=' + $Image))
    } else {
        $template = "SCHOLARFLOW_IMAGE=$Image`n" + $template
    }
    [System.IO.File]::WriteAllText((Join-Path $bundle '.env.example'), $template, (New-Object System.Text.UTF8Encoding($false)))

    $targetModel = Join-Path $bundle 'embedding\bge-m3'
    New-Item -ItemType Directory -Path $targetModel -Force | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $model -Force) {
        if ($entry.Name -ne '.cache') {
            Copy-Item -LiteralPath $entry.FullName -Destination $targetModel -Recurse -Force
        }
    }
    Write-Host 'Validating packaged model without network access...'
    & docker.exe run --rm --network none --mount "type=bind,source=$(Join-Path $bundle 'embedding'),target=/app/embedding" $Image python -m app.rag.prepare_model
    if ($LASTEXITCODE -ne 0) { throw 'Packaged model validation failed.' }

    Write-Host 'Exporting application and PostgreSQL images...'
    # Write binary data directly to disk; PowerShell 5.1 pipelines corrupt it.
    & docker.exe image save --output (Join-Path $bundle 'images.tar') $Image 'postgres:16-alpine'
    if ($LASTEXITCODE -ne 0) { throw 'Docker image export failed.' }

    Write-Host 'Compressing deployment bundle...'
    if ($Target -eq 'Windows') {
        # libarchive supports ZIP64 for the multi-GB images.tar and model files.
        & tar.exe -a -cf $archive -C $staging 'scholarflow-offline'
    } else {
        & tar.exe -czf $archive -C $staging 'scholarflow-offline'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
    $entries = @(& tar.exe -tf $archive)
    if ($LASTEXITCODE -ne 0) { throw 'Archive verification failed.' }
    $requiredFiles = @('images.tar', 'compose.yaml', '.env.example', 'embedding/bge-m3/pytorch_model.bin')
    if ($Target -eq 'Windows') { $requiredFiles += @('deploy.bat', 'deploy.ps1') }
    else { $requiredFiles += 'deploy.sh' }
    foreach ($required in $requiredFiles) {
        if ($entries -notcontains "scholarflow-offline/$required") { throw "Archive is missing $required" }
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [System.IO.File]::WriteAllText(($archive + '.sha256'), "$hash  $([System.IO.Path]::GetFileName($archive))`n", (New-Object System.Text.UTF8Encoding($false)))
    $size = [math]::Round((Get-Item -LiteralPath $archive).Length / 1GB, 2)
    Write-Host "Bundle: $archive"
    Write-Host "Size: $size GiB"
    Write-Host "SHA256: $hash"
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
