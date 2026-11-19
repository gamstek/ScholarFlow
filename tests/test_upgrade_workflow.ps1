# Focused upgrade checks with a fake Docker command; no real services are touched.
$ErrorActionPreference = 'Stop'
$source = Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\upgrade_offline.ps1'
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) 'opencode'
if (-not (Test-Path -LiteralPath $temporaryRoot)) { throw 'Approved temporary directory is missing.' }
$work = Join-Path $temporaryRoot ('scholarflow-upgrade-check-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work -Force | Out-Null

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw "Assertion failed: $Message" }
}

function global:docker.exe {
    $a = @($args)
    $global:LASTEXITCODE = 0
    $s = $global:UpgradeFixture
    $s.calls.Add(($a -join ' ')) | Out-Null
    if ($a[0] -eq 'info') { return 'linux/x86_64' }
    if ($a[0] -eq 'load' -or $a[0] -eq 'tag') { return }
    if ($a[0] -eq 'image') { return 'linux/amd64' }
    if ($a[0] -eq 'inspect') {
        if ($a[2] -eq '{{.Image}}') { return 'sha256:old-image' }
        if ($s.failApp -and $s.currentImage -eq 'scholarflow:release-test') {
            return '{"Status":"exited","Health":{"Status":"unhealthy"}}'
        }
        return '{"Status":"running","Health":{"Status":"healthy"}}'
    }
    if ($a[0] -eq 'compose') {
        switch ($a[1]) {
            'config' {
                return (@{
                    name = 'upgrade-fixture'
                    services = @{
                        app = @{image = 'scholarflow:local'; volumes = @(@{type = 'bind'; target = '/app/data'; source = (Join-Path $s.install 'data')})}
                        db = @{environment = @{POSTGRES_USER = 'postgres'; POSTGRES_DB = 'scholarflow'}}
                    }
                } | ConvertTo-Json -Depth 8)
            }
            'ps' { return 'fixture-app' }
            'stop' { return }
            'up' {
                if ($a[-1] -eq 'app') {
                    $s.currentImage = $env:SCHOLARFLOW_IMAGE
                    $s.startedImages.Add($env:SCHOLARFLOW_IMAGE) | Out-Null
                }
                return
            }
            'exec' {
                if ($a -contains 'pg_dump' -and $s.failBackup) { $global:LASTEXITCODE = 1 }
                return
            }
            'cp' { [IO.File]::WriteAllText($a[-1], 'database snapshot'); return }
        }
    }
    throw ('Unexpected fake Docker command: ' + ($a -join ' '))
}

