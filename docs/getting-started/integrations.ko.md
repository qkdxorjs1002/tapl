# Agent 연결

[문서 홈](../README.ko.md) · [English](integrations.md)

TAPL은 `tapl-mcp` stdio 서버와 `tapl-hook` 수명주기 hook으로 Codex에 연결합니다. 설치 명령이 둘을 함께 구성하며 `taplctl`은 관리 명령을 담당합니다. 이 페이지는 배포되는 Codex 연결을 설명합니다. 다른 MCP 클라이언트에 Codex의 hook·세션 동작이 자동으로 적용되지는 않습니다.

## Agent에게 TAPL 설치 맡기기

Codex 같은 코딩 Agent에 다음 프롬프트를 복사하세요.

```text
TAPL을 설치하고 Codex에 연결해 줘.
저장소: https://github.com/qkdxorjs1002/tapl
설치 가이드: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/installation.ko.md
연결 가이드: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.ko.md

가이드를 읽고 내 OS와 셸, 선행 요구사항과 기존 설치를 확인해 줘.
별도 채널을 지정하지 않았다면 내 OS의 공식 설치 방법으로 최신 안정 릴리스를 설치해 줘.
연결 범위를 이미 지정하지 않았다면 먼저 선택을 확인해 줘: user(내 Codex 프로젝트 전체) 또는 repo(대상 저장소만).
선택한 범위에 맞춰 taplctl install user 또는 taplctl install repo를 실행하고, 필요하면 플랫폼별 실행 파일 경로를 사용해 줘.
기존 TAPL 설정, hook 모드, 워크플로 DB와 무관한 Codex 설정을 보존해 줘.
taplctl --version과 taplctl doctor로 확인해 줘.
설치 버전과 남은 터미널·Codex 재시작, hook 신뢰 단계를 알려 줘.
```

이 프롬프트는 사용자·저장소 연결 범위의 선택권을 유지합니다. 프롬프트의 저장소 URL은 TAPL 프로젝트를 가리킵니다. `install repo`는 실제 작업할 저장소를 대상으로 실행하세요.

## 연결 범위 선택

먼저 [실행 파일을 설치](installation.ko.md)하고 연결 명령 **하나**를 실행합니다.

| 범위 | 적용 대상 | 명령 |
| --- | --- | --- |
| User | `~/.codex` 사용자 설정을 통한 Codex 프로젝트 | `taplctl install user` |
| Repository | `.codex` 설정을 통한 대상 저장소 | `taplctl install repo` |

`repo`는 대상 저장소 안에서 실행하거나 `taplctl install repo --repo /path/to/repository`로 지정하세요. Codex 홈이 기본값과 다르면 `taplctl install user --codex-home /path/to/.codex`를 사용합니다.

두 범위 모두 활성화된 `mcp_servers.tapl` 항목과 수명주기 hook을 추가합니다. 저장소 설치는 로컬 `.tapl` 설정과 워크플로 상태도 초기화합니다. 사용자 연결은 사용 시 각 세션 작업 폴더에 DB를 초기화하며 로컬 `.tapl/config.toml`이나 `.tapl/version`은 만들지 않습니다.

