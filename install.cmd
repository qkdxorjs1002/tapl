@echo off
setlocal DisableDelayedExpansion
set "TAPL_BOOTSTRAP_WORK="
rem Paths are exchanged through the environment, never inserted in PowerShell code.
for /f "usebackq delims=" %%D in (`"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; try { $p = Join-Path ([IO.Path]::GetTempPath()) ('tapl-cmd-' + [guid]::NewGuid().ToString('N')); $acl = [Security.AccessControl.DirectorySecurity]::new(); $user = [Security.Principal.WindowsIdentity]::GetCurrent().User; $acl.SetOwner($user); $acl.SetAccessRuleProtection($true, $false); $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($user, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')); if (Test-Path -LiteralPath $p) { throw 'temporary directory already exists' }; $null = [IO.Directory]::CreateDirectory($p, $acl); [Console]::WriteLine($p) } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"`) do set "TAPL_BOOTSTRAP_WORK=%%D"
if not defined TAPL_BOOTSTRAP_WORK exit /b 1
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1' -OutFile (Join-Path $env:TAPL_BOOTSTRAP_WORK 'install.ps1') -ErrorAction Stop } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
if errorlevel 1 goto download_failed
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%TAPL_BOOTSTRAP_WORK%\install.ps1" %*
set "TAPL_BOOTSTRAP_EXIT=%errorlevel%"
goto cleanup
:download_failed
set "TAPL_BOOTSTRAP_EXIT=%errorlevel%"
:cleanup
rmdir /s /q "%TAPL_BOOTSTRAP_WORK%"
exit /b %TAPL_BOOTSTRAP_EXIT%
