#requires -Version 5.1
# TAPL_RELEASE_BOOTSTRAP_V1

[CmdletBinding()]
param(
    [string]$Version,
    [switch]$Pre,
    [switch]$Semantic,
    [switch]$Reinstall,
    [switch]$Uninstall
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
# A Windows PowerShell child can inherit PowerShell 7's module search paths.
# Resolve built-in commands from the current host before inherited editions.
$env:PSModulePath = [IO.Path]::Combine($PSHOME, "Modules")
$ReleaseBaseUrl = "https://github.com/qkdxorjs1002/tapl/releases"
$ReleasesApiUrl = "https://api.github.com/repos/qkdxorjs1002/tapl/releases"
$MaxReleasePages = 10
$TagPattern = '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)(?:0|[1-9][0-9]*))?$'
$BootstrapMarker = "# TAPL_RELEASE_BOOTSTRAP_V1"
$WorkDirectory = $null
$exitCode = 1

function Get-ReleaseProperty {
    param($Release, [string]$Name)
    if ($null -eq $Release) { return $null }
    $property = $Release.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    return $property.Value
}

function Get-LatestPublishedReleaseTag {
    $selectedTag = $null
    $selectedPublishedAt = [DateTimeOffset]::MinValue
    $jsonParameters = @{ ErrorAction = "Stop" }
    # Newer pwsh can retain JSON strings directly; Windows PowerShell 5.1
    # lacks this option, and some intermediate hosts materialize ISO dates.
    if ((Get-Command ConvertFrom-Json).Parameters.ContainsKey("DateKind")) {
        $jsonParameters["DateKind"] = "String"
    }
    for ($page = 1; $page -le $MaxReleasePages; $page++) {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "$($ReleasesApiUrl)?per_page=100&page=$page" -Headers @{ Accept = "application/vnd.github+json" } -UserAgent "tapl-bootstrap" -ErrorAction Stop
        $json = ([string]$response.Content).Trim()
        if (-not $json.StartsWith("[") -or -not $json.EndsWith("]")) {
            throw "the releases API response is not a JSON array."
        }
        # Windows PowerShell returns the JSON array as one pipeline object.
        # Assign first, then normalize, so both 5.1 and pwsh yield flat items.
        $parsedReleases = $json | ConvertFrom-Json @jsonParameters
        $releases = @($parsedReleases)
        foreach ($release in $releases) {
            $draft = Get-ReleaseProperty $release "draft"
            $tag = Get-ReleaseProperty $release "tag_name"
            $publishedAt = Get-ReleaseProperty $release "published_at"
            if ($draft -isnot [bool] -or $draft -or $tag -isnot [string] -or $tag -cnotmatch $TagPattern) { continue }
            $timestamp = [DateTimeOffset]::MinValue
            if ($publishedAt -is [string]) {
                if ($publishedAt -cnotmatch '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,7})?(?:Z|[+-]\d{2}:\d{2})$') { continue }
                if (-not [DateTimeOffset]::TryParse($publishedAt, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$timestamp)) { continue }
            }
            elseif ($publishedAt -is [DateTimeOffset]) {
                $timestamp = $publishedAt
            }
            elseif ($publishedAt -is [DateTime] -and $publishedAt.Kind -ne [DateTimeKind]::Unspecified) {
                # A JSON-converted UTC/local DateTime preserves the instant.
                # An unspecified DateTime has no trusted timezone; reject it.
                $timestamp = [DateTimeOffset]::new($publishedAt)
            }
            else { continue }
            if ($timestamp -gt $selectedPublishedAt) {
                $selectedTag = $tag
                $selectedPublishedAt = $timestamp
            }
        }
        if ($releases.Count -lt 100) {
            if ($null -eq $selectedTag) { throw "no published release with a valid tag and publication timestamp was found." }
            return $selectedTag
        }
    }
    throw "the releases API exceeded the pagination limit; refusing an incomplete release selection."
}

try {
    # Validate before creating a directory or making any network requests.
    $hasVersion = $PSBoundParameters.ContainsKey("Version")
    if ($Uninstall -and $Reinstall) {
        throw "-Uninstall cannot be combined with -Reinstall."
    }
    if ($Pre -and $hasVersion) {
        throw "-Pre cannot be combined with -Version."
    }
    if ($hasVersion -and $Version -cnotmatch $TagPattern) {
        throw "-Version must be x.y.z or x.y.z-(alpha|beta|rc)N, for example 2.14.0-beta1."
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $scriptUrl = "$ReleaseBaseUrl/latest/download/install.ps1"
    $channel = "stable"
    if ($hasVersion) {
        $scriptUrl = "$ReleaseBaseUrl/download/$Version/install.ps1"
        $channel = "pinned"
    }
    if ($Pre) {
        $Version = Get-LatestPublishedReleaseTag
        $scriptUrl = "$ReleaseBaseUrl/download/$Version/install.ps1"
        $channel = "pre"
    }

    # Use the current PowerShell host so both Windows PowerShell and pwsh work.
    $hostExecutable = [System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    if (-not [System.IO.File]::Exists($hostExecutable)) {
        throw "could not locate the current PowerShell executable."
    }

    $candidate = Join-Path ([System.IO.Path]::GetTempPath()) ("tapl-bootstrap-" + [guid]::NewGuid().ToString("N"))
    # New-Item fails if the name already exists; never reuse another directory.
    $null = New-Item -ItemType Directory -Path $candidate -ErrorAction Stop
    $WorkDirectory = $candidate
    if ([System.Environment]::OSVersion.Platform -eq [System.PlatformID]::Win32NT) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
        $acl = [System.Security.AccessControl.DirectorySecurity]::new()
        $acl.SetOwner($identity)
        $acl.SetAccessRuleProtection($true, $false)
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new($identity, "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $WorkDirectory -AclObject $acl -ErrorAction Stop
    }
    else {
        # Unix pwsh is supported for portable validation of this bootstrap.
        & /bin/chmod 700 $WorkDirectory
        if ($LASTEXITCODE -ne 0) { throw "could not make the temporary directory private." }
    }
    $scriptPath = Join-Path $WorkDirectory "install.ps1"
    Invoke-WebRequest -UseBasicParsing -Uri $scriptUrl -OutFile $scriptPath -ErrorAction Stop | Out-Null
    $downloadedSource = [System.IO.File]::ReadAllText($scriptPath)
    if ([string]::IsNullOrWhiteSpace($downloadedSource)) {
        throw "the release installer asset is empty."
    }
    if ($downloadedSource.Contains($BootstrapMarker)) {
        throw "the release asset is a bootstrap instead of an installer; refusing recursive execution."
    }

    $tokens = $null
    $parseErrors = $null
    $installerAst = [System.Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$parseErrors)
    if ($parseErrors.Count -gt 0) {
        throw "the release installer asset contains PowerShell syntax errors."
    }
    # Older release scripts may silently ignore options. Only declarations in
    # the script's own parameter block establish that an option is supported.
    $declaredParameters = @()
    if ($null -ne $installerAst.ParamBlock) {
        $declaredParameters = @($installerAst.ParamBlock.Parameters | ForEach-Object { $_.Name.VariablePath.UserPath })
    }
    $requestedParameters = @()
    $forwardVersion = ($hasVersion -or $Pre) -and -not $Uninstall
    if ($forwardVersion) { $requestedParameters += "Version" }
    if ($Semantic) { $requestedParameters += "Semantic" }
    if ($Reinstall) { $requestedParameters += "Reinstall" }
    if ($Uninstall) { $requestedParameters += "Uninstall" }
    if ($Pre -and -not $Uninstall) { $requestedParameters += "Channel" }
    foreach ($parameter in $requestedParameters) {
        if ($declaredParameters -notcontains $parameter) {
            throw "the release installer does not support the requested -$parameter option."
        }
    }

    $childArguments = @("-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $scriptPath)
    if ($forwardVersion) { $childArguments += @("-Version", $Version) }
    if ($Semantic) { $childArguments += "-Semantic" }
    if ($declaredParameters -contains "Channel") { $childArguments += @("-Channel", $channel) }
    if ($Reinstall) { $childArguments += "-Reinstall" }
    if ($Uninstall) { $childArguments += "-Uninstall" }
    & $hostExecutable @childArguments
    $exitCode = $LASTEXITCODE
}
catch {
    [Console]::Error.WriteLine("taplctl bootstrap: " + $_.Exception.Message)
    $exitCode = 1
}
finally {
    if ($null -ne $WorkDirectory) {
        Remove-Item -LiteralPath $WorkDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