Codex를 재시작해 서버와 hook을 읽고, 처음 신뢰 요청이 나타나면 설치된 hook을 신뢰하세요. 사용할 이력이 있는 폴더를 엽니다. 하위 폴더는 별도 DB를 소유하며 연결 범위가 모든 폴더의 이력을 합치지는 않습니다. [작업 공간과 세션 경계](../concepts/workflow.ko.md#작업-공간과-세션-경계)를 참고하세요.

## 실행 파일 탐색

일반적인 Homebrew 설치에는 경로 재정의가 필요 없습니다. 설치 명령은 `PATH`에서 `taplctl`을 찾아 같은 위치의 `tapl-mcp`, `tapl-hook` 실행 파일을 사용합니다.

다른 설치가 선택되는 경우 `--taplctl-command`를 사용하세요. Homebrew에서 `taplctl-semantic` 또는 `taplctl-pre`를 설치했다면 formula 이름을 바꿉니다.

```sh
# 한 범위를 선택합니다.
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
# 또는 대상 저장소에서 실행합니다.
taplctl install repo --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
```

### 독립 설치의 실행 파일 경로

Linux의 공개 launcher는 심볼릭 링크일 수 있습니다. 실제 실행 경로로 companion 명령을 찾습니다.

```sh
# 한 범위를 선택합니다.
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
# 또는 대상 저장소에서 실행합니다.
taplctl install repo --taplctl-command "$(realpath "$(command -v taplctl)")"
```

Windows는 PowerShell에서 설치 메타데이터의 활성 가상환경을 읽습니다.

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
# 한 범위를 선택합니다.
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
# 또는 대상 저장소에서 실행합니다.
taplctl install repo --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

선택한 범위의 명령만 실행하세요. 이 경로는 설치된 실행 파일과 companion 명령을 선택하며 다른 DB를 선택하지는 않습니다.

## Hook 모드와 설정 보존

새 명시적 설치의 기본값은 `--mode observe`이며 hook이 워크플로 문제를 안내합니다. `--mode enforce`는 필수 워크플로 상태가 없을 때 영구 변경 도구 사용이나 종료를 차단할 수 있습니다. 예를 들어 대상 저장소에서 다음과 같이 실행합니다.

```sh
taplctl install repo --mode enforce --dry-run
taplctl install repo --mode enforce
```

Hook 모드와 Fast/Standard/Strict 워크플로 엄격도는 별개입니다. Enforce hook은 워크플로 검사이며 sandbox나 보안 경계가 아닙니다. [워크플로](../concepts/workflow.ko.md)를 참고하세요.

설치는 TAPL hook과 Codex TOML을 병합하며 무관한 설정을 보존합니다. 관리 템플릿에 `--force`를 사용하지 않으면 기존 Codex 값이 우선합니다. 런타임 TAPL 설정은 별도의 `--tapl-config-policy`를 사용합니다.

| 정책 | 기존 TAPL 설정 처리 |
| --- | --- |
| `prompt`(기본값) | 설치 버전이 바뀌면 질문하고 같은 버전 설정은 묻지 않고 보존 |
| `merge` | 같은 버전에서도 기존 값을 유지하고 누락 기본값 추가 |
| `overwrite` | 같은 버전에서도 런타임 기본값으로 교체 |

`--dry-run`으로 미리 볼 수 있습니다. 파일 우선순위는 [설정](../guides/configuration.ko.md), 옵션은 [CLI 참조](../reference/cli.ko.md)를 참고하세요.

## 자동 갱신

실제 MCP 시작과 hook 진입 시 기존에 설치한 범위의 버전과 배포 템플릿 fingerprint를 검사합니다. Hook 모드를 보존하고 누락 기본값을 병합하며 알려진 구형 관리 키를 정리합니다. 오래된 TAPL MCP `cwd` 재정의도 제거해 서버가 세션 작업 폴더를 사용하게 합니다.

사용자 자동 갱신에는 `~/.tapl/version`이 필요합니다. 저장소 자동 갱신에는 기존 DB와 `.tapl/version`이 필요합니다. 남은 hook이나 설정 재정의만으로는 해당 범위를 설치하지 않습니다. 로컬 설정이 없으면 그대로 두어 사용자 설정·기본값을 상속합니다. 빠진 저장소 설치 파일을 복구하려면 `taplctl install repo`를 명시적으로 실행하세요.

연결 해제한 범위는 비활성 상태를 유지합니다. 호스트 설정이 바뀌면 Codex를 재시작하세요. 자동 갱신은 실행 중인 호스트를 재시작하지 않습니다.

## 연결 해제와 재연결

연결한 범위에 맞는 명령을 사용합니다.

```sh
taplctl uninstall user --dry-run
taplctl uninstall user
# 또는:
taplctl uninstall repo --repo /path/to/repository
```

Uninstall은 TAPL MCP 항목, 인식되는 hook과 설치 버전 표시를 제거합니다. 무관한 Codex 설정, TAPL 설정과 워크플로 데이터는 보존합니다. 실행 파일과 백그라운드 서비스는 남으므로 [설치 방법](installation.ko.md)에 맞춰 따로 제거하세요.

재연결하려면 해당 `taplctl install` 명령을 실행하고 Codex를 재시작합니다. `--purge-config`와 `--purge-db`는 명시적 삭제 옵션입니다. [CLI 참조](../reference/cli.ko.md#uninstall)를 참고하세요.

## 연결 확인

의도한 작업 폴더에서 `taplctl --version`, `taplctl doctor`를 실행하고 새 Codex 세션을 시작합니다. Agent에 `tapl_*` MCP 도구가 제공되고 해당 폴더의 hook 문맥이 전달되어야 합니다. 모든 MCP 워크플로 호출에는 Codex hook의 `session_id`가 필요하며, 생략하면 격리된 legacy 범위만 선택합니다.

- [빠른 시작](quickstart.ko.md): 첫 워크플로와 Viewer 확인.
- [MCP 참조](../reference/mcp.ko.md): 도구와 세션 인자.
- [문제 해결](../guides/troubleshooting.ko.md): 도구 누락·hook 신뢰·오래된 경로.
