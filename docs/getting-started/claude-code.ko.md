# Claude Code

[문서 홈](../README.ko.md) · [English](claude-code.md)

Claude Code는 TAPL의 공통 워크플로 MCP 도구, 수명주기 검사, 이력과 Viewer를 사용합니다. 설치 상태·세션 소유권·위임 설정은 Codex와 분리합니다. 먼저 [TAPL 실행 파일](installation.ko.md)을 설치하세요.

## 연결과 제거

범위를 하나 선택합니다.

```sh
taplctl install user --client claude-code
# 또는 대상 작업 폴더에서:
taplctl install repo --client claude-code --mode enforce
```

기본 클라이언트는 계속 `codex`입니다. Claude 설치·제거 명령에는 항상 `--client claude-code`를 붙입니다. 두 범위 모두 `--dry-run`, `--tapl-config-policy`, `--taplctl-command`, `--mode observe|enforce`를 지원합니다. [CLI 옵션](../reference/cli.ko.md#install)을 참고하세요. 설치 기본 모드는 `observe`입니다.

| 범위 | MCP 설정 | 수명주기 hook |
| --- | --- | --- |
| 사용자 | `~/.claude.json`의 최상위 `mcpServers.tapl` | `~/.claude/settings.json` |
| 저장소 | `.mcp.json` | `.claude/settings.json` |

`install repo --repo PATH`는 작업 폴더를 선택합니다. `install user --claude-home PATH`는 Claude 설정 디렉터리를 선택하며, 그 부모에 `.claude.json`과 `.tapl`이 위치합니다. TAPL의 `repo`는 공유 프로젝트 `.mcp.json`에 기록하므로, `~/.claude.json` 안에 저장되는 Claude의 프로젝트 개인 MCP 범위와 다릅니다.

Claude Code를 재시작하고 MCP·작업 공간 신뢰 절차를 마친 뒤 `/mcp`에서 확인하세요. 설치된 서버는 `TAPL_CLIENT=claude-code` 환경으로 `tapl-mcp`를 실행하고, 다섯 command hook은 `tapl-hook --client claude-code`를 실행합니다. 실행 파일을 옮길 때 이 클라이언트 지정도 유지합니다. [실행 파일 탐색 예제](integrations.ko.md#실행-파일-탐색)에도 클라이언트 옵션을 추가해 적용할 수 있습니다.

```sh
taplctl uninstall user --client claude-code --dry-run
taplctl uninstall user --client claude-code
# 또는:
taplctl uninstall repo --client claude-code --repo /path/to/workspace
```

설치는 TAPL 소유 항목을 병합하며 다른 hook·서버·설정을 보존합니다. `--tapl-config-policy overwrite`도 다른 클라이언트의 위임 설정은 보존합니다. 기본 제거는 TAPL 데이터와 설정을 유지합니다. 명시적 purge에서도 다른 클라이언트의 설치 표식·사용자 지정 선호·세션 소유 이력이 있으면 공유 파일을 보존하며 JSON 결과에 `preserved_shared`를 표시합니다. 생성된 기본값만으로는 다른 클라이언트의 사용자 지정 선호로 판단하지 않습니다. [제거 경계](../reference/cli.ko.md#uninstall)를 참고하세요.

자동 갱신은 이전에 설치한 Claude 범위만 검사하며 hook 모드와 로컬 설정 부재를 보존합니다. `.tapl/claude-code.version`과 `.tapl/claude-code.install-state.json`을 사용하고 Codex의 기존 표식은 유지합니다. 한쪽을 제거한 뒤 다른 클라이언트가 시작되어도 제거한 통합을 다시 설치하지 않습니다.

## Hook과 세션 소유권

`SessionStart`·`UserPromptSubmit`은 컨텍스트를 전달하고, `PreToolUse`는 파일 변경을 검사하며, `PostToolUse`는 조사 결과 기록을 안내하고, `Stop`은 남은 작업을 확인합니다. Claude에는 이벤트별 `additionalContext`와 거부 응답을 전달합니다. TAPL은 도구 호출을 자동 허용하거나 Claude 권한 규칙을 변경하지 않습니다. Enforce hook은 워크플로 검사이며 보안 sandbox가 아닙니다.

**모든** MCP 호출에 hook 컨텍스트의 정확한 TAPL `session_id`를 전달합니다. Claude 소유자는 `claude-code:<native-session-id>`이며 원본 ID·생략·다른 클라이언트 ID는 거부합니다. Codex의 기존 ID와 격리된 legacy 동작은 유지합니다. 공통 DB에 두 클라이언트의 별도 RUN이 있어도 승인·큐·완료 소유권은 이전되지 않습니다. 파일은 공유하므로 동시 편집은 조율하거나 worktree를 사용하세요.

Helper는 부모의 TAPL 소유자와 별도의 Claude `agent_id`를 유지합니다. Root RUN을 만들거나 부모의 수명주기를 종료하지 않으며 TAPL 상태 기록은 root만 수행합니다. Stop 재진입은 같은 계속 작업을 반복 차단하지 않습니다. 재개·압축 후에도 올바른 소유자와 정책을 유지하거나 다시 읽어야 합니다.

## 모델과 Agent 실행

Claude 선호는 `[clients.claude-code.subagents]`, Codex 선호는 기존 `[subagents]`에 저장합니다. 최초 설정과 이후 카탈로그 점검은 현재 호스트의 실제 도구 schema와 사용자 선택을 사용합니다. TAPL이 provider 모델 목록을 조회하거나 Codex 선호로 Claude 목록을 추측하지 않습니다.

다음 예제는 실제 Agent 도구가 `sonnet` alias를 제공하고 effort 인자를 노출하지 않는 경우입니다.

```toml
[clients.claude-code.subagents]
enabled = true
setup_complete = true
strategy = "balanced"
preference = "Prefer independent bounded tasks."
profiles = []

[clients.claude-code.subagents.models]
sonnet = []

[clients.claude-code.subagents.available_models]
sonnet = []
```

빈 effort 배열은 `Agent.effort`를 생략한다는 뜻이며 지원 effort를 주장하지 않습니다. 선택 모드 `models.inherit = []`는 `Agent.model`과 `Agent.effort`를 모두 생략하고 호스트·Agent 정의에 선택을 맡깁니다. `inherit`는 선택 방식이므로 `available_models`에 넣으면 거부됩니다. 요청한 alias는 모델 정의·조직 정책·환경 강제로 다른 실제 모델에 연결될 수 있으므로 관찰한 차이를 기록합니다.

호출별 effort 지정에는 이를 지원하는 Claude 버전과 실제 Agent schema가 필요합니다. [공식 Agent 참조](https://code.claude.com/docs/en/sub-agents#choose-an-effort-level)의 버전별 우선순위를 확인하고, 설치 버전이 모든 옵션을 노출한다고 가정하지 마세요.

병렬 실행 시 root는 `owned_paths`가 겹치지 않는 독립 TASK를 만들고 승인을 받은 뒤 `tapl_dispatch_tasks`를 원자적으로 호출합니다. Manifest를 검증하고 항목별 Agent를 시작하며 정확한 부모 소유자·TASK ID·실행 ID를 전달합니다. 결과 검토 후 root가 같은 실행 ID로 `tapl_complete_task`·`tapl_block_task`·`tapl_skip_task`를 호출합니다. 생성 실패·중단 시 배치를 복구·취소한 뒤 재dispatch하며 새 실행은 새 ID를 사용합니다. Agent 종료만으로 TASK가 정산되지는 않습니다. [SubAgent 가이드](../guides/subagents.ko.md)를 참고하세요.

```sh
taplctl config get clients.claude-code.subagents --json
taplctl config set clients.claude-code.subagents.strategy balanced
```

## 검증과 문제 해결

자동 검사는 설치·제거·갱신, wheel/sdist 템플릿, hook 응답 계약, 소유권 격리, 독립 설정과 두 TASK의 dispatch·정산·복구를 포함합니다.

공개된 `2.17.0-beta1` 설치 프로그램과 런타임은 Claude Code `2.1.318`을 사용한 morae Linux ARM64 VM 검증을 통과했습니다. Print 모드의 실제 대화 세 개에서 수정·실행 승인 없는 계획, 승인된 단일 파일 수정, 같은 응답에서 호출되어 서로 다른 파일을 소유하는 native Agent 두 개를 검증했습니다. 정확한 세션 소유권, 파일 내용, 실행 ID별 정산과 완료된 RUN의 아카이브를 확인했으며 계획 RUN은 활성 상태로 유지됐습니다. 다섯 hook 이벤트가 모두 기록됐고, 등록된 enforce hook을 별도로 호출한 미승인 `Write` 요청도 차단됐습니다.

이 대화는 VM 내부의 `bypassPermissions`와 `inherit` 모델 선택을 사용해 Agent model/effort 인자를 생략했습니다. 전체 OS·버전 조합, 대화형 trust 승인, 명시적 모델·effort 선택까지 검증한 것은 아닙니다. 프로토콜 검사만으로 실제 대화 동작을 판단하지 않습니다.

MCP가 연결됐지만 소유자 누락 오류가 나면 새 세션을 시작하고 hook 로드를 확인하세요. 다른 세션 ID를 추측해 사용하지 않습니다. 사용자·저장소 통합이 함께 있으면 Claude의 실제 MCP 설정 원본을 확인하고 원하지 않는 범위를 명시적으로 제거합니다. 실행 파일 경로가 오래됐으면 `--taplctl-command`를 지정해 재설치를 미리 확인하고, JSON/TOML 오류는 표시된 파일을 고친 뒤 갱신하세요. [문제 해결](../guides/troubleshooting.ko.md)을 참고하세요.
