# Releases

[Documentation](../README.md) · [한국어](releases.ko.md)

TAPL's release workflow builds versioned Python, runtime, installer, and VS Code assets from a Git tag. This guide describes the checked-in publishing contract and maintainer setup. For end-user install/update commands, use [Installation](../getting-started/installation.md).

## Tags and injected versions

[The release workflow](../../.github/workflows/release.yml) triggers on pushed `*.*.*` tags, then [`release_version.py`](../../.github/scripts/release_version.py) validates the canonical form:

| Tag example | Python package version | Channel behavior |
| --- | --- | --- |
| `2.0.1` | `2.0.1` | Stable release; Marketplace eligible. |
| `2.0.1-alpha1` | `2.0.1a1` | GitHub prerelease. |
| `2.0.1-beta4` | `2.0.1b4` | GitHub prerelease. |
| `2.0.1-rc1` | `2.0.1rc1` | GitHub prerelease. |

Tags have no leading `v` and no build metadata. The workflow injects the PEP 440 version into `tapl/pyproject.toml` and the tag version into `vscode-extension/package.json` before building. Checked-in static versions are development metadata, not a declaration of the latest published version. Inspect the intended tag's assets or `taplctl --version` for an installation.

A local, non-publishing validation example:

```sh
python3 .github/scripts/release_version.py 2.0.1-beta4
# version=2.0.1-beta4
# python_version=2.0.1b4
# prerelease=true
```

## Build and publication flow

Windows preflight and both macOS signing jobs must succeed before the Ubuntu release job. Preflight uses Python 3.11/3.12 and PowerShell 5.1 parsing, tests the bootstrap/runtime/version-bound assets, builds a real wheel, and runs install/update/reinstall/uninstall plus CLI/MCP smoke checks.

The release job uses Python 3.12 and Node.js 22, injects versions, runs extension host tests and the shared Viewer build, builds the Python wheel and Linux runtime wheelhouses, downloads signed macOS runtimes, packages the VSIX, and prepares release installers/manifest. Asset validation checks versions, exact URLs, SHA-256 values, required runtime distributions, and rendered Windows installer contents. An isolated Linux x86_64 venv smoke verifies the installed version and native MCP tool inventory/status.

