@echo off
setlocal DisableDelayedExpansion
rem Let Windows PowerShell rebuild its own module paths, even from a pwsh parent.
set "PSModulePath="
if not defined TEMP exit /b 1
set "TAPL_BOOTSTRAP_WORK=%TEMP%\tapl-cmd-%RANDOM%-%RANDOM%-%RANDOM%"
mkdir "%TAPL_BOOTSTRAP_WORK%" >nul 2>&1
if errorlevel 1 exit /b 1
rem Paths are exchanged through the environment, never inserted in PowerShell code.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; try { $acl = [Security.AccessControl.DirectorySecurity]::new(); $user = [Security.Principal.WindowsIdentity]::GetCurrent().User; $acl.SetOwner($user); $acl.SetAccessRuleProtection($true, $false); $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($user, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')); Set-Acl -LiteralPath $env:TAPL_BOOTSTRAP_WORK -AclObject $acl -ErrorAction Stop; [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1' -OutFile (Join-Path $env:TAPL_BOOTSTRAP_WORK 'install.ps1') -ErrorAction Stop } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
if errorlevel 1 goto download_failed
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%TAPL_BOOTSTRAP_WORK%\install.ps1" %*
set "TAPL_BOOTSTRAP_EXIT=%errorlevel%"
goto cleanup
:download_failed
set "TAPL_BOOTSTRAP_EXIT=%errorlevel%"
:cleanup
rmdir /s /q "%TAPL_BOOTSTRAP_WORK%"
exit /b %TAPL_BOOTSTRAP_EXIT%
