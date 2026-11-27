# Releases

[Documentation](../README.md) · [한국어](releases.ko.md)

TAPL releases `taplctl` and the VS Code Viewer extension separately. The CLI includes the browser Viewer, and the VS Code extension has its own VSIX and Marketplace version. See [Installation](../getting-started/installation.md) and [VS Code Viewer](../guides/vscode.md) for end-user updates.

## Tags and injected versions

| Product | Example tag | Published packages |
| --- | --- | --- |
| [taplctl](../../.github/workflows/release-ctl.yml) | `2.25.6`, `2.25.6-beta1` | Python wheel, runtimes, installers and Homebrew |
| [VS Code Viewer](../../.github/workflows/release.yml) | `viewer-2.26.0`, `viewer-2.26.0-beta1` | VSIX on GitHub, plus Marketplace for stable Viewer tags |

Choose the next version from each product's own published versions. Numeric ctl tags preserve existing installer URLs. `taplctl` applies the PEP 440 equivalent to Python package metadata and uses the original ctl tag for the bundled browser Viewer. Viewer tags use their SemVer suffix for the extension manifest and VSIX filename. Both support `alphaN`, `betaN` and `rcN` suffixes. Omit the leading `v` and build metadata. [Tag parser](../../.github/scripts/release_version.py)

Use a ctl tag for runtime, hooks, CLI, installer, Viewer server, and shared Viewer UI changes. VS Code loads that UI from the installed ctl. Use a Viewer tag for changes to the native VS Code host, extension manifest, or packaged extension resources. When both channels change, verify compatibility with the previous ctl, publish the ctl release first, then publish the extension separately.

The Viewer workflow compares extension release inputs with the previous published Viewer release in the same stable or prerelease channel. During the transition, it falls back to an earlier stable numeric release carrying a VSIX. With no baseline, the first release compares against an empty tree. Edits limited to the shared UI, tests, generated bundles or the manifest version do not trigger a new extension publication. GitHub Latest is reserved for stable ctl installers. [Viewer release planner](../../.github/scripts/viewer_release.py)

