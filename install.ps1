#requires -Version 5.1

[CmdletBinding()]
param(
    [string]$Version,
    [switch]$Reinstall,
    [switch]$Uninstall
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$DefaultManifestUrl = "https://github.com/qkdxorjs1002/tapl/releases/latest/download/taplctl-install-manifest.json"
$Utf8NoBom = [System.Text.UTF8Encoding]::new($false, $true)
$WorkDirectory = $null
$CandidateVenv = $null
$CandidateIncomplete = $false
$LauncherTemporary = $null
$MetadataTemporary = $null

function Stop-Installer {
    param([Parameter(Mandatory = $true)][string]$Message)
    throw [System.InvalidOperationException]::new("taplctl installer: $Message")
}

function Write-InstallerNote {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Output "taplctl installer: $Message"
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or $Path.IndexOf([char]0) -ge 0) {
        Stop-Installer "an installation path is empty or invalid."
    }
    try {
        $fullPath = [System.IO.Path]::GetFullPath($Path)
        $pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
        while (
            $fullPath.Length -gt $pathRoot.Length -and
            ($fullPath.EndsWith("\") -or $fullPath.EndsWith("/"))
        ) {
            $fullPath = $fullPath.Substring(0, $fullPath.Length - 1)
        }
        return $fullPath
    }
    catch {
        Stop-Installer "an installation path is invalid."
    }
}

function Test-PathEqual {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
    return [string]::Equals($Left, $Right, [System.StringComparison]::OrdinalIgnoreCase)
}

function Test-StrictDescendant {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Parent
    )
    $prefix = $Parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    return $Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-PropertyValue {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        Stop-Installer "install metadata is missing a required field."
    }
    return $property.Value
}

function Test-SafeUrlText {
    param($Value)
    return (
        $Value -is [string] -and
        -not [string]::IsNullOrEmpty($Value) -and
        $Value.IndexOfAny([char[]]"`r`n`t") -lt 0
    )
}

function Read-Utf8Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        return $Utf8NoBom.GetString($bytes)
    }
    catch {
        Stop-Installer "could not read a required installer file as UTF-8."
    }
}

