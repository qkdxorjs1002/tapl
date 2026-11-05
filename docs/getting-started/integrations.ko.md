# Agent 연결

[문서 홈](../README.ko.md) · [English](integrations.md)

TAPL은 공통 `tapl-mcp` stdio 서버와 호스트별 `tapl-hook` 수명주기 처리로 Codex와 Claude Code에 연결합니다. 아래에서 클라이언트와 연결 범위를 선택하세요. Claude의 세션 소유권·Agent 선호는 [Claude Code 가이드](claude-code.ko.md)를 참고하세요. 다른 MCP 클라이언트에 두 호스트의 수명주기 동작이 자동 적용되지는 않습니다.

## Agent에게 TAPL 설치 맡기기

코딩 Agent에 다음 프롬프트를 복사하세요.

```text
TAPL을 설치하고 내가 사용하는 코딩 클라이언트에 연결해 줘.
저장소: https://github.com/qkdxorjs1002/tapl
설치 가이드: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/installation.ko.md
연결 가이드: https://github.com/qkdxorjs1002/tapl/blob/main/docs/getting-started/integrations.ko.md

가이드를 읽고 내 OS와 셸, 선행 요구사항과 기존 설치를 확인해 줘.
연결할 클라이언트와 범위를 이미 지정하지 않았다면 먼저 선택을 확인해 줘:
클라이언트: Codex 또는 Claude Code. 범위: user(내 프로젝트 전체) 또는 repo(대상 저장소만).
별도 릴리스를 지정하지 않았다면 공식 설치 방법과 해당 클라이언트에 문서화된 채널을 사용해 줘.
선택한 범위에 맞춰 taplctl install user 또는 taplctl install repo를 실행하되 Claude Code는 --client claude-code를 붙이고 Codex는 --client를 생략해 줘. 필요하면 플랫폼별 실행 파일 경로를 사용해 줘.
기존 TAPL 설정, hook 모드, 워크플로 DB와 무관한 클라이언트 설정을 보존해 줘.
taplctl --version과 taplctl doctor로 확인해 줘.
설치 버전과 남은 터미널·클라이언트 재시작, 신뢰 단계를 알려 줘.
```

프롬프트의 저장소 URL은 TAPL 프로젝트를 가리킵니다. `install repo`는 실제 작업할 저장소를 대상으로 실행하세요.

## 연결 범위 선택

먼저 [실행 파일을 설치](installation.ko.md)하고 **한 행**을 선택합니다.

| 클라이언트 | 범위 | 명령 |
| --- | --- | --- |
| Codex | User: 내 프로젝트 전체 | `taplctl install user` |
| Codex | Repository: 대상 저장소만 | `taplctl install repo` |
| Claude Code | User: 내 프로젝트 전체 | `taplctl install user --client claude-code` |
| Claude Code | Repository: 대상 저장소만 | `taplctl install repo --client claude-code` |

`--client`를 생략하면 CLI는 `codex`를 선택합니다. Claude 설치·제거에는 항상 `--client claude-code`를 붙입니다. `repo`는 대상 저장소 안에서 실행하거나 `--repo /path/to/repository`를 추가하세요.

선택한 통합은 다음 호스트 파일에 기록합니다.

| 클라이언트 / 범위 | MCP 설정 | 수명주기 hook |
| --- | --- | --- |
| Codex 사용자 | `~/.codex/config.toml`의 `mcp_servers.tapl` | `~/.codex/hooks.json` |
| Codex 저장소 | `.codex/config.toml`의 `mcp_servers.tapl` | `.codex/hooks.json` |
| Claude Code 사용자 | `~/.claude.json`의 최상위 `mcpServers.tapl` | `~/.claude/settings.json` |
| Claude Code 저장소 | `.mcp.json`의 `mcpServers.tapl` | `.claude/settings.json` |

Codex MCP 설정은 TOML이며 Claude MCP 설정과 두 클라이언트의 hook 파일은 JSON입니다. TAPL의 Claude `repo` 범위는 `~/.claude.json` 안의 프로젝트 개인 MCP 항목 대신 공유 프로젝트 `.mcp.json`에 기록합니다.

홈이 기본값과 다르면 `taplctl install user --codex-home /path/to/.codex` 또는 `taplctl install user --client claude-code --claude-home /path/to/.claude`를 사용합니다. 선택한 디렉터리의 부모에 사용자 `.tapl` 설정이 위치하며, Claude는 `.claude.json`도 같은 부모에 둡니다.

