# 릴리스

[문서 홈](../README.ko.md) · [English](releases.md)

TAPL은 `taplctl`과 VS Code Viewer 확장을 별도로 배포합니다. CLI에는 브라우저 Viewer가 포함되고 VS Code 확장은 자체 VSIX와 Marketplace 버전을 사용합니다. 사용자 업데이트 절차는 [설치](../getting-started/installation.ko.md)와 [VS Code Viewer](../guides/vscode.ko.md)를 참고하세요.

## 태그와 버전 주입

| 제품 | 태그 예시 | 게시 대상 |
| --- | --- | --- |
| [taplctl](../../.github/workflows/release-ctl.yml) | `2.25.6`, `2.25.6-beta1` | Python wheel, 런타임, 설치기, Homebrew |
| [VS Code Viewer](../../.github/workflows/release.yml) | `viewer-2.26.0`, `viewer-2.26.0-beta1` | GitHub VSIX, 안정판은 Marketplace에도 게시 |

각 제품의 기존 배포 버전을 기준으로 다음 버전을 정합니다. ctl은 기존 숫자 태그로 설치 URL을 유지합니다. Python 패키지 메타데이터에는 PEP 440 버전을, 포함된 브라우저 Viewer에는 원래 ctl 태그를 주입합니다. Viewer 태그는 `viewer-` 뒤의 SemVer를 확장 manifest와 VSIX 파일명에 사용합니다. 두 채널은 `alphaN`, `betaN`, `rcN` 접미사를 지원합니다. 앞에 붙이는 `v`와 빌드 메타데이터는 생략합니다. [태그 파서](../../.github/scripts/release_version.py)

런타임, 훅, CLI, 설치기, Viewer 서버, 공용 Viewer UI가 바뀌면 ctl 태그를 사용합니다. VS Code는 설치된 ctl의 UI를 불러옵니다. VS Code 호스트, 확장 manifest 또는 확장 패키지 자원이 바뀌면 Viewer 태그를 사용합니다. 두 채널 모두 변경되면 이전 ctl과의 호환성을 확인하고 ctl을 먼저 게시한 뒤 확장을 별도로 게시합니다.

Viewer 워크플로는 같은 안정판 또는 프리릴리스 채널의 직전 게시본과 확장 배포 입력을 비교합니다. 분리 전환기에는 VSIX가 포함된 기존 숫자 태그 안정판을 기준으로 삼습니다. 기준 게시본이 없으면 빈 트리와 비교합니다. 공용 UI, 테스트, 생성된 번들, manifest의 버전 번호만 바뀐 경우에는 확장을 새로 게시하지 않습니다. GitHub Latest는 ctl 안정판 설치기에 사용합니다. [Viewer 릴리스 판정 코드](../../.github/scripts/viewer_release.py)