function Get-FileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = $null
    $sha256 = $null
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        $hashBytes = $sha256.ComputeHash($stream)
        return [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLowerInvariant()
    }
    finally {
        if ($null -ne $sha256) {
            $sha256.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function Test-ByteArrayEqual {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Left,
        [Parameter(Mandatory = $true)][byte[]]$Right
    )
    if ($Left.Length -ne $Right.Length) {
        return $false
    }
    for ($index = 0; $index -lt $Left.Length; $index++) {
        if ($Left[$index] -ne $Right[$index]) {
            return $false
        }
    }
    return $true
}

function Get-WindowsLauncherBytes {
    param([Parameter(Mandatory = $true)][string]$Command)

    if (
        $Command.IndexOf([char]34) -ge 0 -or
        $Command.IndexOf([char]13) -ge 0 -or
        $Command.IndexOf([char]10) -ge 0
    ) {
        Stop-Installer "the taplctl command path cannot be represented safely in a batch launcher."
    }
    $escaped = $Command.Replace("%", "%%")
    $text = "@echo off`r`nsetlocal DisableDelayedExpansion`r`n`"$escaped`" %*`r`n"
    return ,$Utf8NoBom.GetBytes($text)
}

function Test-RegularFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        return (
            -not $item.PSIsContainer -and
            (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0)
        )
    }
    catch {
        return $false
    }
}

function Assert-NoReparsePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $cursor = Get-NormalizedPath $Path
    while (-not [string]::IsNullOrEmpty($cursor)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force -ErrorAction Stop
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Stop-Installer "refusing a symlink or reparse installation path: $cursor"
            }
        }
        $parent = [System.IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Get-VenvInventory {
    param([Parameter(Mandatory = $true)][string]$Directory)
    Assert-NoReparsePath $Directory
    $files = [ordered]@{}
    $directories = @()
    # Walk one level at a time so a junction is rejected before traversal.
    $pending = [System.Collections.Generic.Queue[string]]::new()
    $pending.Enqueue($Directory)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        foreach ($item in @(Get-ChildItem -LiteralPath $current -Force -ErrorAction Stop)) {
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Stop-Installer "refusing a symlink or reparse entry in the managed environment."
            }
            $relative = $item.FullName.Substring($Directory.Length + 1)
            if ($item.PSIsContainer) {
                $directories += $relative
                $pending.Enqueue($item.FullName)
            }
            elseif ($relative -ne ".tapl-managed-venv.json") {
                $files[$relative] = Get-FileSha256 $item.FullName
            }
        }
    }
    return [ordered]@{ schema_version = 1; files = $files; directories = @($directories | Sort-Object) }
}

function Write-VenvInventory {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $inventory = Get-VenvInventory $Directory
    $text = ($inventory | ConvertTo-Json -Depth 4) + "`n"
    [System.IO.File]::WriteAllText((Join-Path $Directory ".tapl-managed-venv.json"), $text, $Utf8NoBom)
}

function Get-VerifiedVenvRemoval {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $inventoryPath = Join-Path $Directory ".tapl-managed-venv.json"
    if (-not (Test-RegularFile $inventoryPath)) {
        Stop-Installer "managed environment lacks an ownership inventory; run -Reinstall before -Uninstall."
    }
    $actual = Get-VenvInventory $Directory
    try {
        $expected = (Read-Utf8Text $inventoryPath) | ConvertFrom-Json
        if ((Get-PropertyValue $expected "schema_version") -ne 1) { throw "schema" }
        $expectedFiles = Get-PropertyValue $expected "files"
        if (-not ($expectedFiles -is [System.Management.Automation.PSCustomObject])) { throw "files" }
        $properties = @($expectedFiles.PSObject.Properties | Where-Object { -not (Test-ManagedBytecode $_.Name $expectedFiles) })
        $actualFileNames = @($actual.files.Keys | Where-Object { -not (Test-ManagedBytecode $_ $expectedFiles) })
        if ($properties.Count -ne $actualFileNames.Count) { throw "files" }
        foreach ($property in $properties) {
            if (-not $actual.files.Contains($property.Name) -or $actual.files[$property.Name] -cne $property.Value) { throw "file" }
        }
        $expectedDirectories = @((Get-PropertyValue $expected "directories") | Where-Object { [System.IO.Path]::GetFileName($_) -ne '__pycache__' } | Sort-Object)
        $actualDirectories = @($actual.directories | Where-Object { [System.IO.Path]::GetFileName($_) -ne '__pycache__' } | Sort-Object)
        if (($expectedDirectories -join "`n") -cne ($actualDirectories -join "`n")) { throw "directories" }
        foreach ($directory in $actual.directories) {
            if ([System.IO.Path]::GetFileName($directory) -eq '__pycache__') {
                $parent = [System.IO.Path]::GetDirectoryName($directory)
                if (-not [string]::IsNullOrEmpty($parent) -and $expectedDirectories -notcontains $parent) { throw "bytecode directory" }
            }
        }
    }
    catch {
        Stop-Installer "managed environment ownership is ambiguous or files changed; refusing to uninstall."
    }
    return @{ Directory = $Directory; Files = @($actual.files.Keys); Directories = @($actual.directories) }
}

function Test-ManagedBytecode {
    param([string]$Relative, $Files)
    if ([System.IO.Path]::GetFileName([System.IO.Path]::GetDirectoryName($Relative)) -ne '__pycache__') { return $false }
    $name = [System.IO.Path]::GetFileName($Relative)
    if ($name -cnotmatch '^(?<module>.+)\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc$') { return $false }
    $sourceName = $Matches['module'] + '.py'
    $sourceParent = [System.IO.Path]::GetDirectoryName([System.IO.Path]::GetDirectoryName($Relative))
    if ([string]::IsNullOrEmpty($sourceParent)) { $source = $sourceName }
    else { $source = Join-Path $sourceParent $sourceName }
    return ($null -ne $Files.PSObject.Properties[$source])
}

function Remove-VerifiedVenv {
    param([Parameter(Mandatory = $true)]$Plan)
    foreach ($relative in $Plan.Files) { [System.IO.File]::Delete((Join-Path $Plan.Directory $relative)) }
    [System.IO.File]::Delete((Join-Path $Plan.Directory ".tapl-managed-venv.json"))
    foreach ($relative in @($Plan.Directories | Sort-Object { $_.Length } -Descending)) {
        [System.IO.Directory]::Delete((Join-Path $Plan.Directory $relative), $false)
    }
    [System.IO.Directory]::Delete($Plan.Directory, $false)
}

function Assert-FileRemovalAccess {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        if (($item.Attributes -band [System.IO.FileAttributes]::ReadOnly) -ne 0) { throw "read-only file" }
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { throw "reparse file" }
        $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::None)
        $stream.Dispose()
    }
    catch {
        Stop-Installer "a managed file is read-only, in use or inaccessible: $Path ($($_.Exception.Message)); clear read-only attributes and close taplctl/Codex processes before retrying -Uninstall. No files were removed."
    }
}

function Assert-RemovalAccess {
    param([Parameter(Mandatory = $true)]$Plan)
    foreach ($relative in @($Plan.Files) + @('.tapl-managed-venv.json')) {
        Assert-FileRemovalAccess (Join-Path $Plan.Directory $relative)
    }
}

function Invoke-PythonCandidate {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [string[]]$PrefixArguments = @()
    )
    try {
        & $Executable @PrefixArguments -c "import sys, venv; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" *> $null
        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Find-Python {
    if (-not [string]::IsNullOrWhiteSpace($env:TAPL_PYTHON)) {
        if (-not (Test-RegularFile $env:TAPL_PYTHON) -or -not (Invoke-PythonCandidate -Executable $env:TAPL_PYTHON)) {
            Stop-Installer "TAPL_PYTHON must point to Python 3.11 or newer with the venv module."
        }
        return @{ Executable = $env:TAPL_PYTHON; PrefixArguments = [string[]]@() }
    }
    $candidates = @(
        @{ Name = "py.exe"; Prefix = @("-3") },
        @{ Name = "python.exe"; Prefix = @() },
        @{ Name = "python3.exe"; Prefix = @() },
        @{ Name = "python"; Prefix = @() },
        @{ Name = "python3"; Prefix = @() }
    )
    foreach ($candidate in $candidates) {
        $command = Get-Command $candidate.Name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command -and (Invoke-PythonCandidate -Executable $command.Source -PrefixArguments $candidate.Prefix)) {
            return @{
                Executable = $command.Source
                PrefixArguments = [string[]]$candidate.Prefix
            }
        }
    }
    Stop-Installer "Python 3.11 or newer with the venv module is required. Install Python, then run this installer again."
}