저장소 설치는 로컬 `.tapl` 설정과 워크플로 상태도 초기화합니다. 사용자 연결은 사용 시 각 세션 작업 폴더에 DB를 초기화하며 로컬 `.tapl/config.toml`이나 저장소 설치 표식은 만들지 않습니다.

선택한 클라이언트를 재시작하세요. Codex는 요청이 나타나면 설치된 hook을 신뢰합니다. Claude Code는 MCP·작업 공간 신뢰 절차를 마치고 `/mcp`에서 확인합니다. 사용할 이력이 있는 폴더를 엽니다. 하위 폴더는 별도 DB를 소유하며 연결 범위가 모든 폴더의 이력을 합치지는 않습니다. [작업 공간과 세션 경계](../concepts/workflow.ko.md#작업-공간과-세션-경계)를 참고하세요.

## 실행 파일 탐색

일반적인 Homebrew 설치에는 경로 재정의가 필요 없습니다. 설치 명령은 `PATH`에서 `taplctl`을 찾아 같은 위치의 `tapl-mcp`, `tapl-hook` 실행 파일을 사용합니다.

다른 설치가 선택되는 경우 `--taplctl-command`를 사용하세요. 아래 예제는 사용자 범위이며 저장소 범위는 `install user`를 `install repo`로 바꿉니다. 설치한 formula(`taplctl`, `taplctl-semantic`, `taplctl-pre`)를 사용합니다.

```sh
# taplctl formula의 Codex:
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
# taplctl-pre formula의 Claude Code:
taplctl install user --client claude-code --taplctl-command "$(brew --prefix taplctl-pre)/libexec/bin/taplctl"
```

### 독립 설치의 실행 파일 경로

Linux의 공개 launcher는 심볼릭 링크일 수 있습니다. 실제 실행 경로로 companion 명령을 찾습니다. 클라이언트를 선택하고 저장소 범위는 `install user`를 `install repo`로 바꿉니다.

```sh
# Codex:
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
# Claude Code:
taplctl install user --client claude-code --taplctl-command "$(realpath "$(command -v taplctl)")"
```

Windows는 PowerShell에서 설치 메타데이터의 활성 가상환경을 읽습니다.

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
# Codex:
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
# Claude Code:
taplctl install user --client claude-code --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

선택한 클라이언트의 명령만 실행하세요. 저장소 범위는 `install user`를 `install repo`로 바꿉니다. 이 경로는 설치된 실행 파일과 companion 명령을 선택하며 다른 DB를 선택하지는 않습니다.

## Hook 모드와 설정 보존

새 명시적 설치의 기본값은 `--mode observe`이며 hook이 워크플로 문제를 안내합니다. `--mode enforce`는 필수 워크플로 상태가 없을 때 영구 변경 도구 사용이나 종료를 차단할 수 있습니다. 사용할 클라이언트에 맞춰 미리 확인하고 적용합니다.

```sh
taplctl install repo --mode enforce --dry-run
taplctl install repo --mode enforce
# 또는 Claude Code:
taplctl install repo --client claude-code --mode enforce --dry-run
taplctl install repo --client claude-code --mode enforce
```

Hook 모드와 Fast/Standard/Strict 워크플로 엄격도는 별개입니다. Enforce hook은 워크플로 검사이며 sandbox나 보안 경계가 아닙니다. [워크플로](../concepts/workflow.ko.md)를 참고하세요.

설치는 TAPL 소유 MCP 항목과 hook을 병합하며 무관한 호스트 설정을 보존합니다. 관리 템플릿에 `--force`를 사용하지 않으면 기존 Codex TOML 값이 우선합니다. Claude의 관리 MCP·hook 항목은 교체하되 다른 서버와 hook은 보존합니다. 런타임 TAPL 설정은 별도의 `--tapl-config-policy`를 사용합니다.

| 정책 | 기존 TAPL 설정 처리 |
| --- | --- |
| `prompt`(기본값) | 설치 버전이 바뀌면 질문하고 같은 버전 설정은 묻지 않고 보존 |
| `merge` | 같은 버전에서도 기존 값을 유지하고 누락 기본값 추가 |
| `overwrite` | 같은 버전에서도 런타임 기본값으로 교체하되 다른 클라이언트의 위임 설정은 보존 |

`--dry-run`으로 미리 볼 수 있습니다. 파일 우선순위는 [설정](../guides/configuration.ko.md), 옵션은 [CLI 참조](../reference/cli.ko.md)를 참고하세요.

## 자동 갱신

실제 MCP 시작과 hook 진입 시 현재 클라이언트가 기존에 설치한 범위의 버전과 배포 템플릿 fingerprint를 검사합니다. Hook 모드를 보존하고 누락 기본값을 병합하며 알려진 구형 관리 키를 정리합니다. Codex 갱신은 오래된 TAPL MCP `cwd` 재정의도 제거해 서버가 세션 작업 폴더를 사용하게 합니다.

사용자 `~/.tapl` 또는 저장소 `.tapl` 안에서 클라이언트마다 별도 설치 표식을 사용합니다.

| 클라이언트 | 버전 표식 | 템플릿 상태 |
| --- | --- | --- |
| Codex | `version` | `install-state.json` |
| Claude Code | `claude-code.version` | `claude-code.install-state.json` |

사용자 자동 갱신에는 해당 클라이언트의 버전 표식이 필요합니다. 저장소 갱신에는 기존 DB도 필요합니다. 남은 hook이나 설정 재정의만으로는 해당 범위를 설치하지 않습니다. 로컬 설정이 없으면 그대로 두어 사용자 설정·기본값을 상속합니다. 빠진 저장소 설치 파일을 복구하려면 해당 `taplctl install repo` 명령(Claude는 `--client claude-code` 추가)을 명시적으로 실행하세요.

연결 해제한 클라이언트·범위는 다른 클라이언트가 시작되어도 비활성 상태를 유지합니다. 호스트 설정이 바뀌면 선택한 클라이언트를 재시작하세요. 자동 갱신은 실행 중인 호스트를 재시작하지 않습니다.

## 연결 해제와 재연결

연결한 클라이언트·범위에 맞는 명령을 사용합니다. 필요하면 제거 전에 미리 확인합니다.

```sh
# Codex:
taplctl uninstall user --dry-run
taplctl uninstall user
# 또는:
taplctl uninstall repo --repo /path/to/repository

# Claude Code:
taplctl uninstall user --client claude-code --dry-run
taplctl uninstall user --client claude-code
# 또는:
taplctl uninstall repo --client claude-code --repo /path/to/repository
```

Uninstall은 선택한 클라이언트의 TAPL MCP 항목, 인식되는 hook과 설치 표식을 제거합니다. 무관한 호스트 설정, TAPL 설정과 워크플로 데이터는 보존합니다. 실행 파일과 백그라운드 서비스는 남으므로 [설치 방법](installation.ko.md)에 맞춰 따로 제거하세요.

재연결하려면 해당 설치 명령을 실행하고 클라이언트를 재시작합니다. `--purge-config`와 `--purge-db`는 명시적 삭제 옵션입니다. 다른 클라이언트의 설치 표식·사용자 지정 선호·세션 소유 이력이 있으면 공유 파일을 보존하며, 생성된 기본값만으로는 사용자 지정 선호로 판단하지 않습니다. JSON 결과에 `preserved_shared`를 표시합니다. [제거 경계](../reference/cli.ko.md#uninstall)를 참고하세요.

## 연결 확인

의도한 작업 폴더에서 `taplctl --version`, `taplctl doctor`를 실행하고 선택한 클라이언트에서 새 세션을 시작합니다. Agent에 `tapl_*` MCP 도구가 제공되고 해당 폴더의 hook 문맥이 전달되어야 합니다. 모든 MCP 워크플로 호출에는 해당 클라이언트 hook의 정확한 TAPL `session_id`를 전달합니다. Claude는 `claude-code:<native-session-id>` 소유자를 요구하며 생략·원본 ID·다른 클라이언트 ID는 거부합니다. Codex는 기존 ID를 유지하고 생략 시 격리된 legacy 범위만 선택합니다.

- [빠른 시작](quickstart.ko.md): 첫 워크플로와 Viewer 확인.
- [Claude Code](claude-code.ko.md): hook 이벤트·세션 소유권·Agent 모델 선호.
- [MCP 참조](../reference/mcp.ko.md): 도구와 세션 인자.
- [문제 해결](../guides/troubleshooting.ko.md): 도구 누락·hook 신뢰·오래된 경로.
