#requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$Wheel,
    [Parameter(Mandatory = $true)][string]$Python
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$Wheel = (Resolve-Path -LiteralPath $Wheel).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ('tapl Windows smoke ' + [guid]::NewGuid().ToString('N'))
$originalUserPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$environmentNames = @('PATH', 'HOME', 'USERPROFILE', 'CODEX_HOME', 'TAPL_INSTALL_ROOT', 'TAPL_BIN_DIR', 'TAPL_INSTALL_MANIFEST_URL', 'TAPL_INSTALL_METADATA', 'TAPL_PYTHON')
$savedEnvironment = @{}
foreach ($name in $environmentNames) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$server = $null

function Assert-Smoke {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function Invoke-Installer {
    param([string[]]$InstallerArguments = @())
    # Exercise the public CMD wrapper and its argument/exit-code forwarding.
    & (Join-Path $repoRoot 'install.cmd') @InstallerArguments
    Assert-Smoke ($LASTEXITCODE -eq 0) "install.cmd failed: $InstallerArguments"
}

function Get-InstallMetadata {
    return Get-Content -Raw -LiteralPath (Join-Path $env:TAPL_INSTALL_ROOT 'install.json') | ConvertFrom-Json
}

function Write-Manifest {
    param([string]$WheelPath)
    $version = & $Python -c "import sys,zipfile,email; z=zipfile.ZipFile(sys.argv[1]); p=next(n for n in z.namelist() if n.endswith('.dist-info/METADATA')); print(email.message_from_bytes(z.read(p))['Version'])" $WheelPath
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Could not read actual wheel metadata.'
    $manifest = @{
        schema_version = 1
        version = $version.Trim()
        wheel = @{
            url = "$baseUrl/$([IO.Path]::GetFileName($WheelPath))"
            sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $WheelPath).Hash.ToLowerInvariant()
        }
    }
    $json = ($manifest | ConvertTo-Json -Depth 4) + "`n"
    [IO.File]::WriteAllText((Join-Path $fixtures 'taplctl-install-manifest.json'), $json, [Text.UTF8Encoding]::new($false))
    return $manifest.version
}

try {
    New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
    $fixtures = Join-Path $temporaryRoot 'served wheels'
    New-Item -ItemType Directory -Path $fixtures | Out-Null
    Copy-Item -LiteralPath $Wheel -Destination $fixtures
    $firstWheel = Join-Path $fixtures ([IO.Path]::GetFileName($Wheel))
    $env:HOME = Join-Path $temporaryRoot 'user home'
    $env:USERPROFILE = $env:HOME
    $env:CODEX_HOME = Join-Path $env:HOME '.codex'
    $env:TAPL_INSTALL_ROOT = Join-Path $temporaryRoot 'managed install'
    $env:TAPL_BIN_DIR = Join-Path $temporaryRoot 'user bin'
    $env:TAPL_INSTALL_METADATA = Join-Path $env:TAPL_INSTALL_ROOT 'install.json'
    $env:TAPL_PYTHON = $Python
    New-Item -ItemType Directory -Path (Join-Path $env:HOME '.tapl'), $env:TAPL_INSTALL_ROOT, $env:TAPL_BIN_DIR | Out-Null
    $dataFile = Join-Path $env:HOME '.tapl\retained-data.txt'
    $unrelatedRoot = Join-Path $env:TAPL_INSTALL_ROOT 'unrelated.txt'
    $unrelatedBin = Join-Path $env:TAPL_BIN_DIR 'unrelated.cmd'
    foreach ($path in @($dataFile, $unrelatedRoot, $unrelatedBin)) { [IO.File]::WriteAllText($path, 'keep me') }

    $serverScript = Join-Path $temporaryRoot 'serve.py'
    $portFile = Join-Path $temporaryRoot 'port.txt'
    @'
import http.server
from pathlib import Path
import sys
server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), http.server.SimpleHTTPRequestHandler)
Path(sys.argv[1]).write_text(str(server.server_port), encoding='ascii')
server.serve_forever()
'@ | Set-Content -Encoding ASCII -LiteralPath $serverScript
    $server = Start-Process -FilePath $Python -ArgumentList ('"{0}" "{1}"' -f $serverScript, $portFile) -WorkingDirectory $fixtures -PassThru -WindowStyle Hidden
    for ($attempt = 0; $attempt -lt 100 -and -not (Test-Path -LiteralPath $portFile); $attempt++) {
        Start-Sleep -Milliseconds 100
        if ($server.HasExited) { throw 'Local wheel HTTP server exited early.' }
    }
    Assert-Smoke (Test-Path -LiteralPath $portFile) 'Local wheel HTTP server did not start.'
    $baseUrl = 'http://127.0.0.1:' + (Get-Content -Raw -LiteralPath $portFile).Trim()
    $env:TAPL_INSTALL_MANIFEST_URL = "$baseUrl/taplctl-install-manifest.json"
    $firstVersion = Write-Manifest $firstWheel
    Invoke-Installer
    $first = Get-InstallMetadata
    Assert-Smoke ($first.version -eq $firstVersion) 'Initial actual wheel was not activated.'
    $installedPython = Join-Path $first.venv 'Scripts\python.exe'
    $requestedVersion = & $Python -c 'import sys; print(sys.version_info[:2])'
    $installedVersion = & $installedPython -c 'import sys; print(sys.version_info[:2])'
    Assert-Smoke ($requestedVersion -eq $installedVersion) 'Installer selected a different Python than the CI matrix.'
    & $installedPython (Join-Path $PSScriptRoot 'windows_runtime_smoke.py')
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Installed wheel CLI/MCP/hook smoke failed.'

    # Build a newer, complete wheel from the same source to test real updater activation.
    $buildSource = Join-Path $temporaryRoot 'next source'
    @'