The VSIX keeps a bundled UI for compatibility with older ctl installs. Verify an extension host change with one VSIX and both a compatible ctl and a previous ctl that uses the fallback. To verify a shared UI update, keep the VSIX installed, switch the ctl build, reopen the dashboard, and check the loaded version, workspace, and host theme. [Viewer stdio contract](../reference/mcp.md#viewer-stdio)

For an authorized publication, tag the reviewed commit using the appropriate channel. These are example versions.

```sh
git tag -a 2.25.6 -m "taplctl 2.25.6"
git push origin refs/tags/2.25.6

git tag -a viewer-2.26.0 -m "TAPL Viewer 2.26.0"
git push origin refs/tags/viewer-2.26.0
```

You can check ctl version conversion locally without publishing.

```sh
python3 .github/scripts/release_version.py 2.0.1-beta4
# version=2.0.1-beta4
# python_version=2.0.1b4
# prerelease=true
```

## Build and publication flow

The ctl workflow runs these independent checks and artifact producers concurrently:

- Windows installer fixtures use a Python 3.11/3.12 matrix for PowerShell 5.1 parsing, bootstrap tests, and stdlib-only installer fixtures.
- Windows runtime preflight uses a separate Python 3.11/3.12 matrix for runtime regressions, version-bound installer assets, a real wheel build, and install/update/reinstall/uninstall plus CLI/MCP smoke checks.
- `build-packages` uses Python 3.12 and Node.js 22, injects the Python and browser Viewer versions, tests the shared Viewer code, and builds the application wheel.
- Linux runtime jobs build arm64/x86_64 wheelhouses in a matrix. The macOS arm64/x86_64 matrix signs runtime wheelhouses and verifies real Homebrew install/reinstall before uploading signed artifacts.

The Ubuntu `release` job waits for every check and producer to succeed. It downloads the exact versioned wheel and runtime archives, prepares installers/manifest, and validates asset bytes, versions, exact URLs, SHA-256 values, required runtime distributions, and rendered Windows installer contents. An isolated Linux x86_64 venv smoke verifies the installed version and native MCP tool inventory/status. The Homebrew token guard must also pass before GitHub Release publication. The three additional wheelhouses for Homebrew use dependencies verified against the lockfile. Release CI verifies the pinned model files and shares them with each check. Both models must pass indexing and search checks on Windows x64, Linux x64 and ARM64, and macOS ARM64 before publication.

| Asset | Purpose |
| --- | --- |
| `taplctl-PYTHON_VERSION-py3-none-any.whl` | Platform-independent TAPL application package. |
| `taplctl-mcp-runtime-TAG-macos-arm64.tar.gz` | Signed macOS arm64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-macos-x86_64.tar.gz` | Signed macOS x86_64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-arm64.tar.gz` | Linux arm64 MCP dependency wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-x86_64.tar.gz` | Linux x86_64 MCP dependency wheelhouse. |
| `taplctl-semantic-runtime-TAG-macos-arm64.tar.gz` | Signed Apple Silicon semantic dependency wheelhouse. |
| `taplctl-semantic-runtime-TAG-linux-arm64.tar.gz`, `taplctl-semantic-runtime-TAG-linux-x86_64.tar.gz` | Linux semantic dependency wheelhouses. |
| `taplctl-install-manifest.json` | Schema version 1, Python version, wheel URL, and wheel SHA-256. |
| `install.ps1`, `install.cmd` | Windows release assets; the PowerShell installer is stamped for that release. |

`PYTHON_VERSION` and `TAG` above are naming placeholders, including their different prerelease syntax. The manifest does not list every runtime archive; release/Homebrew runtime URL/hash metadata is computed separately from the final asset bytes. A Windows wheelhouse is not among these tarball targets.

The workflow creates or updates the tagged GitHub Release and uploads the validated assets (`--clobber` on an existing release). Prereleases are marked explicitly. Homebrew updates after the ctl GitHub Release succeeds. Re-running can replace same-tag assets, so review the concrete source and generated contents before publication.

## Homebrew channels

`HOMEBREW_TAP_TOKEN` is required with write access to `qkdxorjs1002/homebrew-tap` and is checked before GitHub publication. The downstream `homebrew` job depends on `release`, then checks out the tap, updates formulas, and commits/pushes changes. It uses the existing `Formula/taplctl.rb` as the template and updates `Formula/taplctl-pre.rb` plus `Aliases/taplctl@pre` on releases. Stable releases update `taplctl.rb` and the name migration metadata. The workflow removes `taplctl-semantic.rb` and maps its name to `taplctl` in `formula_renames.json`. The updater skips a version older than the formula's current version and validates generated Ruby syntax before committing/pushing the tap.

The two formulas conflict because they provide the same commands. Runtime wheelhouse URLs and checksums select the matching macOS/Linux architecture. Viewer services use port 8000; the Homebrew formulas do not automatically start `searchd`. See [Viewer services](../guides/viewer.md#run-as-a-homebrew-service).

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

The release jobs sign Mach-O files in both macOS MCP wheelhouses and the macOS ARM64 semantic wheelhouse with **Developer ID Application**. The pure-Python TAPL wheel and generated console scripts contain no Mach-O executables.

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

Each architecture job imports the identity into a temporary keychain, adds it to the keychain search list, and signs all runtime Mach-O files with secure timestamps and hardened runtime. Repacking updates wheel `RECORD` hashes and removes obsolete upstream `RECORD.jws`/`RECORD.p7s` signatures. It unpacks the repacked wheels again to verify hashes/signatures; pure-Python wheels remain byte-for-byte unchanged. Exit cleanup restores the search list and removes the temporary keychain/`.p12`, including failure paths. Runtime archives are uploaded as intermediate artifacts only after signing and the Homebrew install/reinstall checks succeed.

The `release` job waits for every runtime matrix to succeed and computes release/Homebrew hashes from the exact downloaded archive bytes, including the signed macOS archives. Missing credentials, incorrect identity, or failed signatures stop release publication; there is no unsigned fallback. Existing release assets change only through publication, not a workflow merge or revert.

Generated Homebrew formulas use `preserve_rpath`: signed native libraries' `@rpath` dylib IDs must survive installation without path rewriting/ad-hoc re-signing. They install prebuilt wheels into a virtual environment with `--no-index --no-deps --no-compile`. Both architectures undergo real Homebrew install **and reinstall** checks before publication. The checks compare installed Mach-O bytes with the signed wheels, verify Developer ID authority, Team ID, timestamp and runtime flag, and run installed MCP. Ad-hoc signature validity alone is insufficient. The separate [macOS Homebrew workflow](../../.github/workflows/macos-homebrew.yml) can repeat preservation checks with published runtimes.

Successful signing verification reports `Verified Developer ID signatures on N Mach-O files.` To inspect a downloaded runtime, extract the archive and unpack a native wheel with `python -m wheel unpack`, then run:

```sh
codesign --verify --strict --all-architectures /path/to/unpacked/native-library.so
codesign --display --verbose=4 /path/to/unpacked/native-library.so
```

Check `Authority=Developer ID Application: …`, intended `TeamIdentifier`, `Timestamp`, and `runtime`. This is **code signing**, not Apple notarization: no notary submission or notarized/Gatekeeper-approved distribution is claimed. Independently fetched pip/semantic dependencies, external interpreters/executables, and dependencies fetched by standalone installation are outside the signed wheelhouse scope.

<a id="vscode-marketplace"></a>

## VS Code Marketplace

Stable `viewer-*` tags publish **`paragonnov.tapl-workflow-viewer`** after the Viewer GitHub Release is published. The Viewer release contains only the VSIX and is excluded from GitHub Latest. Viewer alpha, beta and RC tags publish the VSIX on GitHub. Authentication uses GitHub OIDC directly with Marketplace Trusted Publishing. No Azure subscription, Entra application, `azure/login`, `AZURE_*` secrets, or Marketplace PAT is required.

The extension icon at `vscode-extension/resources/icon.png` is derived from `assets/readme/tapl-logo.png`. Keep both dimensions at or below **1024 pixels**, preserving the logo's aspect ratio and transparency. Publication requires the release preflight check of the PNG referenced by the extension manifest; a successful local VSIX build alone does not establish Marketplace acceptance.

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

The Marketplace job downloads the VSIX from the stable Viewer GitHub Release and runs `vsce publish --oidc --packagePath ... --skip-duplicate`. Duplicate versions count as successful on rerun. The repository uses `@vscode/vsce` `^4.1.0` with Node.js 22 or later. After `npm install --package-lock=false --ignore-scripts` in `vscode-extension`, inspect the installed CLI without publishing:

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
