# 설치

[문서 홈](../README.ko.md) · [English](installation.md)

플랫폼에 맞는 TAPL 실행 파일을 설치한 뒤 [Codex에 연결](integrations.ko.md)합니다. 패키지 설치 방법과 Codex 연결 범위는 별개의 선택입니다. [Agent에게 설치와 연결을 맡길 수도 있습니다](integrations.ko.md#agent에게-tapl-설치-맡기기).

## 요구사항

- `venv`를 포함한 Python 3.11 이상. Homebrew formula는 `python@3.12`를 사용합니다.
- FTS5와 확장 로딩을 지원하는 SQLite.
- Formula 설치에는 Homebrew, Linux 설치에는 `curl`.
- Windows 설치에는 Windows 10/11과 PowerShell 5.1 이상 또는 PowerShell 7.
- 선택 사항인 Viewer에는 브라우저, 확장에는 VS Code.

TAPL wheel은 플랫폼 독립적이지만 의존성에는 호환 wheel이 필요합니다. 드문 아키텍처, 아주 새로운 Python 버전, Alpine 같은 musl 기반 Linux는 로컬 빌드 도구가 필요할 수 있습니다. 소스 개발은 `uv`를 사용합니다. [기여 안내](../development/contributing.ko.md)를 참고하세요.

## macOS와 Homebrew

Tap을 추가한 뒤 formula **하나만** 선택합니다.

```sh
brew tap qkdxorjs1002/tap

# 전문 검색을 포함한 안정 버전
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl

# 또는 시맨틱·벡터 의존성을 포함한 안정 버전
brew trust --formula qkdxorjs1002/tap/taplctl-semantic
brew install taplctl-semantic

# 또는 프리릴리즈를 포함한 가장 최근 공개 릴리스
brew trust --formula qkdxorjs1002/tap/taplctl-pre
brew install taplctl-pre
```

`taplctl`과 `taplctl-semantic`은 안정 릴리스를 따릅니다. `taplctl-pre`는 가장 최근 공개된 릴리스를 선택하므로 안정 버전이나 프리릴리즈일 수 있습니다. `taplctl@pre`는 별칭입니다. Trust와 prefix 조회에는 위의 정식 formula 이름을 사용하세요.

세 formula 모두 `taplctl`, `tapl-mcp`, `tapl-hook`을 제공하므로 함께 설치할 수 없습니다. 전환 전에는 `brew uninstall taplctl`처럼 현재 formula를 제거하세요. Formula는 설치 시 PyPI에서 패키지를 해석하지 않고 릴리스에 고정된 wheel 묶음을 사용합니다.

## Linux

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

독립 설치 스크립트는 최신 안정 릴리스를 선택합니다. `curl`, `venv`를 포함한 Python 3.11 이상, 설치 디렉터리 쓰기 권한이 필요합니다. 기본 설치 위치는 `${XDG_DATA_HOME:-$HOME/.local/share}/tapl`, 명령 링크 위치는 `${XDG_BIN_HOME:-$HOME/.local/bin}`입니다.

`TAPL_INSTALL_ROOT`와 `TAPL_BIN_DIR`로 위치를 지정할 수 있으며, 지정하지 않으면 해당 XDG 변수가 적용됩니다. 스크립트는 필요한 `PATH` export를 출력하지만 셸 시작 파일을 수정하거나 Codex hook을 설치하지 않습니다. 출력된 설정을 적용하고 필요하면 영구 설정한 뒤 [Codex를 연결](integrations.ko.md#연결-범위-선택)하세요.

## Windows

`main`의 고정 진입 스크립트를 내려받아 실행합니다.

```powershell
Invoke-WebRequest -UseBasicParsing https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 -OutFile install.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
```

명령 프롬프트에서도 설치할 수 있습니다.

```bat
curl.exe -fL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.cmd -o install.cmd
install.cmd
```

관리자 권한 없이 사용자 범위로 설치합니다. 기본 루트는 `%LOCALAPPDATA%\tapl`, 실행 launcher는 `%LOCALAPPDATA%\tapl\bin\taplctl.cmd`입니다. 사용자 `PATH`를 반영하도록 터미널을 다시 연 뒤 [Codex를 연결](integrations.ko.md#독립-설치의-실행-파일-경로)하세요.

### 채널과 시맨틱 의존성

`main`의 진입 스크립트는 릴리스를 선택하고 해당 릴리스의 설치 asset을 내려받습니다. 릴리스 설치 asset은 자기 버전만 설치하며 채널을 선택하는 진입 스크립트가 아닙니다.

| 진입 스크립트 옵션 | 선택 대상 |
| --- | --- |
| 없음 | 최신 안정 릴리스 |
| `-Pre` | 프리릴리즈를 포함한 가장 최근 공개 릴리스. 더 최근 안정 릴리스가 선택될 수도 있음 |
| `-Semantic` | 임베딩·벡터 의존성을 포함한 최신 안정 릴리스 |
| `-Pre -Semantic` | 시맨틱 의존성을 포함한 가장 최근 공개 릴리스 |
| `-Version TAG` | 정확히 지정한 릴리스 태그 |
| `-Version TAG -Semantic` | 시맨틱 의존성을 포함한 지정 릴리스 |

`-Pre`와 `-Version`은 함께 사용할 수 없습니다. 태그는 `x.y.z` 또는 `x.y.z-(alpha|beta|rc)N` 형식이며 예로 `2.14.0-beta1`이 있습니다. 아래 `TAG`를 실제 릴리스 태그로 바꾸세요.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Pre -Semantic
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Version TAG
```

```bat
install.cmd -Pre -Semantic
install.cmd -Version TAG
```

Windows는 선택 의존성을 설치하면 로컬 시맨틱 검색을 지원합니다. Unix 소켓을 쓰는 `searchd` 데몬은 Windows에서 사용할 수 없으며, 전문 검색에는 필요하지 않습니다. [검색 안내](../guides/search.ko.md)를 참고하세요.

### Windows 실행 파일 재설치·제거

내려받은 진입 스크립트에 유지하려는 릴리스·채널 옵션을 지정해 사용합니다.

| 작업 | PowerShell | CMD |
| --- | --- | --- |
| 재설치 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Reinstall` | `install.cmd -Reinstall` |
| 실행 파일 제거 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall` | `install.cmd -Uninstall` |

`-Reinstall`과 `-Uninstall`은 함께 사용할 수 없습니다. 이전 버전으로의 전환을 포함해 릴리스를 바꾸려면 진입 스크립트에 `-Version TAG`를 사용하세요. 같은 릴리스를 다시 설치할 때는 `-Reinstall`을 추가합니다. 채널 옵션이 없는 재설치 예제는 기본값인 안정 채널을 사용합니다.

실행 파일을 제거하기 전에 [설치한 Codex 연결 범위를 각각 해제](integrations.ko.md#연결-해제와-재연결)하세요. 제거 시 TAPL 설정, 워크플로 DB와 무관한 파일은 보존합니다. 파일 목록이 없는 구형 설치는 먼저 `-Reinstall`이 필요하며, 관리 파일이 수정되어 있으면 점검을 위해 제거를 중단합니다.

`TAPL_INSTALL_ROOT`와 `TAPL_BIN_DIR`로 설치·launcher 위치를 바꿀 수 있습니다. `TAPL_INSTALL_MANIFEST_URL`은 사용자 지정 manifest를 선택하지만, 릴리스 설치 스크립트에는 여전히 자기 버전의 manifest가 필요합니다. 설치 스크립트는 사용 전에 manifest와 wheel SHA-256을 검증합니다.

## 업데이트

Linux·Windows 독립 설치에서는 다음 명령을 사용합니다.

```sh
taplctl update --check
taplctl update
```

Updater는 관리 설치 메타데이터를 확인하고 manifest와 wheel SHA-256을 검증합니다. Windows 업데이트는 안정·프리릴리즈·고정 채널과 시맨틱 옵션을 보존합니다. 고정 채널은 기록된 릴리스 manifest를 계속 사용합니다. 선택을 바꾸려면 Windows 진입 스크립트를 사용하세요. `TAPL_INSTALL_MANIFEST_URL`은 manifest 선택을 덮어씁니다.

Homebrew는 설치한 formula를 갱신합니다.

```sh
brew update
brew upgrade taplctl
# 설치한 formula가 taplctl-semantic 또는 taplctl-pre라면 그 이름을 사용합니다.
```

`taplctl update`는 Homebrew나 소스 체크아웃을 갱신하지 않습니다. Homebrew 업그레이드·재설치 중 Viewer 서비스가 이미 실행 중인 경우에만 재시작을 시도합니다. 신규 설치나 중지된 서비스는 중지 상태를 유지하며, 수동으로 시작한 MCP stdio와 `searchd` 프로세스는 재시작하지 않습니다.

기존에 연결한 Codex 범위는 MCP 시작과 hook 진입 시 버전이나 배포 템플릿 변경을 감지해 자동 갱신합니다. 설정과 hook 모드를 보존하고 누락 기본값을 병합하며 알려진 구형 키를 정리합니다. 업데이트 뒤 보통 `taplctl install`을 다시 실행할 필요는 없습니다. 호스트 설정을 다시 읽도록 Codex를 재시작하세요. [자동 갱신 범위](integrations.ko.md#자동-갱신)를 참고하세요.

## 설치 확인과 다음 단계

```sh
taplctl --version
taplctl doctor
```

`doctor`는 런타임, SQLite 기능, 선택 의존성, 설정과 선택 DB를 출력합니다. 시맨틱 의존성이 없어도 전문 검색은 사용할 수 있습니다. 의도한 작업 폴더에서 실행하세요. 작업 공간 상태를 초기화하거나 기존 연결을 갱신할 수 있습니다.

- [빠른 시작](quickstart.ko.md): 연결과 첫 작업 완료.
- [Agent 연결](integrations.ko.md): 범위·실행 경로·hook 신뢰·연결 해제.
- [CLI 참조](../reference/cli.ko.md): 관리 옵션.
- [문제 해결](../guides/troubleshooting.ko.md): 설치·연결 진단.