function Invoke-SelectedPython {
    param(
        [Parameter(Mandatory = $true)]$Python,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $executable = $Python.Executable
    $allArguments = @($Python.PrefixArguments) + $Arguments
    & $executable @allArguments | Out-Host
    return $LASTEXITCODE
}

function Get-ManagedInstallation {
    param(
        [Parameter(Mandatory = $true)][string]$MetadataPath,
        [Parameter(Mandatory = $true)][string]$ExpectedInstallRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedBinDirectory,
        [Parameter(Mandatory = $true)][string]$ExpectedVersionsDirectory,
        [Parameter(Mandatory = $true)][string]$ExpectedLauncher
    )

    if (-not (Test-RegularFile -Path $MetadataPath)) {
        Stop-Installer "$MetadataPath exists but is not valid schema 1 PowerShell install metadata; refusing to overwrite it."
    }
    try {
        $metadataBytes = [System.IO.File]::ReadAllBytes($MetadataPath)
        $metadata = $Utf8NoBom.GetString($metadataBytes) | ConvertFrom-Json
    }
    catch {
        Stop-Installer "$MetadataPath exists but is not valid schema 1 PowerShell install metadata; refusing to overwrite it."
    }

    try {
        if (-not ($metadata -is [System.Management.Automation.PSCustomObject])) { throw "root" }
        $schema = Get-PropertyValue $metadata "schema_version"
        if (($schema -is [bool]) -or $schema -ne 1) { throw "schema" }
        if ((Get-PropertyValue $metadata "method") -ne "powershell") { throw "method" }
        $pathOwnership = $metadata.PSObject.Properties['added_to_user_path']
        if ($null -ne $pathOwnership -and -not ($pathOwnership.Value -is [bool])) { throw "path ownership" }

        $installRootValue = Get-PropertyValue $metadata "install_root"
        $binDirectoryValue = Get-PropertyValue $metadata "bin_dir"
        $venvValue = Get-PropertyValue $metadata "venv"
        $executableValue = Get-PropertyValue $metadata "executable"
        foreach ($value in @($installRootValue, $binDirectoryValue, $venvValue, $executableValue)) {
            if (-not ($value -is [string]) -or [string]::IsNullOrEmpty($value)) { throw "path" }
        }

        $normalizedInstallRoot = Get-NormalizedPath $installRootValue
        $normalizedBinDirectory = Get-NormalizedPath $binDirectoryValue
        $normalizedVenv = Get-NormalizedPath $venvValue
        $normalizedExecutable = Get-NormalizedPath $executableValue
        if (-not (Test-PathEqual $installRootValue $normalizedInstallRoot)) { throw "install_root" }
        if (-not (Test-PathEqual $binDirectoryValue $normalizedBinDirectory)) { throw "bin_dir" }
        if (-not (Test-PathEqual $venvValue $normalizedVenv)) { throw "venv" }
        if (-not (Test-PathEqual $executableValue $normalizedExecutable)) { throw "executable" }
        if (-not (Test-PathEqual $normalizedInstallRoot $ExpectedInstallRoot)) { throw "install_root" }
        if (-not (Test-PathEqual $normalizedBinDirectory $ExpectedBinDirectory)) { throw "bin_dir" }
        if (-not (Test-PathEqual $normalizedExecutable $ExpectedLauncher)) { throw "executable" }
        if (-not (Test-StrictDescendant $normalizedVenv $ExpectedVersionsDirectory)) { throw "venv" }
        if (-not (Test-PathEqual ([System.IO.Path]::GetDirectoryName($normalizedVenv)) $ExpectedVersionsDirectory)) { throw "venv" }
        Assert-NoReparsePath $normalizedVenv
        Assert-NoReparsePath (Join-Path $normalizedVenv "Scripts")

        $manifestUrlValue = Get-PropertyValue $metadata "manifest_url"
        $wheelUrlValue = Get-PropertyValue $metadata "wheel_url"
        $versionValue = Get-PropertyValue $metadata "version"
        $shaValue = Get-PropertyValue $metadata "wheel_sha256"
        if (-not (Test-SafeUrlText $manifestUrlValue)) { throw "manifest_url" }
        if (-not (Test-SafeUrlText $wheelUrlValue)) { throw "wheel_url" }
        if (-not ($versionValue -is [string]) -or $versionValue -cnotmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?$') { throw "version" }
        if (-not ($shaValue -is [string]) -or $shaValue -notmatch '^[0-9a-fA-F]{64}$') { throw "sha" }

        $pythonCommand = Join-Path (Join-Path $normalizedVenv "Scripts") "python.exe"
        $taplCommand = Join-Path (Join-Path $normalizedVenv "Scripts") "taplctl.exe"
        if (-not $Reinstall -and -not $Uninstall -and (-not (Test-RegularFile $pythonCommand) -or -not (Test-RegularFile $taplCommand))) { throw "command" }
        if (-not (Test-RegularFile $ExpectedLauncher)) { throw "launcher" }
        $expectedLauncherBytes = Get-WindowsLauncherBytes -Command $taplCommand
        $launcherBytes = [System.IO.File]::ReadAllBytes($ExpectedLauncher)
        if (-not (Test-ByteArrayEqual $launcherBytes $expectedLauncherBytes)) { throw "launcher" }
        if (-not [System.IO.Directory]::Exists($ExpectedInstallRoot)) { throw "install_root" }
        if (-not [System.IO.Directory]::Exists($ExpectedVersionsDirectory)) { throw "versions" }
        if (-not [System.IO.Directory]::Exists($ExpectedBinDirectory)) { throw "bin_dir" }
    }
    catch {
        Stop-Installer "$MetadataPath exists but is not valid schema 1 PowerShell install metadata; refusing to overwrite it."
    }

    return @{
        Metadata = $metadata
        MetadataBytes = [byte[]]$metadataBytes
        LauncherBytes = [byte[]]$launcherBytes
        Venv = $normalizedVenv
        Python = $pythonCommand
        Command = $taplCommand
        Version = $versionValue
        WheelSha256 = $shaValue.ToLowerInvariant()
    }
}

function Compare-SemVer {
    param(
        [Parameter(Mandatory = $true)][string]$Left,
        [Parameter(Mandatory = $true)][string]$Right
    )
    $versionPattern = '^(?<major>[0-9]+)\.(?<minor>[0-9]+)\.(?<patch>[0-9]+)(?:(?<stage>a|b|rc)(?<serial>[0-9]+))?$'
    if ($Left -cnotmatch $versionPattern) { throw "invalid left version" }
    $leftParts = @($Matches['major'], $Matches['minor'], $Matches['patch'])
    $leftStage = $Matches['stage']
    $leftSerial = $Matches['serial']
    if ($Right -cnotmatch $versionPattern) { throw "invalid right version" }
    $rightParts = @($Matches['major'], $Matches['minor'], $Matches['patch'])
    $rightStage = $Matches['stage']
    $rightSerial = $Matches['serial']
    for ($index = 0; $index -lt 3; $index++) {
        $leftNumber = $leftParts[$index].TrimStart('0')
        $rightNumber = $rightParts[$index].TrimStart('0')
        if ([string]::IsNullOrEmpty($leftNumber)) { $leftNumber = "0" }
        if ([string]::IsNullOrEmpty($rightNumber)) { $rightNumber = "0" }
        if ($leftNumber.Length -gt $rightNumber.Length) { return 1 }
        if ($leftNumber.Length -lt $rightNumber.Length) { return -1 }
        $comparison = [string]::CompareOrdinal($leftNumber, $rightNumber)
        if ($comparison -gt 0) { return 1 }
        if ($comparison -lt 0) { return -1 }
    }

    $stageRanks = @{ a = 0; b = 1; rc = 2; stable = 3 }
    $leftStageKey = $leftStage
    $rightStageKey = $rightStage
    if ([string]::IsNullOrEmpty($leftStageKey)) { $leftStageKey = "stable" }
    if ([string]::IsNullOrEmpty($rightStageKey)) { $rightStageKey = "stable" }
    $leftStageRank = $stageRanks[$leftStageKey]
    $rightStageRank = $stageRanks[$rightStageKey]
    if ($leftStageRank -gt $rightStageRank) { return 1 }
    if ($leftStageRank -lt $rightStageRank) { return -1 }

    if ($leftStageKey -ne "stable") {
        $leftNumber = $leftSerial.TrimStart('0')
        $rightNumber = $rightSerial.TrimStart('0')
        if ([string]::IsNullOrEmpty($leftNumber)) { $leftNumber = "0" }
        if ([string]::IsNullOrEmpty($rightNumber)) { $rightNumber = "0" }
        if ($leftNumber.Length -gt $rightNumber.Length) { return 1 }
        if ($leftNumber.Length -lt $rightNumber.Length) { return -1 }
        $comparison = [string]::CompareOrdinal($leftNumber, $rightNumber)
        if ($comparison -gt 0) { return 1 }
        if ($comparison -lt 0) { return -1 }
    }
    return 0
}

function Invoke-TaplVersion {
    param([Parameter(Mandatory = $true)][string]$Command)
    try {
        $output = & $Command --version 2>$null
        if ($LASTEXITCODE -ne 0) { return $null }
        return (($output | Out-String).Trim())
    }
    catch {
        return $null
    }
}

function New-TemporaryFileWithBytes {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][byte[]]$Bytes
    )
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $path = Join-Path $Directory ($Prefix + [System.IO.Path]::GetRandomFileName())
        try {
            $stream = [System.IO.File]::Open(
                $path,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $stream.Write($Bytes, 0, $Bytes.Length)
                $stream.Flush($true)
            }
            finally {
                $stream.Dispose()
            }
            return $path
        }
        catch [System.IO.IOException] {
            continue
        }
    }
    Stop-Installer "could not prepare a temporary installation file."
}