VSIX는 이전 ctl과의 호환을 위해 UI 사본을 포함합니다. VS Code 호스트를 변경하면 같은 VSIX로 설치형 Viewer를 지원하는 ctl과 호환 Viewer를 사용하는 이전 ctl을 각각 검증합니다. 공용 UI 변경은 VSIX를 설치한 채 ctl 빌드를 바꾸고 대시보드를 다시 열어 로드된 버전, 워크스페이스, 호스트 테마를 확인합니다. [Viewer stdio 계약](../reference/mcp.ko.md#viewer-stdio)

게시 승인을 받은 경우 검토한 커밋에 해당 채널의 태그를 붙입니다. 아래 버전은 예시입니다.

```sh
git tag -a 2.25.6 -m "taplctl 2.25.6"
git push origin refs/tags/2.25.6

git tag -a viewer-2.26.0 -m "TAPL Viewer 2.26.0"
git push origin refs/tags/viewer-2.26.0
```

게시 없이 로컬에서 ctl 버전 변환을 확인할 수 있습니다.

```sh
python3 .github/scripts/release_version.py 2.0.1-beta4
# version=2.0.1-beta4
# python_version=2.0.1b4
# prerelease=true
```

## 빌드와 게시 흐름

ctl 워크플로는 다음 독립 검사와 자산 생성 작업을 병렬로 실행합니다.

- Windows 설치기 fixture는 Python 3.11/3.12 matrix로 PowerShell 5.1 구문 검사, bootstrap 테스트, stdlib-only 설치기 fixture를 실행합니다.
- Windows 런타임 사전 검사는 별도 Python 3.11/3.12 matrix로 런타임 회귀, 버전이 고정된 설치기 파일 검사, 실제 wheel 빌드, 설치·업데이트·재설치·제거와 CLI·MCP smoke를 수행합니다.
- `build-packages`는 Python 3.12·Node.js 22를 사용해 Python과 브라우저 Viewer의 버전을 주입하고 공유 Viewer를 검증한 뒤 애플리케이션 wheel을 빌드합니다.
- Linux 런타임 job은 arm64/x86_64 matrix로 wheelhouse를 빌드합니다. macOS arm64/x86_64 matrix는 런타임 wheelhouse에 서명하고 실제 Homebrew 설치·재설치를 검증한 뒤 서명 artifact를 올립니다.

Ubuntu `release` job은 모든 검사와 생성 job의 성공을 기다립니다. 정확한 버전별 wheel·런타임 아카이브를 내려받아 설치기·manifest를 준비하고 자산 바이트·버전·정확한 URL·SHA-256·필수 런타임 distribution·렌더링된 Windows 설치기를 검증합니다. 격리 Linux x86_64 venv smoke는 설치 버전과 native MCP 도구 목록·상태를 검증합니다. GitHub Release 게시 전에 Homebrew 토큰 검사도 통과해야 합니다. Homebrew용 세 의미 검색 wheelhouse에는 잠금 파일의 해시를 검증한 의존성이 들어갑니다. 릴리스 CI는 고정 모델 파일의 체크섬을 확인한 뒤 각 검증 작업에 전달합니다. GitHub 게시 전에 Windows x64·Linux x64 및 ARM64·macOS ARM64에서 두 모델을 색인하고 검색합니다.

| 자산 | 용도 |
| --- | --- |
| `taplctl-PYTHON_VERSION-py3-none-any.whl` | 플랫폼 독립 TAPL 애플리케이션 패키지. |
| `taplctl-mcp-runtime-TAG-macos-arm64.tar.gz` | 서명된 macOS arm64 MCP 의존성 wheelhouse. |
| `taplctl-mcp-runtime-TAG-macos-x86_64.tar.gz` | 서명된 macOS x86_64 MCP 의존성 wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-arm64.tar.gz` | Linux arm64 MCP 의존성 wheelhouse. |
| `taplctl-mcp-runtime-TAG-linux-x86_64.tar.gz` | Linux x86_64 MCP 의존성 wheelhouse. |
| `taplctl-semantic-runtime-TAG-macos-arm64.tar.gz` | 서명된 Apple Silicon 의미 검색 의존성 wheelhouse. |
| `taplctl-semantic-runtime-TAG-linux-arm64.tar.gz`, `taplctl-semantic-runtime-TAG-linux-x86_64.tar.gz` | Linux 의미 검색 의존성 wheelhouse. |
| `taplctl-install-manifest.json` | Schema version 1, Python 버전, wheel URL·SHA-256. |
| `install.ps1`, `install.cmd` | Windows 릴리스 자산. PowerShell 설치기에 해당 릴리스 버전을 주입합니다. |

위 `PYTHON_VERSION`·`TAG`는 이름 자리표시자이며 prerelease 표기가 서로 다릅니다. Manifest에는 모든 런타임 아카이브가 들어 있지 않습니다. 릴리스·Homebrew용 런타임 URL·해시는 최종 자산 바이트에서 별도로 계산합니다. 위 tarball 대상에 Windows wheelhouse는 없습니다.

Workflow는 태그의 GitHub Release를 만들거나 갱신하고 검증한 자산을 올립니다. 기존 릴리스에서는 `--clobber`를 사용합니다. Prerelease 여부는 명시적으로 지정합니다. ctl GitHub Release 게시에 성공하면 Homebrew를 갱신합니다. 재실행은 같은 태그 자산을 교체할 수 있으므로 게시 전에 구체적 소스와 생성 내용을 검토하세요.

## Homebrew 채널

`qkdxorjs1002/homebrew-tap` 쓰기 권한을 가진 `HOMEBREW_TAP_TOKEN`이 필요하며 GitHub 게시 전에 확인합니다. 후속 `homebrew` job은 `release`에 의존하며 tap을 checkout한 뒤 formula를 갱신하고 변경을 commit·push합니다. 기존 `Formula/taplctl.rb`를 템플릿으로 사용하고 릴리스 시 `Formula/taplctl-pre.rb`와 `Aliases/taplctl@pre`를 갱신합니다. 정식 릴리스만 `taplctl.rb`와 이름 이전 메타데이터를 갱신합니다. 기존 `taplctl-semantic.rb`는 제거하고 `formula_renames.json`에 `taplctl`로 이전하는 항목을 둡니다. Updater는 현재 formula보다 오래된 버전을 건너뛰며 생성 Ruby 구문을 검사한 뒤 tap에 commit·push합니다.

두 formula는 같은 명령을 제공하므로 서로 충돌합니다. 런타임 wheelhouse URL·체크섬은 macOS·Linux 아키텍처에 맞게 선택합니다. Viewer 서비스는 8000 포트를 사용하며 Homebrew formula도 `searchd`를 자동 시작하지 않습니다. [Viewer 서비스](../guides/viewer.ko.md#homebrew-서비스로-실행)를 보세요.

## Windows 진입 스크립트와 릴리스 설치기

저장소 최상위 `install.ps1`은 **라우팅 bootstrap**이며 `install.cmd`는 CMD 진입점입니다. 릴리스를 선택한 뒤 그 릴리스의 설치기를 내려받습니다.

- 채널 옵션 없음: GitHub의 최신 정식 릴리스 자산.
- `-Pre`: 게시 시각 기준으로 가장 최근인 유효한 공개 릴리스. Prerelease와 더 최근 정식 릴리스 모두 대상입니다.
- `-Version TAG`: 정확한 릴리스. `-Pre`와 조합할 수 없습니다.
- `-Semantic`, `-Reinstall`, `-Uninstall`: 선택한 설치기가 지원하면 전달합니다.

소스 `.github/scripts/install-windows.ps1`은 개발용 템플릿입니다. [`prepare_windows_installers.py`](../../.github/scripts/prepare_windows_installers.py)가 게시할 `install.ps1`에 태그와 대응 Python 버전을 넣습니다. 릴리스 자산은 또 다른 bootstrap이 아닌 버전 고정 설치기입니다. 게시한 설치기는 자기 버전만 설치하며 `-Version`을 지정해도 해당 릴리스와 일치해야 합니다. Manifest도 같은 버전이어야 하며 `TAPL_INSTALL_MANIFEST_URL`로 사용자 manifest를 골라도 버전 고정을 우회하지 않습니다. 버전을 넣지 않은 개발 템플릿은 새 설치 시 버전·manifest를 명시해야 하며 조용히 latest를 고르지 않습니다.

Bootstrap은 옵션, 내려받은 PowerShell 구문과 선언된 인자 지원을 검증하고 다른 bootstrap으로 재귀 실행하는 것을 거부합니다. 설치기는 후보 설치를 활성화하기 전에 manifest·wheel SHA-256을 검사하고 채널·semantic 메타데이터를 기록합니다. 설치기 관리 업데이트는 이 선택을 보존합니다. 연결 제거(`taplctl uninstall user` 또는 `repo`)와 실행 파일 제거(`-Uninstall`)는 별도이며 해당 purge를 명시적으로 요청하지 않으면 워크플로·설정 데이터는 유지합니다. 전체 사용법은 [설치](../getting-started/installation.ko.md)를 보세요.

<a id="macos-signing"></a>

## macOS 서명

릴리스 job은 두 macOS MCP wheelhouse와 macOS ARM64 의미 검색 wheelhouse의 Mach-O 파일을 **Developer ID Application**으로 서명합니다. 순수 Python TAPL wheel과 생성된 콘솔 스크립트에는 Mach-O 실행 파일이 없습니다.

### 최초 설정

1. Xcode Settings → Accounts → Manage Certificates에서 유료 Apple Developer 팀을 추가하고 **Developer ID Application** 인증서를 생성합니다. Apple Development·Apple Distribution·Developer ID Installer와는 다른 종류입니다.
2. Keychain Access → My Certificates에서 개인 키를 포함한 identity인지 확인하고 비밀번호로 보호한 `.p12`로 내보냅니다. 파일은 저장소 밖에 보관합니다.
3. 저장소 Actions 값을 설정합니다.

   | 종류 | 이름 | 값 |
   | --- | --- | --- |
   | Secret | `MACOS_CERTIFICATE_P12_BASE64` | 인증서·개인 키를 포함한 `.p12`의 Base64. |
   | Secret | `MACOS_CERTIFICATE_PASSWORD` | 내보내기 비밀번호. |
   | Variable | `APPLE_TEAM_ID` | 10자리 Apple Developer Team ID. |

   인증된 GitHub CLI로 값을 출력하지 않고 로컬에서 등록합니다.

   ```sh
   base64 -i /absolute/path/DeveloperIDApplication.p12 | \
     gh secret set MACOS_CERTIFICATE_P12_BASE64 --repo qkdxorjs1002/tapl
   gh secret set MACOS_CERTIFICATE_PASSWORD --repo qkdxorjs1002/tapl
   gh variable set APPLE_TEAM_ID --repo qkdxorjs1002/tapl --body YOURTEAMID
   ```

   비밀번호는 명령에 넣지 말고 프롬프트에 입력합니다. 이 라이브러리에는 provisioning profile이 필요하지 않습니다.
4. `security find-identity -v -p codesigning`으로 확인합니다. 공개 인증서만이 아닌 유효한 `Developer ID Application: … (TEAMID)` identity가 있어야 합니다. CI의 `.p12`에는 `APPLE_TEAM_ID`와 맞는 identity가 정확히 하나 있어야 합니다.

### 서명과 Homebrew 검증

아키텍처별 job은 identity를 임시 keychain에 가져오고 검색 목록에 추가한 뒤 모든 런타임 Mach-O 파일에 secure timestamp·hardened runtime으로 서명합니다. Wheel 재패키징은 `RECORD` 해시를 갱신하고 더 이상 유효하지 않은 upstream `RECORD.jws`·`RECORD.p7s` 서명을 제거합니다. 다시 풀어서 해시·서명을 검증하며 순수 Python wheel은 바이트 그대로 보존합니다. 실패 경로를 포함한 종료 정리는 검색 목록을 복원하고 임시 keychain·`.p12`를 삭제합니다. 서명과 Homebrew 설치·재설치 검사가 성공한 뒤에만 런타임 아카이브를 중간 artifact로 올립니다.

`release` job은 모든 런타임 matrix의 성공을 기다린 뒤 서명된 macOS 아카이브를 포함해 내려받은 정확한 아카이브 바이트로 릴리스·Homebrew 해시를 계산합니다. 자격 증명 누락·잘못된 identity·서명 실패는 게시를 중단하며 서명 없는 fallback은 없습니다. 기존 릴리스 자산은 게시할 때만 바뀌며 workflow 병합·revert 자체로 바뀌지 않습니다.

생성 Homebrew formula는 `preserve_rpath`를 사용합니다. 서명된 native 라이브러리의 `@rpath` dylib ID를 설치 중 경로 변경·ad-hoc 재서명 없이 유지해야 합니다. 미리 빌드한 wheel을 `--no-index --no-deps --no-compile`로 가상 환경에 설치합니다. 게시 전 두 아키텍처 모두 실제 Homebrew **설치·재설치**를 확인합니다. 설치한 Mach-O 바이트를 서명 wheel과 비교하고 Developer ID authority·Team ID·timestamp·runtime flag를 검증하며 설치된 MCP를 실행합니다. Ad-hoc 서명이 유효한 것만으로는 부족합니다. 별도 [macOS Homebrew workflow](../../.github/workflows/macos-homebrew.yml)로 게시 런타임의 보존 검사를 반복할 수 있습니다.

서명 검증 성공 시 `Verified Developer ID signatures on N Mach-O files.`를 출력합니다. 내려받은 런타임을 살펴보려면 아카이브를 풀고 `python -m wheel unpack`으로 native wheel을 푼 뒤 실행합니다.

```sh
codesign --verify --strict --all-architectures /path/to/unpacked/native-library.so
codesign --display --verbose=4 /path/to/unpacked/native-library.so
```

`Authority=Developer ID Application: …`, 의도한 `TeamIdentifier`, `Timestamp`, `runtime`을 확인합니다. 이는 **코드 서명**이며 Apple notarization이 아닙니다. Notary 제출이나 notarized·Gatekeeper 승인 배포를 주장하지 않습니다. 별도로 받은 pip·semantic 의존성, 외부 인터프리터·실행 파일, 독립 설치 과정에서 받은 의존성은 서명 wheelhouse 범위 밖입니다.

<a id="vscode-marketplace"></a>

## VS Code Marketplace

안정판 `viewer-*` 태그는 Viewer GitHub Release 게시 후 **`paragonnov.tapl-workflow-viewer`**를 Marketplace에 게시합니다. Viewer 릴리스에는 VSIX만 포함되며 GitHub Latest에서 제외됩니다. Viewer alpha·beta·RC 태그는 GitHub에 VSIX를 게시합니다. GitHub OIDC로 Marketplace Trusted Publishing에 직접 인증합니다. Azure 구독, Entra application, `azure/login`, `AZURE_*` secret, Marketplace PAT가 필요하지 않습니다.

확장 아이콘 `vscode-extension/resources/icon.png`는 `assets/readme/tapl-logo.png`에서 만듭니다. 로고 비율과 투명도를 유지하면서 가로·세로를 각각 **1024픽셀 이하**로 맞추세요. 게시하려면 릴리스 사전 검사에서 확장 manifest가 참조하는 PNG를 확인해야 합니다. 로컬 VSIX 빌드 성공만으로 Marketplace 승인까지 확인되는 것은 아닙니다.

### 최초 설정

1. [Marketplace publisher 관리](https://marketplace.visualstudio.com/manage/publishers/)에서 publisher **`paragonnov`**를 열고 **Trusted Publishing** → **Create**를 펼쳐 정책을 등록합니다.

   | 필드 | 값 |
   | --- | --- |
   | Policy name | `TAPL release`처럼 용도를 나타내는 이름. |
   | Repository owner | `qkdxorjs1002` |
   | Repository | `tapl` |
   | Workflow | `release.yml` (`.github/workflows` 아래의 파일명). |
   | Environment | `vscode-marketplace` |

2. GitHub environment **`vscode-marketplace`**를 만들고 신뢰할 릴리스 ref만 허용하도록 배포 branch·tag를 제한합니다. 게시 job은 정확히 같은 environment를 참조하고 `contents: read`와 `id-token: write` 권한을 부여해야 합니다. [릴리스 workflow](../../.github/workflows/release.yml)에 이 설정이 선언되어 있습니다.
3. 비공개 저장소는 정책 생성 후 48시간 안에 첫 토큰 교환을 성공해야 정책이 영구 활성화됩니다. [Microsoft의 Trusted Publishing 설정](https://code.visualstudio.com/api/working-with-extensions/publishing-extension#publish-with-github-actions-and-trusted-publishing)을 참고하세요.

Marketplace job은 Viewer 안정판의 GitHub Release에서 VSIX를 받아 `vsce publish --oidc --packagePath ... --skip-duplicate`를 실행합니다. 재실행 시 이미 있는 버전은 성공으로 처리합니다. 저장소는 `@vscode/vsce` `^4.1.0`과 Node.js 22 이상을 사용합니다. `vscode-extension`에서 `npm install --package-lock=false --ignore-scripts`를 실행한 뒤 게시 없이 설치된 CLI를 확인할 수 있습니다.

```sh
npx --no-install vsce --version
npx --no-install vsce publish --help
```

`--oidc`를 알 수 없다는 오류는 설치 버전과 lockfile을 확인합니다. 토큰 요청 실패는 job의 `id-token: write` 권한을 확인합니다. 토큰 교환 실패나 `401`·`403`은 정책의 publisher, 저장소 소유자·이름, workflow 파일명, environment가 실행 중인 job과 일치하는지 확인합니다. [CLI의 Trusted Publishing 문서](https://github.com/microsoft/vscode-vsce#trusted-publishing)에 토큰 교환 동작이 설명되어 있습니다. 인증 오류는 PAT fallback 없이 게시를 중단합니다.

로컬 도움말과 workflow 계약 테스트는 CLI 지원·설정을 확인합니다. 실제 토큰 교환과 publisher 권한은 GitHub Actions의 설정된 게시 job 실행으로 검증해야 하며 로컬 검사로는 확인할 수 없습니다.

## 검증과 관련 문서

버전 변환, Windows 생성 자산, workflow 계약, Homebrew 갱신, 서명 동작은 `tapl/tests`의 `test_release_version.py`, `test_release_packaging.py`, `test_installer_bootstrap.py`, `test_installer_windows.py`, `test_homebrew_macos.py`, `test_macos_signing.py` 등에서 검증합니다. 플랫폼 CI가 실제 설치·런타임 검사를 추가합니다. 소스 테스트만으로 자격 증명 설정이나 릴리스 게시 완료를 입증할 수 없습니다.

- [기여와 검증](contributing.ko.md): 로컬 검사와 플랫폼 검증 범위.
- [아키텍처](architecture.ko.md): 패키지·런타임·Viewer 책임.
- [문제 해결](../guides/troubleshooting.ko.md): 사용자 런타임·연결 오류.