import re, shutil, sys
from pathlib import Path
source, target, current = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
shutil.copytree(source, target, ignore=shutil.ignore_patterns('.venv', '__pycache__', '*.egg-info', 'dist'))
major, minor, patch = map(int, re.match(r'(\d+)\.(\d+)\.(\d+)', current).groups())
project = target / 'pyproject.toml'
text, count = re.subn(r'(?m)^version = "[^"]+"$', f'version = "{major}.{minor}.{patch + 1}"', project.read_text(), count=1)
assert count == 1
project.write_text(text)
'@ | & $Python - (Join-Path $repoRoot 'tapl') $buildSource $firstVersion
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Could not prepare next actual wheel source.'
    & $Python -m pip wheel --no-deps --wheel-dir $fixtures $buildSource
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Could not build next actual wheel.'
    $nextWheels = @(Get-ChildItem -LiteralPath $fixtures -Filter '*.whl' | Where-Object { $_.FullName -ne $firstWheel })
    Assert-Smoke ($nextWheels.Count -eq 1) 'Expected exactly one next actual wheel.'
    $nextVersion = Write-Manifest $nextWheels[0].FullName
    $launcher = Join-Path $env:TAPL_BIN_DIR 'taplctl.cmd'
    & $launcher update --check
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Actual wheel update check failed.'
    & $launcher update
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Actual wheel update failed.'
    $updated = Get-InstallMetadata
    Assert-Smoke ($updated.version -eq $nextVersion -and $updated.venv -ne $first.venv) 'Updater did not activate the next actual wheel.'
    & (Join-Path $updated.venv 'Scripts\python.exe') (Join-Path $PSScriptRoot 'windows_runtime_smoke.py')
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Updated wheel CLI/MCP/hook smoke failed.'

    # Reinstall must remember the selected manifest even without the environment override.
    Remove-Item Env:TAPL_INSTALL_MANIFEST_URL
    Invoke-Installer -InstallerArguments @('-Reinstall')
    $reinstalled = Get-InstallMetadata
    Assert-Smoke ($reinstalled.version -eq $nextVersion -and $reinstalled.venv -ne $updated.venv) 'Reinstall did not rebuild the selected release.'
    & $launcher --version
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Reinstalled launcher failed.'
    Invoke-Installer -InstallerArguments @('-Uninstall')
    Assert-Smoke (-not (Test-Path -LiteralPath $env:TAPL_INSTALL_METADATA)) 'Uninstall retained managed metadata.'
    Assert-Smoke (-not (Test-Path -LiteralPath $launcher)) 'Uninstall retained its launcher.'
    Assert-Smoke (-not (Test-Path -LiteralPath $reinstalled.venv)) 'Uninstall retained its managed environment.'
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    Assert-Smoke (-not (@($userPath -split ';') -contains $env:TAPL_BIN_DIR)) 'Uninstall retained its user PATH entry.'
    foreach ($path in @($dataFile, $unrelatedRoot, $unrelatedBin)) {
        Assert-Smoke ((Get-Content -Raw -LiteralPath $path) -eq 'keep me') "Uninstall changed unrelated data: $path"
    }
    # A clean install after removal must work with the same preserved user data.
    $env:TAPL_INSTALL_MANIFEST_URL = "$baseUrl/taplctl-install-manifest.json"
    Invoke-Installer
    $fresh = Get-InstallMetadata
    Assert-Smoke ($fresh.version -eq $nextVersion) 'Fresh installation after removal selected the wrong release.'
    & $launcher --version
    Assert-Smoke ($LASTEXITCODE -eq 0) 'Fresh launcher after removal failed.'
    Invoke-Installer -InstallerArguments @('-Uninstall')
    Assert-Smoke (-not (Test-Path -LiteralPath $env:TAPL_INSTALL_METADATA)) 'Final cleanup retained managed metadata.'
    Write-Host 'Actual Windows wheel lifecycle and runtime smoke passed.'
}
finally {
    if ($null -ne $server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    [Environment]::SetEnvironmentVariable('Path', $originalUserPath, 'User')
    foreach ($name in $environmentNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    if (Test-Path -LiteralPath $temporaryRoot) { Remove-Item -LiteralPath $temporaryRoot -Recurse -Force }
}