| Asset | Purpose |
| --- | --- |
| `taplctl-PYTHON_VERSION-py3-none-any.whl` | Platform-independent TAPL application package. |
| `taplctl-mcp-runtime-TAG-macos-arm64.tar.gz` | Signed macOS arm64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-macos-x86_64.tar.gz` | Signed macOS x86_64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-arm64.tar.gz` | Linux arm64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-x86_64.tar.gz` | Linux x86_64 MCP dependency wheelhouse. |
| `tapl-workflow-viewer-TAG.vsix` | Validated VS Code extension. Prerelease tags also publish this through GitHub Releases. |
| `taplctl-install-manifest.json` | Schema version 1, Python version, wheel URL, and wheel SHA-256. |
| `install.ps1`, `install.cmd` | Windows release assets; the PowerShell installer is stamped for that release. |

`PYTHON_VERSION` and `TAG` above are naming placeholders, including their different prerelease syntax. The manifest does not list every runtime archive; release/Homebrew runtime URL/hash metadata is computed separately from the final asset bytes. A Windows wheelhouse is not among these tarball targets.

The workflow creates or updates the tagged GitHub Release and uploads assets (`--clobber` on an existing release). Prereleases are marked explicitly. Re-running can replace same-tag assets, so review the concrete source and generated contents before publication.

## Homebrew channels

`HOMEBREW_TAP_TOKEN` is required with write access to `qkdxorjs1002/homebrew-tap`. The job uses the existing `Formula/taplctl.rb` as the template and updates `Formula/taplctl-pre.rb` plus `Aliases/taplctl@pre` on releases. Stable releases also update the stable formula and `taplctl-semantic.rb` when present. Prereleases leave the stable formulas unchanged. The updater skips a version older than the formula's current version and validates generated Ruby syntax before committing/pushing the tap.

The three formulas conflict because they provide the same commands. Runtime wheelhouse URLs and checksums select the matching macOS/Linux architecture. Viewer services use port 8000; the semantic formula does not automatically start `searchd`. See [Viewer services](../guides/viewer.md#run-as-a-homebrew-service).

## Windows entry scripts and release installers

The repository's top-level `install.ps1` is a **routing bootstrap**, with `install.cmd` as its CMD entry. It chooses a release before downloading that release's installer:

- No channel option: GitHub's latest stable release asset.
- `-Pre`: newest valid published release by publication time, including prereleases and possibly a newer stable release.
- `-Version TAG`: the exact release. It cannot be combined with `-Pre`.
- `-Semantic`, `-Reinstall`, and `-Uninstall`: forwarded when supported by the selected installer.

The source `.github/scripts/install-windows.ps1` is a developer template. [`prepare_windows_installers.py`](../../.github/scripts/prepare_windows_installers.py) stamps the tag and equivalent Python version into the published `install.ps1`; the release asset is the version-bound installer, not another routing bootstrap. A published installer only installs its own version and requires any `-Version` argument to match. Its manifest must agree with that version; a custom `TAPL_INSTALL_MANIFEST_URL` does not bypass release binding. An unstamped developer template requires an explicit version/manifest for a new installation and never silently selects latest.

The bootstrap validates options and downloaded PowerShell syntax/declared parameter support, refusing recursion into another bootstrap. The installer validates the manifest and wheel SHA-256 before activating a candidate installation and records channel/semantic metadata for updates. Installer-managed updates preserve these choices. Integration removal (`taplctl uninstall user` or `repo`) and executable removal (`-Uninstall`) are separate; workflow/configuration data is preserved unless a corresponding purge was explicitly requested. Full usage is in [Installation](../getting-started/installation.md).

<a id="macos-signing"></a>

## macOS signing

The release jobs sign Mach-O files inside **both macOS MCP runtime wheelhouses** using **Developer ID Application**. Native dependencies such as `pydantic_core` and `cryptography` are included. The pure-Python TAPL wheel and generated console scripts are not Mach-O executables.

### One-time setup

1. Add a paid Apple Developer team in Xcode Settings → Accounts → Manage Certificates and create a **Developer ID Application** certificate. Apple Development, Apple Distribution, and Developer ID Installer are different certificate types.
2. In Keychain Access → My Certificates, confirm the identity includes its private key, then export it as a password-protected `.p12` kept outside the repository.
3. Configure repository Actions values:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Secret | `MACOS_CERTIFICATE_P12_BASE64` | Base64 `.p12` containing the certificate/private key. |
   | Secret | `MACOS_CERTIFICATE_PASSWORD` | Export password. |
   | Variable | `APPLE_TEAM_ID` | Ten-character Apple Developer Team ID. |

   With authenticated GitHub CLI, register credentials locally without printing them:

   ```sh
   base64 -i /absolute/path/DeveloperIDApplication.p12 | \
     gh secret set MACOS_CERTIFICATE_P12_BASE64 --repo qkdxorjs1002/tapl
   gh secret set MACOS_CERTIFICATE_PASSWORD --repo qkdxorjs1002/tapl
   gh variable set APPLE_TEAM_ID --repo qkdxorjs1002/tapl --body YOURTEAMID
   ```

   Enter the password at the prompt, not in the command. These libraries need no provisioning profile.
4. Check `security find-identity -v -p codesigning`. Require a valid `Developer ID Application: … (TEAMID)` identity, not just a public certificate. CI's `.p12` must contain exactly one matching identity for `APPLE_TEAM_ID`.

### Signing and Homebrew verification

Each architecture job imports the identity into a temporary keychain, adds it to the keychain search list, and signs all runtime Mach-O files with secure timestamps and hardened runtime. Repacking updates wheel `RECORD` hashes and removes obsolete upstream `RECORD.jws`/`RECORD.p7s` signatures. It unpacks the repacked wheels again to verify hashes/signatures; pure-Python wheels remain byte-for-byte unchanged. Exit cleanup restores the search list and removes the temporary keychain/`.p12`, including failure paths. Only completed runtime archives are uploaded as intermediate artifacts.

The Ubuntu job waits for successful signing and computes release/Homebrew hashes from the exact signed archive bytes. Missing credentials, incorrect identity, or failed signatures stop release publication; there is no unsigned fallback. Existing release assets change only through publication, not a workflow merge or revert.

Generated Homebrew formulas use `preserve_rpath`: signed native libraries' `@rpath` dylib IDs must survive installation without path rewriting/ad-hoc re-signing. They install prebuilt wheels into a virtual environment with `--no-index --no-deps --no-compile`. Both architectures undergo real Homebrew install **and reinstall** checks before publication. The checks compare installed Mach-O bytes with the signed wheels, verify Developer ID authority, Team ID, timestamp and runtime flag, and run installed MCP. Ad-hoc signature validity alone is insufficient. The separate [macOS Homebrew workflow](../../.github/workflows/macos-homebrew.yml) can repeat preservation checks with published runtimes.

Successful signing verification reports `Verified Developer ID signatures on N Mach-O files.` To inspect a downloaded runtime, extract the archive and unpack a native wheel with `python -m wheel unpack`, then run:

```sh
codesign --verify --strict --all-architectures /path/to/unpacked/native-library.so
codesign --display --verbose=4 /path/to/unpacked/native-library.so
```

Check `Authority=Developer ID Application: …`, intended `TeamIdentifier`, `Timestamp`, and `runtime`. This is **code signing**, not Apple notarization: no notary submission or notarized/Gatekeeper-approved distribution is claimed. Independently fetched pip/semantic dependencies, external interpreters/executables, and dependencies fetched by standalone installation are outside the signed wheelhouse scope.

<a id="vscode-marketplace"></a>

## VS Code Marketplace

Stable tags publish **`paragonnov.tapl-workflow-viewer`** after the release job validates the VSIX. Alpha/beta/RC tags retain GitHub Release VSIX assets and skip Marketplace publication. Authentication uses GitHub OIDC directly with Marketplace Trusted Publishing. No Azure subscription, Entra application, `azure/login`, `AZURE_*` secrets, or Marketplace PAT is required.

The extension icon at `vscode-extension/resources/icon.png` is derived from `assets/readme/tapl-logo.png`. Keep both dimensions at or below **1024 pixels**, preserving the logo's aspect ratio and transparency. Release preflight checks the PNG referenced by the extension manifest before building; a successful local VSIX build alone does not establish Marketplace acceptance.

### One-time setup

1. Open publisher **`paragonnov`** in [Marketplace publisher management](https://marketplace.visualstudio.com/manage/publishers/), select **Trusted Publishing**, expand **Create**, and register a policy:

   | Field | Value |
   | --- | --- |
   | Policy name | A descriptive name, such as `TAPL release`. |
   | Repository owner | `qkdxorjs1002` |
   | Repository | `tapl` |
   | Workflow | `release.yml` (filename under `.github/workflows`). |
   | Environment | `vscode-marketplace` |

2. Create the GitHub environment **`vscode-marketplace`** and restrict deployment branches/tags to trusted release refs. The publishing job must reference that exact environment and grant `contents: read` and `id-token: write`; [the release workflow](../../.github/workflows/release.yml) declares these settings.
3. For a private repository, complete the first successful token exchange within 48 hours of creating the policy to activate it permanently. See [Microsoft's Trusted Publishing setup](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#publish-with-github-actions-and-trusted-publishing).

The Marketplace job downloads the validated stable VSIX artifact and runs `vsce publish --oidc --packagePath ... --skip-duplicate`. Duplicate versions count as successful on rerun. The repository uses `@vscode/vsce` `^4.1.0` with Node.js 22 or later. After `npm install --package-lock=false --ignore-scripts` in `vscode-extension`, inspect the installed CLI without publishing:

```sh
npx --no-install vsce --version
npx --no-install vsce publish --help
```

If `--oidc` is unknown, check the installed version and lockfile. For token acquisition failures, check the job's `id-token: write` permission. For exchange failures or `401`/`403`, compare the policy's publisher, repository owner/name, workflow filename, and environment with the running job. [The CLI's Trusted Publishing documentation](https://github.com/microsoft/vscode-vsce#trusted-publishing) describes the token exchange; authentication errors stop publication without a PAT fallback.

Local help and workflow contract tests check CLI support and configuration. Actual token exchange and publisher authorization require a run of the configured publishing job in GitHub Actions; local checks do not verify them.

## Validation and related pages

Version conversion, generated Windows assets, workflow contracts, Homebrew updates, and signing behavior have tests under `tapl/tests`, including `test_release_version.py`, `test_release_packaging.py`, `test_installer_bootstrap.py`, `test_installer_windows.py`, `test_homebrew_macos.py`, and `test_macos_signing.py`. Platform CI adds real install/runtime checks. Source-only tests do not establish that credentials are provisioned or that a release was published.

- [Contributing](contributing.md): local checks and platform verification boundaries.
- [Architecture](architecture.md): package, runtime, and Viewer responsibilities.
- [Troubleshooting](../guides/troubleshooting.md): end-user runtime and connection failures.
