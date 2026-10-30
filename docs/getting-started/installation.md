# Installation

[Documentation](../README.md) · [한국어](installation.ko.md)

Install the TAPL executables for your platform, then [connect Codex](integrations.md). Package installation and Codex connection scope are separate choices. You can also [ask your agent to install and connect TAPL](integrations.md#ask-your-agent-to-install-tapl).

## Requirements

- Python 3.11+ with `venv`; the Homebrew formula uses `python@3.12`.
- SQLite with FTS5 and extension loading support.
- Homebrew for a formula installation; `curl` for Linux installation.
- Windows 10/11 and PowerShell 5.1+ or PowerShell 7 for Windows installation.
- A browser for the optional Viewer; VS Code for the optional extension.

The TAPL wheel is platform-independent, but dependencies still need compatible wheels. Uncommon architectures, very new Python versions, and musl-based Linux distributions such as Alpine may need local build tools. Source development uses `uv`; see [contributing](../development/contributing.md).

## macOS with Homebrew

Add the tap and choose **one** formula:

```sh
brew tap qkdxorjs1002/tap

# Stable, with full-text search
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl

# Or: stable, with semantic/vector dependencies
brew trust --formula qkdxorjs1002/tap/taplctl-semantic
brew install taplctl-semantic

# Or: newest published release, including prereleases
brew trust --formula qkdxorjs1002/tap/taplctl-pre
brew install taplctl-pre
```

`taplctl` and `taplctl-semantic` follow stable releases. `taplctl-pre` selects the newest published release, which can be stable or prerelease; `taplctl@pre` is an alias. Use the canonical formula name for trust and prefix lookup.

All three provide `taplctl`, `tapl-mcp`, and `tapl-hook` and cannot coexist. Uninstall the current formula before switching, for example `brew uninstall taplctl`. Formulae use pinned release-hosted wheel bundles without resolving packages from PyPI at installation time.

## Linux

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

The standalone installer selects the latest stable release. It requires `curl`, Python 3.11+ with `venv`, and writable installation directories. It installs under `${XDG_DATA_HOME:-$HOME/.local/share}/tapl` and links the command in `${XDG_BIN_HOME:-$HOME/.local/bin}` by default.

Set `TAPL_INSTALL_ROOT` and `TAPL_BIN_DIR` to override those locations; otherwise the corresponding XDG variables apply. The script prints any required `PATH` export but does not edit shell startup files or install Codex hooks. Apply the export and make it persistent if needed, then [connect Codex](integrations.md#choose-a-connection-scope).

## Windows

Download the fixed entry script from `main`, then run it:

```powershell
Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 -OutFile install.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

Or use Command Prompt:

```bat
curl.exe -fL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.cmd -o install.cmd
install.cmd
```

Installation is per-user without administrator access. The default root is `%LOCALAPPDATA%\tapl`, with a launcher at `%LOCALAPPDATA%\tapl\bin\taplctl.cmd`. Reopen your terminal to load the updated user `PATH`, then [connect Codex](integrations.md#standalone-executable-paths).

### Channels and semantic dependencies

The `main` entry scripts select a release and download that release's installer asset. Release installer assets install their own version; they are not channel-selection entry scripts.

| Entry-script options | Selection |
| --- | --- |
| None | Latest stable release |
| `-Pre` | Newest published release, including prereleases; a newer stable release can also win |
| `-Semantic` | Latest stable with embedding/vector dependencies |
| `-Pre -Semantic` | Newest published release with semantic dependencies |
| `-Version TAG` | Exact release tag |
| `-Version TAG -Semantic` | Exact release with semantic dependencies |

`-Pre` and `-Version` cannot be combined. A tag uses `x.y.z` or `x.y.z-(alpha|beta|rc)N`, for example `2.14.0-beta1`. Replace `TAG` below with an actual release tag:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Pre -Semantic
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version TAG
```

```bat
install.cmd -Pre -Semantic
install.cmd -Version TAG
```

Windows supports local semantic search with its optional dependencies. The Unix-socket `searchd` daemon is unavailable on Windows; full-text search works without it. See [search](../guides/search.md).

### Reinstall or remove Windows executables

Use the downloaded entry script, with the release/channel options you intend to keep:

| Action | PowerShell | CMD |
| --- | --- | --- |
| Reinstall | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Reinstall` | `install.cmd -Reinstall` |
| Remove executables | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall` | `install.cmd -Uninstall` |

`-Reinstall` and `-Uninstall` cannot be combined. To switch releases, including a downgrade, run the entry script with `-Version TAG`; add `-Reinstall` when reinstalling the same release. Reinstall examples without a channel flag use the stable default.

Before removing executables, [disconnect each installed Codex scope](integrations.md#disconnect-or-reconnect). Removal preserves TAPL settings, workflow databases, and unrelated files. Legacy installations without a file inventory require `-Reinstall` first; modified managed files stop removal for inspection.

`TAPL_INSTALL_ROOT` and `TAPL_BIN_DIR` override installation and launcher directories. `TAPL_INSTALL_MANIFEST_URL` selects a custom manifest; a release installer still requires a manifest for its own version. The installer verifies the manifest and wheel SHA-256 before use.

## Update

For Linux and Windows standalone installations:

```sh
taplctl update --check
taplctl update
```

The updater checks managed-install metadata and verifies the manifest and wheel SHA-256. Windows updates preserve stable, prerelease, or pinned channel selection and the semantic option; a pinned channel keeps using its recorded release manifest. Use the Windows entry script to deliberately change that selection. `TAPL_INSTALL_MANIFEST_URL` overrides manifest selection.

For Homebrew, update the installed formula instead:

```sh
brew update
brew upgrade taplctl
# Use taplctl-semantic or taplctl-pre if that is your installed formula.
```

`taplctl update` does not update Homebrew or source checkouts. During Homebrew upgrade/reinstall, the formula attempts to restart its Viewer service only if already running. A fresh install or stopped service remains stopped. Manually started MCP stdio and `searchd` processes are not restarted.

Existing opted-in Codex integrations refresh at MCP startup and hook entry when the version or shipped templates change. Refresh preserves settings and hook mode, merges missing defaults, and migrates known obsolete keys. Repeating `taplctl install` is normally unnecessary after an update; restart Codex to reload host configuration. See [refresh boundaries](integrations.md#automatic-refresh).

## Verify and continue

```sh
taplctl --version
taplctl doctor
```

`doctor` reports the runtime, SQLite capabilities, optional dependencies, configuration, and selected database. Missing semantic dependencies do not prevent full-text use. Run it in the intended workspace; it may initialize workspace state and refresh existing integration.

- [Quick start](quickstart.md): connect and complete your first task.
- [Agent integration](integrations.md): scopes, executable paths, hook trust, and disconnection.
- [CLI reference](../reference/cli.md): management options.
- [Troubleshooting](../guides/troubleshooting.md): installation and connection diagnosis.
