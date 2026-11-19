# Package an existing local application image; no build, CI, model or DB image.
[CmdletBinding()]
param(
    [string]$Image = 'scholarflow:local',
    [string]$Version = '',
    [string]$OutputDirectory = ''
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $root 'dist' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath (Split-Path -Parent $OutputDirectory))) { throw 'Output parent directory does not exist.' }
foreach ($command in @('docker.exe', 'tar.exe')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command is required." }
}
$info = & docker.exe image inspect $Image --format '{{.Os}}/{{.Architecture}}'
if ($LASTEXITCODE -ne 0 -or $info.Trim() -ne 'linux/amd64') { throw 'A local linux/amd64 application image is required.' }
$sourceId = (& docker.exe image inspect $Image --format '{{.Id}}').Trim()
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the local application image.' }
$release = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $sourceId.Substring(7, 8)
if (-not $Version) { $Version = $release }
$releaseImage = 'scholarflow:release-' + $release
& docker.exe tag $Image $releaseImage
if ($LASTEXITCODE -ne 0) { throw 'Cannot create a release image tag.' }
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$staging = Join-Path $OutputDirectory ('.upgrade-stage-' + [guid]::NewGuid().ToString('N'))
$bundle = Join-Path $staging 'scholarflow-upgrade'
$archive = Join-Path $OutputDirectory ('scholarflow-upgrade-windows-amd64-' + $release + '.zip')
New-Item -ItemType Directory -Path $bundle -Force | Out-Null
try {
    Copy-Item -LiteralPath (Join-Path $root 'scripts\upgrade_offline.ps1') -Destination (Join-Path $bundle 'upgrade.ps1')
    Copy-Item -LiteralPath (Join-Path $root 'scripts\upgrade_offline.bat') -Destination (Join-Path $bundle 'upgrade.bat')
    Copy-Item -LiteralPath (Join-Path $root 'scripts\start_offline.bat') -Destination (Join-Path $bundle 'start.bat')
    Copy-Item -LiteralPath (Join-Path $root 'scripts\stop_offline.bat') -Destination (Join-Path $bundle 'stop.bat')
    Copy-Item -LiteralPath (Join-Path $root 'docs\upgrade.md') -Destination (Join-Path $bundle 'README.md')
    Write-Host "Exporting existing local image: $Image -> $releaseImage"
    & docker.exe image save --output (Join-Path $bundle 'images.tar') $releaseImage
    if ($LASTEXITCODE -ne 0) { throw 'Application image export failed.' }
    $imageHash = (Get-FileHash -LiteralPath (Join-Path $bundle 'images.tar') -Algorithm SHA256).Hash.ToLowerInvariant()
    $manifest = [ordered]@{
        format_version = 1; kind = 'application'; version = $Version
        image = $releaseImage; source_image_id = $sourceId; images_sha256 = $imageHash
    }
    [IO.File]::WriteAllText((Join-Path $bundle 'upgrade.json'), ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
    Write-Host 'Compressing Windows application upgrade package...'
    & tar.exe -a -cf $archive -C $staging 'scholarflow-upgrade'
    if ($LASTEXITCODE -ne 0) { throw 'Upgrade archive creation failed.' }
    $entries = @(& tar.exe -tf $archive)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the upgrade archive.' }
    foreach ($file in @('upgrade.bat', 'upgrade.ps1', 'upgrade.json', 'images.tar', 'README.md', 'start.bat', 'stop.bat')) {
        if ($entries -notcontains "scholarflow-upgrade/$file") { throw "Missing archive entry: $file" }
    }
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText(($archive + '.sha256'), "$hash  $([IO.Path]::GetFileName($archive))`n", (New-Object Text.UTF8Encoding($false)))
    Write-Host "Upgrade package: $archive"
    Write-Host ('Size: ' + [math]::Round((Get-Item -LiteralPath $archive).Length / 1GB, 2) + ' GiB')
    Write-Host "Version: $Version"
} finally {
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
}
