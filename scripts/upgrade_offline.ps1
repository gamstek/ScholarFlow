# Upgrade an existing Windows deployment while preserving its data and settings.
[CmdletBinding()]
param([string]$InstallDirectory = '')

$ErrorActionPreference = 'Stop'
$package = $PSScriptRoot
$backup = $null
$record = $null
$appStopped = $false
$environmentChanged = $false
$locationChanged = $false
$lock = $null
$controlScripts = @('start.bat', 'stop.bat')
$previousControls = @{}
$controlsChanged = $false
$previousImageOverride = [Environment]::GetEnvironmentVariable('SCHOLARFLOW_IMAGE', 'Process')

function Invoke-Docker {
    param([string[]]$Arguments)
    $output = & docker.exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: docker $($Arguments -join ' ')" }
    return $output
}

function Write-Json {
    param([string]$Path, $Value)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}

try {
    $manifest = Get-Content -LiteralPath (Join-Path $package 'upgrade.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.format_version -ne 1 -or $manifest.kind -ne 'application') {
        throw 'Unsupported upgrade package format.'
    }
    if ($manifest.image -notmatch '^scholarflow:release-[a-zA-Z0-9_.-]+$') {
        throw 'Invalid release image reference.'
    }
    $imageArchive = Join-Path $package 'images.tar'
    $actualHash = (Get-FileHash -LiteralPath $imageArchive -Algorithm SHA256).Hash
    if ($actualHash -ne $manifest.images_sha256) { throw 'Image archive checksum mismatch. Transfer the package again.' }
    foreach ($file in $controlScripts) {
        if (-not (Test-Path -LiteralPath (Join-Path $package $file) -PathType Leaf)) { throw "Upgrade package is missing $file" }
    }

    if (-not $InstallDirectory) {
        Add-Type -AssemblyName System.Windows.Forms
        $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
        try {
            $dialog.Description = 'Select the ORIGINAL ScholarFlow deployment folder containing compose.yaml and .env.'
            $dialog.ShowNewFolderButton = $false
            if ($dialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Upgrade cancelled.' }
            $InstallDirectory = $dialog.SelectedPath
        } finally { $dialog.Dispose() }
    }
    $InstallDirectory = (Resolve-Path -LiteralPath $InstallDirectory).Path
    foreach ($required in @('compose.yaml', '.env')) {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallDirectory $required) -PathType Leaf)) {
            throw "Select the original deployment folder; $required is missing."
        }
    }
    $lock = [IO.File]::Open((Join-Path $InstallDirectory '.scholarflow-upgrade.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    Push-Location $InstallDirectory
    $locationChanged = $true
    # Existing .env controls project settings; ignore an inherited image override.
    [Environment]::SetEnvironmentVariable('SCHOLARFLOW_IMAGE', $null, 'Process')
    $engine = (Invoke-Docker @('info', '--format', '{{.OSType}}/{{.Architecture}}')).Trim()
    if ($engine -notmatch '^linux/(amd64|x86_64)$') { throw 'Docker Desktop must run Linux amd64 containers.' }
    $config = (Invoke-Docker @('compose', 'config', '--format', 'json')) | ConvertFrom-Json
    $dataMount = @($config.services.app.volumes | Where-Object { $_.target -eq '/app/data' })
    if ($dataMount.Count -ne 1 -or $dataMount[0].type -ne 'bind') {
        throw 'This updater requires the existing /app/data bind mount. Custom data volumes need a separate migration.'
    }
    $dataPath = $dataMount[0].source
    if (-not (Test-Path -LiteralPath $dataPath -PathType Container)) { throw 'Existing application data directory is missing.' }
    $dataRoot = [IO.Path]::GetFullPath($dataPath).TrimEnd('\', '/')
    $backupRoot = [IO.Path]::GetFullPath((Join-Path $InstallDirectory 'backups'))
    if ($backupRoot.Equals($dataRoot, [StringComparison]::OrdinalIgnoreCase) -or $backupRoot.StartsWith($dataRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The backup directory would be inside the data mount. This custom mount needs a separate backup location.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $InstallDirectory 'embedding\bge-m3') -PathType Container)) {
        throw 'Existing BGE-M3 model directory is missing. Use the original deployment folder.'
    }

    $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
    $rollbackImage = 'scholarflow:rollback-' + $stamp
    $appId = @(Invoke-Docker @('compose', 'ps', '--all', '--quiet', 'app'))
    if ($appId.Count -gt 1) { throw 'Multiple application containers are not supported by this updater.' }
    $oldImage = if ($appId.Count -eq 1 -and $appId[0]) {
        (Invoke-Docker @('inspect', '--format', '{{.Image}}', $appId[0])).Trim()
    } else {
        (Invoke-Docker @('image', 'inspect', $config.services.app.image, '--format', '{{.Id}}')).Trim()
    }
    Invoke-Docker @('tag', $oldImage, $rollbackImage)
    $backup = Join-Path $InstallDirectory ('backups\upgrade-' + $stamp)
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Item -LiteralPath '.env' -Destination (Join-Path $backup '.env')
    $controlBackup = Join-Path $backup 'control-scripts'
    New-Item -ItemType Directory -Path $controlBackup -Force | Out-Null
    foreach ($file in $controlScripts) {
        $previousControls[$file] = Test-Path -LiteralPath (Join-Path $InstallDirectory $file)
        if ($previousControls[$file]) { Copy-Item -LiteralPath (Join-Path $InstallDirectory $file) -Destination $controlBackup }
    }
    foreach ($file in Get-ChildItem -LiteralPath $InstallDirectory -File | Where-Object { $_.Name -match '^compose.*\.ya?ml$' }) {
        Copy-Item -LiteralPath $file.FullName -Destination $backup
    }
    $record = [ordered]@{
        version = $manifest.version; install_directory = $InstallDirectory
        project = $config.name; data_source = $dataPath
        previous_image = $oldImage; rollback_image = $rollbackImage
        new_image = $manifest.image; backup_complete = $false; status = 'preparing'
        previous_control_scripts = $previousControls
    }
    Write-Json (Join-Path $backup 'upgrade-record.json') $record

    Write-Host 'Importing the new application image. Existing services are still running...'
    Invoke-Docker @('load', '--input', $imageArchive)
    $platform = (Invoke-Docker @('image', 'inspect', $manifest.image, '--format', '{{.Os}}/{{.Architecture}}')).Trim()
    if ($platform -ne 'linux/amd64') { throw 'The release image platform is not linux/amd64.' }

    Write-Host 'Stopping the application briefly to take a consistent backup...'
    Invoke-Docker @('compose', 'stop', 'app')
    $appStopped = $true
    Invoke-Docker @('compose', 'up', '-d', '--pull', 'never', '--no-deps', 'db')
    $dbUser = $config.services.db.environment.POSTGRES_USER
    $dbName = $config.services.db.environment.POSTGRES_DB
    if (-not $dbUser -or -not $dbName) { throw 'Cannot determine the existing PostgreSQL user/database.' }
    $dbReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        & docker.exe compose exec -T db pg_isready -U $dbUser -d $dbName > $null 2>&1
        if ($LASTEXITCODE -eq 0) { $dbReady = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $dbReady) { throw 'The existing database did not become ready.' }
    $dump = '/tmp/scholarflow-upgrade-' + $stamp + '.dump'
    Invoke-Docker @('compose', 'exec', '-T', 'db', 'pg_dump', '-U', $dbUser, '-d', $dbName, '--format=custom', '--file', $dump)
    Invoke-Docker @('compose', 'cp', ('db:' + $dump), (Join-Path $backup 'postgres.dump'))
    $dumpFile = Get-Item -LiteralPath (Join-Path $backup 'postgres.dump')
    if ($dumpFile.Length -eq 0) { throw 'The database backup is empty.' }
    Invoke-Docker @('compose', 'exec', '-T', 'db', 'rm', '-f', $dump)
    Copy-Item -LiteralPath $dataPath -Destination (Join-Path $backup 'data') -Recurse -Force
    $record.backup_complete = $true
    $record.status = 'backed-up'
    Write-Json (Join-Path $backup 'upgrade-record.json') $record
    Write-Host "Backup completed: $backup"

    # Preserve every user setting except the application image reference.
    $envFile = Join-Path $InstallDirectory '.env'
    $settings = [IO.File]::ReadAllText($envFile)
    $imageLine = 'SCHOLARFLOW_IMAGE=' + $manifest.image
    $pattern = '(?m)^[ \t]*(?:export[ \t]+)?SCHOLARFLOW_IMAGE[ \t]*=[^\r\n]*'
    if ([regex]::IsMatch($settings, $pattern)) { $settings = [regex]::Replace($settings, $pattern, $imageLine) }
    else { $settings = $settings.TrimEnd() + "`r`n" + $imageLine + "`r`n" }
    $environmentChanged = $true
    [IO.File]::WriteAllText($envFile, $settings, (New-Object Text.UTF8Encoding($false)))
    $env:SCHOLARFLOW_IMAGE = $manifest.image
    Invoke-Docker @('compose', 'up', '-d', '--pull', 'never', '--no-deps', '--force-recreate', 'app')
    $newApp = (Invoke-Docker @('compose', 'ps', '--quiet', 'app')).Trim()
    $healthy = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        $state = (Invoke-Docker @('inspect', '--format', '{{json .State}}', $newApp)) | ConvertFrom-Json
        if ($state.Status -ne 'running') { throw 'The new application container stopped during startup.' }
        if ($state.Health.Status -eq 'healthy') { $healthy = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { throw 'The new application did not become healthy.' }
    $controlsChanged = $true
    foreach ($file in $controlScripts) {
        Copy-Item -LiteralPath (Join-Path $package $file) -Destination (Join-Path $InstallDirectory $file) -Force
    }
    $record.status = 'success'
    Write-Json (Join-Path $backup 'upgrade-record.json') $record
    Write-Host "[OK] Upgraded to $($manifest.version). Existing data, model and settings were preserved."
    Write-Host "Backup: $backup"
    Write-Host "Previous image retained: $rollbackImage"
} catch {
    Write-Host ('[ERROR] ' + $_.Exception.Message) -ForegroundColor Red
    if ($controlsChanged) {
        foreach ($file in $controlScripts) {
            try {
                if ($previousControls[$file]) {
                    Copy-Item -LiteralPath (Join-Path $controlBackup $file) -Destination (Join-Path $InstallDirectory $file) -Force
                } else {
                    Remove-Item -LiteralPath (Join-Path $InstallDirectory $file) -Force -ErrorAction SilentlyContinue
                }
            } catch { Write-Host "[ERROR] Could not restore $file; see the backup folder." }
        }
    }
    if ($environmentChanged -and $backup) {
        try { Copy-Item -LiteralPath (Join-Path $backup '.env') -Destination (Join-Path $InstallDirectory '.env') -Force }
        catch { Write-Host '[ERROR] Could not restore .env automatically; the original copy is in the backup folder.' }
    }
    if ($record -and $backup) {
        $record.status = 'failed'
        try { Write-Json (Join-Path $backup 'upgrade-record.json') $record }
        catch { Write-Host '[ERROR] Could not update the recovery record.' }
    }
    if ($appStopped) {
        Write-Host 'Attempting to restart the previous application image...'
        $env:SCHOLARFLOW_IMAGE = $rollbackImage
        & docker.exe compose up -d --pull never --no-deps --force-recreate app
        if ($LASTEXITCODE -ne 0) { Write-Host '[ERROR] Previous application restart failed; contact the maintainer.' }
        else { Write-Host 'Previous application restart requested. Database/file snapshots are retained for recovery.' }
    }
    if ($backup) { Write-Host "Backup/recovery details: $backup" }
    exit 1
} finally {
    [Environment]::SetEnvironmentVariable('SCHOLARFLOW_IMAGE', $previousImageOverride, 'Process')
    if ($locationChanged) { Pop-Location }
    if ($lock) { $lock.Dispose() }
}