function Move-FileAtomically {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if ([System.IO.File]::Exists($Destination)) {
        $nativeTypeName = "TaplInstaller.NativeFileOperations"
        if ($null -eq ([System.Management.Automation.PSTypeName]$nativeTypeName).Type) {
            Add-Type -TypeDefinition @'
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace TaplInstaller
{
    public static class NativeFileOperations
    {
        private const int MoveFileReplaceExisting = 0x1;
        private const int MoveFileWriteThrough = 0x8;

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "MoveFileExW", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool MoveFileEx(
            string existingFileName,
            string newFileName,
            int flags
        );

        public static void ReplaceExisting(string source, string destination)
        {
            if (!MoveFileEx(source, destination, MoveFileReplaceExisting | MoveFileWriteThrough))
            {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
        }
    }
}
'@ -ErrorAction Stop
        }
        [TaplInstaller.NativeFileOperations]::ReplaceExisting($Source, $Destination)
    }
    else {
        [System.IO.File]::Move($Source, $Destination)
    }
}

function Test-PathListContains {
    param(
        [AllowNull()][string]$PathList,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    if ([string]::IsNullOrEmpty($PathList)) { return $false }
    foreach ($entry in $PathList.Split(';')) {
        $candidate = $entry.Trim().Trim('"')
        if ([string]::IsNullOrEmpty($candidate)) { continue }
        try {
            $expanded = [System.Environment]::ExpandEnvironmentVariables($candidate)
            $normalized = [System.IO.Path]::GetFullPath($expanded).TrimEnd('\', '/')
            if (Test-PathEqual $normalized $Expected.TrimEnd('\', '/')) { return $true }
        }
        catch {
            if (Test-PathEqual $candidate.TrimEnd('\', '/') $Expected.TrimEnd('\', '/')) { return $true }
        }
    }
    return $false
}

function Add-ToUserPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
    if (-not (Test-PathListContains $userPath $Directory)) {
        if ([string]::IsNullOrEmpty($userPath)) {
            $newUserPath = $Directory
        }
        else {
            $newUserPath = $userPath + ';' + $Directory
        }
        [System.Environment]::SetEnvironmentVariable("Path", $newUserPath, [System.EnvironmentVariableTarget]::User)
    }
    if (-not (Test-PathListContains $env:Path $Directory)) {
        if ([string]::IsNullOrEmpty($env:Path)) {
            $env:Path = $Directory
        }
        else {
            $env:Path = $env:Path + ';' + $Directory
        }
    }
}

function Remove-FromUserPath {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $userPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)
    if ($null -ne $userPath) {
        $remaining = @($userPath.Split(';') | Where-Object { -not (Test-PathListContains $_ $Directory) })
        [System.Environment]::SetEnvironmentVariable("Path", ($remaining -join ';'), [System.EnvironmentVariableTarget]::User)
    }
    if ($null -ne $env:Path) {
        $env:Path = (@($env:Path.Split(';') | Where-Object { -not (Test-PathListContains $_ $Directory) }) -join ';')
    }
}

try {
    if ($env:OS -ne "Windows_NT") {
        Stop-Installer "this installer supports Windows only."
    }

    if ($Uninstall -and ($Reinstall -or -not [string]::IsNullOrEmpty($Version))) {
        Stop-Installer "-Uninstall cannot be combined with -Version or -Reinstall."
    }
    $requestedPythonVersion = $null
    if (-not [string]::IsNullOrEmpty($Version)) {
        if ($Version -cnotmatch '^(?<base>(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))(?:-(?<kind>alpha|beta|rc)(?<serial>0|[1-9][0-9]*))?$') {
            Stop-Installer "-Version must be x.y.z or x.y.z-(alpha|beta|rc)N, for example 2.14.0-beta1."
        }
        $requestedPythonVersion = $Matches['base']
        if (-not [string]::IsNullOrEmpty($Matches['kind'])) {
            $markers = @{ alpha = 'a'; beta = 'b'; rc = 'rc' }
            $requestedPythonVersion += $markers[$Matches['kind']] + $Matches['serial']
        }
    }

    if (-not [string]::IsNullOrEmpty($env:TAPL_INSTALL_ROOT)) {
        $installRoot = Get-NormalizedPath $env:TAPL_INSTALL_ROOT
    }
    elseif (-not [string]::IsNullOrEmpty($env:LOCALAPPDATA)) {
        $installRoot = Get-NormalizedPath (Join-Path $env:LOCALAPPDATA "tapl")
    }
    else {
        Stop-Installer "LOCALAPPDATA or TAPL_INSTALL_ROOT must be set."
    }

    if (-not [string]::IsNullOrEmpty($env:TAPL_BIN_DIR)) {
        $binDirectory = Get-NormalizedPath $env:TAPL_BIN_DIR
    }
    else {
        $binDirectory = Get-NormalizedPath (Join-Path $installRoot "bin")
    }
    if (-not [string]::IsNullOrEmpty($env:TAPL_INSTALL_MANIFEST_URL)) {
        $manifestUrl = $env:TAPL_INSTALL_MANIFEST_URL
    }
    elseif (-not [string]::IsNullOrEmpty($Version)) {
        $manifestUrl = "https://github.com/qkdxorjs1002/tapl/releases/download/$Version/taplctl-install-manifest.json"
    }
    else {
        $manifestUrl = $DefaultManifestUrl
    }
    if (-not (Test-SafeUrlText $manifestUrl)) {
        Stop-Installer "the release manifest URL is invalid."
    }

    $versionsDirectory = Join-Path $installRoot "versions"
    $metadataPath = Join-Path $installRoot "install.json"
    $launcherPath = Join-Path $binDirectory "taplctl.cmd"
    foreach ($path in @($installRoot, $binDirectory, $versionsDirectory, $metadataPath, $launcherPath)) {
        Assert-NoReparsePath $path
    }
    $metadataExists = Test-Path -LiteralPath $metadataPath
    $launcherExists = Test-Path -LiteralPath $launcherPath
    $managed = $null

    if ($metadataExists) {
        $managed = Get-ManagedInstallation -MetadataPath $metadataPath -ExpectedInstallRoot $installRoot -ExpectedBinDirectory $binDirectory -ExpectedVersionsDirectory $versionsDirectory -ExpectedLauncher $launcherPath
        $managedVersionOutput = $null
        if (-not $Uninstall -and -not $Reinstall) { $managedVersionOutput = Invoke-TaplVersion $managed.Command }
        if (-not $Uninstall -and -not $Reinstall -and $managedVersionOutput -ne "taplctl $($managed.Version)") {
            Stop-Installer "managed taplctl command version does not match install.json (expected taplctl $($managed.Version))."
        }
    }
    elseif ($launcherExists) {
        Stop-Installer "$launcherPath already exists and is not managed by a valid PowerShell install.json; move it or choose TAPL_BIN_DIR."
    }

    if ($Uninstall) {
        if ($null -eq $managed) {
            Write-InstallerNote "no managed installation was found; nothing to uninstall"
            return
        }
        # The active environment must be fully owned. Damaged or unmarked
        # historical environments are preserved for inspection after repair.
        $removals = @(Get-VerifiedVenvRemoval $managed.Venv)
        foreach ($item in @(Get-ChildItem -LiteralPath $versionsDirectory -Force -ErrorAction Stop)) {
            if (Test-PathEqual $item.FullName $managed.Venv) {
                continue
            }
            elseif (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Write-InstallerNote "preserving historical reparse entry: $($item.FullName)"
            }
            elseif ($item.PSIsContainer -and (Test-Path -LiteralPath (Join-Path $item.FullName ".tapl-managed-venv.json"))) {
                try { $removals += Get-VerifiedVenvRemoval $item.FullName }
                catch { Write-InstallerNote "preserving historical environment with changed or ambiguous ownership: $($item.FullName)" }
            }
        }
        foreach ($plan in $removals) { Assert-RemovalAccess $plan }
        Assert-FileRemovalAccess $launcherPath
        Assert-FileRemovalAccess $metadataPath
        if (-not (Test-ByteArrayEqual ([System.IO.File]::ReadAllBytes($metadataPath)) $managed.MetadataBytes) -or
            -not (Test-ByteArrayEqual ([System.IO.File]::ReadAllBytes($launcherPath)) $managed.LauncherBytes)) {
            Stop-Installer "installation ownership changed during uninstall preparation; no files were removed."
        }
        try {
            foreach ($plan in @($removals | Sort-Object { Test-PathEqual $_.Directory $managed.Venv })) { Remove-VerifiedVenv $plan }
        }
        catch {
            Stop-Installer "could not remove all managed binaries; close taplctl/Codex processes. Metadata was preserved for inspection; configuration and workflow data were preserved."
        }
        $pathProperty = $managed.Metadata.PSObject.Properties['added_to_user_path']
        [System.IO.File]::Delete($launcherPath)
        [System.IO.File]::Delete($metadataPath)
        if ($null -ne $pathProperty -and $pathProperty.Value -eq $true) { Remove-FromUserPath $binDirectory }
        foreach ($directory in @($binDirectory, $versionsDirectory, $installRoot)) {
            if ([System.IO.Directory]::Exists($directory) -and @(Get-ChildItem -LiteralPath $directory -Force).Count -eq 0) {
                [System.IO.Directory]::Delete($directory, $false)
            }
        }
        Write-InstallerNote "managed taplctl binaries were uninstalled; configuration and workflow data were preserved"
        Write-Output "To remove workflow integration first, run taplctl uninstall user before -Uninstall."
        return
    }

    $python = Find-Python
    if ($Reinstall -and $null -ne $managed -and [string]::IsNullOrEmpty($Version) -and [string]::IsNullOrEmpty($env:TAPL_INSTALL_MANIFEST_URL)) {
        $manifestUrl = $managed.Metadata.manifest_url
    }

    if ($null -eq $managed) {
        [System.IO.Directory]::CreateDirectory($installRoot) | Out-Null
        [System.IO.Directory]::CreateDirectory($versionsDirectory) | Out-Null
        [System.IO.Directory]::CreateDirectory($binDirectory) | Out-Null
    }

    $WorkDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("tapl-install-" + [System.Guid]::NewGuid().ToString("N"))
    [System.IO.Directory]::CreateDirectory($WorkDirectory) | Out-Null
    $manifestPath = Join-Path $WorkDirectory "taplctl-install-manifest.json"

    Write-InstallerNote "fetching the release manifest"
    try {
        Invoke-WebRequest -UseBasicParsing -Uri $manifestUrl -OutFile $manifestPath -ErrorAction Stop | Out-Null
    }
    catch {
        Stop-Installer "could not download the release manifest."
    }
    if ((Get-Item -LiteralPath $manifestPath).Length -gt 1048576) {
        Stop-Installer "release manifest validation failed."
    }

    try {
        $manifest = (Read-Utf8Text $manifestPath) | ConvertFrom-Json
        if (-not ($manifest -is [System.Management.Automation.PSCustomObject])) { throw "root" }
        $manifestSchema = Get-PropertyValue $manifest "schema_version"
        if (($manifestSchema -is [bool]) -or $manifestSchema -ne 1) { throw "schema" }
        $manifestVersion = Get-PropertyValue $manifest "version"
        if (-not ($manifestVersion -is [string]) -or $manifestVersion -cnotmatch '^[0-9]+\.[0-9]+\.[0-9]+(?:(?:a|b|rc)[0-9]+)?$') { throw "version" }
        $wheel = Get-PropertyValue $manifest "wheel"
        if (-not ($wheel -is [System.Management.Automation.PSCustomObject])) { throw "wheel" }
        $wheelUrl = Get-PropertyValue $wheel "url"
        $wheelSha256 = Get-PropertyValue $wheel "sha256"
        if (-not (Test-SafeUrlText $wheelUrl)) { throw "wheel_url" }
        if (-not ($wheelSha256 -is [string]) -or $wheelSha256 -notmatch '^[0-9a-fA-F]{64}$') { throw "sha" }
        $wheelSha256 = $wheelSha256.ToLowerInvariant()
        $wheelUri = [System.Uri]$wheelUrl
        if (-not $wheelUri.IsAbsoluteUri) { throw "wheel_url" }
        $wheelName = [System.IO.Path]::GetFileName($wheelUri.AbsolutePath)
        if ($wheelName -notmatch '^[A-Za-z0-9_.+\-]+\.whl$') { throw "wheel_name" }
    }
    catch {
        Stop-Installer "release manifest validation failed."
    }

    if ($null -ne $requestedPythonVersion -and $manifestVersion -cne $requestedPythonVersion) {
        Stop-Installer "release manifest version does not match requested -Version $Version."
    }

    if ($null -ne $managed) {
        $versionComparison = Compare-SemVer $managed.Version $manifestVersion
        if ($versionComparison -gt 0 -and [string]::IsNullOrEmpty($Version) -and -not $Reinstall) {
            Write-InstallerNote "installed taplctl $($managed.Version) is newer than published release $manifestVersion; leaving it unchanged"
            Add-ToUserPath $binDirectory
            Write-Output ""
            Write-Output "Workflow hooks were not installed automatically. Install them when ready:"
            Write-Output "  taplctl install user"
            return
        }
    }

    $currentVenv = $null
    if (
        $null -ne $managed -and
        -not $Reinstall -and
        $managed.Version -eq $manifestVersion -and
        $managed.WheelSha256 -eq $wheelSha256
    ) {
        $currentVenv = $managed.Venv
        Write-InstallerNote "version $manifestVersion is already installed"
    }

    if ($null -eq $currentVenv) {
        $wheelPath = Join-Path $WorkDirectory $wheelName
        Write-InstallerNote "downloading taplctl $manifestVersion"
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $wheelUrl -OutFile $wheelPath -ErrorAction Stop | Out-Null
        }
        catch {
            Stop-Installer "could not download the taplctl wheel."
        }

        try {
            $actualSha256 = Get-FileSha256 -Path $wheelPath
        }
        catch {
            Stop-Installer "could not calculate the wheel SHA-256."
        }
        if ($actualSha256 -ne $wheelSha256) {
            Stop-Installer "wheel SHA-256 mismatch (expected $wheelSha256, got $actualSha256)."
        }
        Write-InstallerNote "wheel SHA-256 verified"

        for ($attempt = 0; $attempt -lt 20; $attempt++) {
            $candidateName = "$manifestVersion-$($wheelSha256.Substring(0, 12)).$([System.IO.Path]::GetRandomFileName())"
            $candidatePath = Join-Path $versionsDirectory $candidateName
            if (-not (Test-Path -LiteralPath $candidatePath)) {
                $CandidateVenv = $candidatePath
                break
            }
        }
        if ($null -eq $CandidateVenv) {
            Stop-Installer "could not choose a unique virtual environment path."
        }
        $CandidateIncomplete = $true

        Write-InstallerNote "creating a dedicated virtual environment"
        $venvExit = Invoke-SelectedPython -Python $python -Arguments @("-m", "venv", $CandidateVenv)
        if ($venvExit -ne 0) {
            Stop-Installer "could not create a virtual environment. Ensure the Python venv module is available."
        }

        $candidatePython = Join-Path (Join-Path $CandidateVenv "Scripts") "python.exe"
        $candidateCommand = Join-Path (Join-Path $CandidateVenv "Scripts") "taplctl.exe"
        if (-not (Test-RegularFile $candidatePython)) {
            Stop-Installer "the virtual environment did not create Scripts\python.exe."
        }
        Write-InstallerNote "installing taplctl $manifestVersion"
        & $candidatePython -m pip install --disable-pip-version-check --upgrade $wheelPath
        if ($LASTEXITCODE -ne 0) {
            Stop-Installer "pip could not install taplctl; the previous installation was left unchanged."
        }
        if (-not (Test-RegularFile $candidateCommand) -or (Invoke-TaplVersion $candidateCommand) -ne "taplctl $manifestVersion") {
            Stop-Installer "the installed taplctl executable failed validation."
        }
        Write-VenvInventory $CandidateVenv
        $currentVenv = $CandidateVenv
    }

    if ($null -ne $managed) {
        if (-not (Test-ByteArrayEqual ([System.IO.File]::ReadAllBytes($metadataPath)) $managed.MetadataBytes)) {
            Stop-Installer "install metadata changed while the installation was being prepared."
        }
        if (-not (Test-ByteArrayEqual ([System.IO.File]::ReadAllBytes($launcherPath)) $managed.LauncherBytes)) {
            Stop-Installer "the managed taplctl launcher changed while the installation was being prepared."
        }
    }
    elseif ((Test-Path -LiteralPath $metadataPath) -or (Test-Path -LiteralPath $launcherPath)) {
        Stop-Installer "installation ownership changed while the installation was being prepared."
    }

    $currentCommand = Join-Path (Join-Path $currentVenv "Scripts") "taplctl.exe"
    $launcherBytes = Get-WindowsLauncherBytes -Command $currentCommand
    $addedToUserPath = -not (Test-PathListContains ([System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::User)) $binDirectory)
    if ($null -ne $managed) {
        $pathProperty = $managed.Metadata.PSObject.Properties['added_to_user_path']
        $addedToUserPath = ($addedToUserPath -or ($null -ne $pathProperty -and $pathProperty.Value -eq $true))
    }
    $metadataObject = [ordered]@{
        schema_version = 1
        method = "powershell"
        manifest_url = $manifestUrl
        version = $manifestVersion
        wheel_url = $wheelUrl
        wheel_sha256 = $wheelSha256
        install_root = $installRoot
        bin_dir = $binDirectory
        venv = $currentVenv
        executable = $launcherPath
        added_to_user_path = [bool]$addedToUserPath
        installed_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss.fffZ", [System.Globalization.CultureInfo]::InvariantCulture)
    }
    $metadataText = ($metadataObject | ConvertTo-Json -Depth 4) + "`n"
    $metadataBytes = $Utf8NoBom.GetBytes($metadataText)

    $LauncherTemporary = New-TemporaryFileWithBytes -Directory $binDirectory -Prefix ".taplctl.cmd.tmp." -Bytes $launcherBytes
    $MetadataTemporary = New-TemporaryFileWithBytes -Directory $installRoot -Prefix ".install.json." -Bytes $metadataBytes
    $oldLauncherBytes = $null
    if ($null -ne $managed) {
        $oldLauncherBytes = $managed.LauncherBytes
    }

    try {
        Move-FileAtomically -Source $LauncherTemporary -Destination $launcherPath
        $LauncherTemporary = $null
    }
    catch {
        Stop-Installer "could not activate the taplctl command launcher; the previous installation was left unchanged."
    }

    try {
        Move-FileAtomically -Source $MetadataTemporary -Destination $metadataPath
        $MetadataTemporary = $null
    }
    catch {
        $rollbackSucceeded = $false
        try {
            $activeBytes = [System.IO.File]::ReadAllBytes($launcherPath)
            if (-not (Test-ByteArrayEqual $activeBytes $launcherBytes)) {
                throw "launcher changed"
            }
            if ($null -ne $oldLauncherBytes) {
                $rollbackPath = New-TemporaryFileWithBytes -Directory $binDirectory -Prefix ".taplctl.cmd.rollback." -Bytes $oldLauncherBytes
                try {
                    Move-FileAtomically -Source $rollbackPath -Destination $launcherPath
                    $rollbackPath = $null
                }
                finally {
                    if ($null -ne $rollbackPath -and (Test-Path -LiteralPath $rollbackPath)) {
                        Remove-Item -LiteralPath $rollbackPath -Force -ErrorAction SilentlyContinue
                    }
                }
            }
            else {
                [System.IO.File]::Delete($launcherPath)
            }
            $rollbackSucceeded = $true
        }
        catch {
            $rollbackSucceeded = $false
        }
        if ($rollbackSucceeded) {
            Stop-Installer "install metadata could not be activated; the previous command launcher was restored."
        }
        if ($CandidateIncomplete -and (Test-RegularFile $launcherPath)) {
            try {
                $remainingLauncherBytes = [System.IO.File]::ReadAllBytes($launcherPath)
                if (Test-ByteArrayEqual $remainingLauncherBytes $launcherBytes) {
                    # The public launcher still owns this candidate. Preserve it
                    # rather than turn an activation failure into a broken command.
                    $CandidateIncomplete = $false
                }
            }
            catch {
                # Candidate cleanup remains enabled when ownership is uncertain.
            }
        }
        Stop-Installer "install metadata could not be activated and the previous command launcher could not be restored."
    }

    $CandidateIncomplete = $false
    Add-ToUserPath $binDirectory
    Write-InstallerNote "taplctl $manifestVersion is installed at $launcherPath"
    Write-Output ""
    Write-Output "Workflow hooks were not installed automatically. Install them when ready:"
    Write-Output "  taplctl install user"
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    foreach ($temporary in @($LauncherTemporary, $MetadataTemporary)) {
        if ($null -ne $temporary -and (Test-Path -LiteralPath $temporary)) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
    if ($CandidateIncomplete -and $null -ne $CandidateVenv -and (Test-Path -LiteralPath $CandidateVenv)) {
        try {
            $inventory = Get-VenvInventory $CandidateVenv
            Remove-VerifiedVenv @{ Directory = $CandidateVenv; Files = @($inventory.files.Keys); Directories = @($inventory.directories) }
        }
        catch {
            Write-Warning "taplctl installer: could not remove the incomplete candidate environment."
        }
    }
    if ($null -ne $WorkDirectory -and (Test-Path -LiteralPath $WorkDirectory)) {
        try {
            $inventory = Get-VenvInventory $WorkDirectory
            Remove-VerifiedVenv @{ Directory = $WorkDirectory; Files = @($inventory.files.Keys); Directories = @($inventory.directories) }
        }
        catch { Write-Warning "taplctl installer: could not remove temporary download files." }
    }
}
