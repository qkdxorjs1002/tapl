# macOS release signing

The release workflow signs Mach-O files inside both macOS MCP runtime archives
(`macos-arm64` and `macos-x86_64`) with an Apple **Developer ID Application**
certificate. This includes native dependency libraries such as `pydantic_core`
and `cryptography`. The platform-independent TAPL Python wheel and its generated
console scripts are not Mach-O executables.

## One-time configuration

1. In Xcode Settings → Accounts, add the Apple Developer account, select the
   paid developer team, and open Manage Certificates. Create a **Developer ID
   Application** certificate. An Apple Development, Apple Distribution, or
   Developer ID Installer certificate is not a substitute.
2. In Keychain Access → My Certificates, confirm that the certificate has an
   associated private key. Export that identity as a password-protected `.p12`.
   Keep the file outside this repository.
3. In this repository's Settings → Secrets and variables → Actions, configure:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Secret | `MACOS_CERTIFICATE_P12_BASE64` | Base64-encoded `.p12` containing the certificate and private key |
   | Secret | `MACOS_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` |
   | Variable | `APPLE_TEAM_ID` | The 10-character Team ID from Apple Developer membership details |

   The certificate can be registered without printing it or copying it into a
   chat. With an authenticated GitHub CLI, run locally:

   ```sh
   base64 -i /absolute/path/DeveloperIDApplication.p12 | \
     gh secret set MACOS_CERTIFICATE_P12_BASE64 --repo qkdxorjs1002/tapl
   gh secret set MACOS_CERTIFICATE_PASSWORD --repo qkdxorjs1002/tapl
   gh variable set APPLE_TEAM_ID --repo qkdxorjs1002/tapl --body YOURTEAMID
   ```

   Enter the export password at the GitHub CLI prompt. Do not put it directly
   in the shell command. No provisioning profile is needed for these libraries.

4. Check the local identity with `security find-identity -v -p codesigning`.
   There must be a valid `Developer ID Application: … (TEAMID)` identity, not
   merely an installed public certificate. The `.p12` used by CI must contain
   exactly one matching identity for `APPLE_TEAM_ID`.

## Release behavior

The normal release tag trigger runs a macOS job for each architecture. Each job
downloads the runtime wheels, imports the identity into a temporary keychain,
signs all Mach-O files with a secure timestamp and hardened runtime, and checks
their signatures. Repacking updates wheel `RECORD` hashes and removes obsolete
upstream `RECORD.jws`/`RECORD.p7s` signatures. The repacked wheels are unpacked
again to verify their hashes and final native signatures. Pure Python wheels
are preserved byte for byte.

The temporary keychain is added to the user's keychain search list while
signing so `codesign` can locate its identity. The original search list is
restored, and the temporary keychain and `.p12` are removed on exit, including
failure paths.
GitHub-hosted macOS runners provide the signing environment. Only completed
runtime archives are uploaded as intermediate artifacts.

The Ubuntu release job waits for macOS signing to succeed, downloads the signed
archives, and computes the release/Homebrew SHA-256 values from those exact
bytes. Missing credentials, an incorrect identity, or signing failure stops the
release. There is no unsigned fallback. Set the three configuration values
before creating the next release tag.

Existing release assets are not changed by merging this workflow. New tags use
the new signing path. Reverting the signing change restores the previous build
pipeline; it does not alter already published assets.

## Homebrew signature preservation

Generated formulas use Homebrew's `preserve_rpath` directive. The signed native
wheel libraries use `@rpath` dylib IDs; preserving those IDs prevents Homebrew
from rewriting them to installation-specific paths and replacing Developer ID
signatures with ad-hoc signatures. Installation still creates a Python virtual
environment and installs the prebuilt wheels with `--no-index --no-deps
--no-compile`; it does not compile or re-sign the native libraries locally.

Both macOS architectures are checked with a real Homebrew installation before
release publication. The check compares every installed runtime Mach-O file
with its signed wheel bytes and verifies its Developer ID authority, Team ID,
timestamp, and hardened runtime. It also repeats verification after reinstall
and runs the installed MCP runtime. A valid ad-hoc signature is not sufficient.
This protects the signed MCP runtime; separately fetched semantic dependencies
remain outside that signing scope.

## Verification and boundaries

Successful jobs print `Verified Developer ID signatures on N Mach-O files.`
To inspect a downloaded runtime, extract its tarball, unpack a native wheel
with `python -m wheel unpack`, then run:

```sh
codesign --verify --strict --all-architectures /path/to/unpacked/native-library.so
codesign --display --verbose=4 /path/to/unpacked/native-library.so
```

Confirm `Authority=Developer ID Application: …`, the intended `TeamIdentifier`,
`Timestamp`, and the `runtime` flag. CI verifies both architectures' signatures;
the existing runtime execution smoke test covers Linux x86_64.

**Code signing is separate from Apple notarization.** This workflow does not
submit packages to Apple's notary service and does not claim notarized or
Gatekeeper-approved distribution. Notarization requires separate credentials
and a submission step. Dependencies fetched independently by `install.sh`,
`pip`, or optional semantic dependency installation are outside the signed
release wheelhouse. Apple's Python interpreter and other external executables
are also outside this signing scope.

References: [Apple Developer ID signing](https://developer.apple.com/documentation/xcode/creating-distribution-signed-code-for-the-mac/),
[GitHub certificate setup](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications),
and [wheel format and RECORD](https://packaging.python.org/en/latest/specifications/binary-distribution-format/).