try {
    foreach ($case in @('success', 'failed-backup', 'failed-app', 'bad-checksum')) {
        $caseRoot = Join-Path $work $case
        $install = Join-Path $caseRoot 'original installation'
        $package = Join-Path $caseRoot 'upgrade package'
        New-Item -ItemType Directory -Path $install, $package, (Join-Path $install 'data'), (Join-Path $install 'embedding\bge-m3') -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination (Join-Path $package 'upgrade.ps1')
        $originalEnv = "CLOUD_API_KEY=fixture-key-to-preserve`r`nSCHOLARFLOW_IMAGE=scholarflow:local`r`nCUSTOM_SETTING=keep-me`r`n"
        [IO.File]::WriteAllText((Join-Path $install '.env'), $originalEnv)
        [IO.File]::WriteAllText((Join-Path $install 'compose.yaml'), 'original compose configuration')
        [IO.File]::WriteAllText((Join-Path $install 'data\paper.txt'), 'existing paper and index data')
        [IO.File]::WriteAllText((Join-Path $install 'embedding\bge-m3\fixture'), 'existing model')
        [IO.File]::WriteAllText((Join-Path $package 'images.tar'), 'image fixture')
        foreach ($file in @('start.bat', 'stop.bat')) {
            [IO.File]::WriteAllText((Join-Path $install $file), ('old ' + $file))
            [IO.File]::WriteAllText((Join-Path $package $file), ('new ' + $file))
        }
        $hash = (Get-FileHash -LiteralPath (Join-Path $package 'images.tar') -Algorithm SHA256).Hash
        if ($case -eq 'bad-checksum') { $hash = 'incorrect' }
        $manifest = @{format_version = 1; kind = 'application'; image = 'scholarflow:release-test'; version = 'test'; images_sha256 = $hash}
        [IO.File]::WriteAllText((Join-Path $package 'upgrade.json'), ($manifest | ConvertTo-Json))
        $global:UpgradeFixture = @{
            install = $install; calls = (New-Object 'Collections.Generic.List[string]')
            startedImages = (New-Object 'Collections.Generic.List[string]')
            currentImage = 'scholarflow:local'; failBackup = ($case -eq 'failed-backup'); failApp = ($case -eq 'failed-app')
        }
        & (Join-Path $package 'upgrade.ps1') -InstallDirectory $install
        $code = $LASTEXITCODE
        $settings = [IO.File]::ReadAllText((Join-Path $install '.env'))
        Assert-True ([IO.File]::ReadAllText((Join-Path $install 'data\paper.txt')) -eq 'existing paper and index data') "$case preserved data"
        Assert-True ([IO.File]::ReadAllText((Join-Path $install 'embedding\bge-m3\fixture')) -eq 'existing model') "$case preserved model"
        Assert-True ([IO.File]::ReadAllText((Join-Path $install 'compose.yaml')) -eq 'original compose configuration') "$case preserved Compose"
        if ($case -eq 'success') {
            Assert-True ($code -eq 0) 'successful upgrade returned zero'
            Assert-True ($settings.Contains('CLOUD_API_KEY=fixture-key-to-preserve') -and $settings.Contains('CUSTOM_SETTING=keep-me')) 'user settings preserved'
            Assert-True ($settings.Contains('SCHOLARFLOW_IMAGE=scholarflow:release-test')) 'new image persisted'
            $backup = @(Get-ChildItem -LiteralPath (Join-Path $install 'backups') -Directory)[0].FullName
            Assert-True ([IO.File]::ReadAllText((Join-Path $backup '.env')) -eq $originalEnv) 'original environment backed up'
            Assert-True ((Get-Item -LiteralPath (Join-Path $backup 'postgres.dump')).Length -gt 0) 'database backed up'
            Assert-True ([IO.File]::ReadAllText((Join-Path $backup 'data\paper.txt')) -eq 'existing paper and index data') 'files backed up'
            foreach ($file in @('start.bat', 'stop.bat')) {
                Assert-True ([IO.File]::ReadAllText((Join-Path $install $file)) -eq ('new ' + $file)) 'control script installed'
                Assert-True ([IO.File]::ReadAllText((Join-Path $backup ('control-scripts\' + $file))) -eq ('old ' + $file)) 'old control script backed up'
            }
        } else {
            Assert-True ($code -ne 0) "$case rejected"
            Assert-True ($settings -eq $originalEnv) "$case preserved original environment"
            foreach ($file in @('start.bat', 'stop.bat')) {
                Assert-True ([IO.File]::ReadAllText((Join-Path $install $file)) -eq ('old ' + $file)) "$case preserved control scripts"
            }
            if ($case -eq 'bad-checksum') { Assert-True ($global:UpgradeFixture.calls.Count -eq 0) 'bad archive never touched Docker' }
            else { Assert-True ($global:UpgradeFixture.currentImage -like 'scholarflow:rollback-*') "$case requested old application restart" }
            if ($case -eq 'failed-backup') {
                Assert-True (-not ($global:UpgradeFixture.startedImages -contains 'scholarflow:release-test')) 'failed backup did not start a release'
            }
        }
        Assert-True (-not ($global:UpgradeFixture.calls -match '^compose down|\bvolume rm\b|\bpg_restore\b')) "$case never removed volumes or restored databases"
        Write-Host "PASS: $case"
    }
    Write-Host 'All 4 focused upgrade checks passed. Real Docker services were not accessed.'
} finally {
    Remove-Item -LiteralPath 'Function:\docker.exe' -ErrorAction SilentlyContinue
    Remove-Variable -Name UpgradeFixture -Scope Global -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
}
