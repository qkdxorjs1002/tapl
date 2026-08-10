<p align="center">
  <img src="assets/tapl-readme-hero-with-text.png" alt="tapl: Harness over prompting. State over files." />
</p>

# tapl

[English](README.md)

`tapl`은 Codex CLI가 저장소 안에서 진행하는 작업을 놓치지 않도록 기록합니다.
사용자의 지시와 lifecycle을 repo-local SQLite DB에 저장하고, 계획형 작업에는
Codex의 plan, task, finding, approval, event, archive, 검색 가능한 history도
기록합니다. 코드는 여전히 Codex가 쓰고, `tapl`은 durable 작업의 진행 상태 확인과
context가 사라진 뒤의 재개를 가능하게 합니다.

## 빠른 시작

[설치 상세](#설치-상세)를 한 번 따라 한 뒤, repository 안에서 Codex를 평소처럼
사용하면 됩니다.

## 어떻게 동작하나요?

핵심은 또 하나의 prompt template이 아닙니다. TAPL은 기존 CLI와 repo-local
state 위에 typed MCP tool을 제공하므로, Codex는 CLI help를 반복해서 읽지 않고
MCP 서버에서 workflow 계약을 한 번 전달받습니다. 아래 capture-style 이미지는 이번 README 재작성 중
`tapl`이 기록한 명령 흐름을 반영합니다.

<p align="center">
  <img src="assets/tapl-codex-iterm-demo.svg" alt="README 파일을 편집하기 전에 tapl state를 사용하는 Codex CLI terminal-style 캡처" />
</p>

설치 후에는 Codex를 평소처럼 사용하면 됩니다. TAPL MCP 서버가 typed workflow
tool과 고정 가이던스를 제공하고, hook은 현재 상태와 durable-edit 경계만 짧게
전달합니다. 보통은 workflow record를 직접 쓰는 명령을 사람이 실행할 필요가 없습니다.

상태는 `.tapl/tapl.db`에 저장됩니다. 그래서 다음 Codex session, hook, 사용자,
브라우저 또는 VS Code viewer가 같은 run을 확인할 수 있습니다.

## 왜 필요한지

Codex session은 일을 잘합니다. 하지만 긴 개발 작업에는 마지막 prompt 이상의
정보가 필요합니다.

- 사용자가 무엇을 요청했나?
- agent가 어떤 plan을 골랐나?
- 아직 남은 task는 무엇인가?
- durable file edit가 승인됐나?
- 구현 중 무엇을 배웠나?
- 다음 session이 그 history를 검색할 수 있나?

`tapl`은 하나의 전역 CLI, typed MCP facade, repo-local SQLite DB로 이 질문에 답합니다.

## 기능

설치 후에는 이 workflow가 Codex 사용 중 자동으로 실행됩니다. MCP tool이
structured call을 `taplctl`로 매핑하고, hook은 짧은 lifecycle state를 반환합니다.
사용자는 Codex가 무엇을 기록했는지 확인하거나 검증하고 싶을 때만 CLI를 보면 됩니다.

### 1. 현재 Codex run 확인

현재 repository에서 Codex가 기록한 내용을 보고 싶을 때는 다음 명령을 사용합니다.

```sh
taplctl status
taplctl validate
```

`status`는 active request, workflow mode, plan, task, finding, approval state,
recent activity를 보여줍니다. `validate`는 선택한 workflow mode에 필요하며 긴
Codex session을 나중에 이어가기 어렵게 만드는 record 누락을 알려줍니다.

통합 도구에는 `--json` 출력이 그대로 제공됩니다. Codex hook은 내부적으로
Codex가 효율적으로 읽을 수 있는 간결한 출력을 위해 `--agent`를 사용하지만,
일반 사용자가 따라 실행하는 모드는 아닙니다.

### 2. Plan과 task는 Codex가 기록하게 두기

Plan과 task는 흩어진 Markdown 메모가 아니라 first-class record입니다.
Codex는 MCP 서버에서 lifecycle guidance를 받고 typed MCP tool field로 plan/task
내용을 기록합니다. `tapl`은 저장된 record의 Markdown body를 안정적인 템플릿으로 렌더링합니다.

요청을 요약할 때 agent는 복잡도에 따라 `planned` 또는 `lightweight`를 명시적으로
선택합니다. 기본값인 `planned`는 계획, durable edit, test, verification에
사용합니다. `lightweight`는 저장할 plan/task가 필요 없는 단순한 비영속 답변용이며,
바로 결과를 기록하고 archive할 수 있습니다. 진행 중 작업이 복잡해지면
`tapl_apply_plan` 호출이 run을 `planned`로 자동 승격합니다.

MCP write tool은 실행 가능한 식별자, 상태, validation issue, 필요한 병렬 실행
계약만 담은 compact receipt를 반환합니다. 각 receipt에는 최신 권장 MCP action도
포함되므로 agent가 보통 `tapl_get_next`를 별도로 호출할 필요가 없습니다. Script와
수동 통합을 위한 공개 CLI `--json` 상세 계약은 그대로 유지됩니다.

일반적인 사용에서는 Codex에게 작업을 요청하고, 설치된 MCP 서버와 hook이 record를
최신 상태로 유지하게 두면 됩니다. Agent가 따르는 필드 계약은 MCP tool description과
JSON schema가 기준입니다. CLI help는 사람이 직접 운영·진단·복구할 때 사용하는
flag 설명만 제공하며 agent workflow prompt 역할은 하지 않습니다.

```sh
taplctl plan set --help
taplctl task set --help
taplctl approval set --help
```

### 3. 검색 가능한 완료 작업 history

지난 작업은 archive로 남기고 검색할 수 있습니다.

```sh
taplctl search "workflow dashboard"
taplctl search "workflow dashboard" --limit 5
taplctl item show --id 1
```

Search는 SQLite FTS를 사용하고, semantic dependency를 설치하면 semantic/vector
search도 사용할 수 있습니다. 완료된 run은 `taplctl archive list`와
`taplctl archive show --id <id>`로 확인합니다.

### 4. Codex lifecycle 주변의 hook

`tapl`은 다음 Codex hook wiring을 설치합니다.

- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `Stop`

Hook은 `taplctl hook-event`를 호출하고 현재 workflow state를 읽은 뒤, 짧은
lifecycle context를 반환합니다. 고정 가이던스와 typed tool 계약은 MCP 서버가
담당하고, hook은 현재 상태의 경계를 지킵니다.

### 5. 하나의 CLI, workspace-local state

`taplctl`은 한 번 설치합니다. 각 Codex workspace는 상태를 `.tapl/tapl.db`에
저장하며, 이 DB가 workspace 앵커 역할도 합니다. 첫 hook event에서 상위 DB를
찾지 못하면 payload 작업 폴더를 명시적으로 초기화합니다. 이후 하위 Git
repository에서 명령을 실행해도 별도 history DB를 만들지 않고 해당 workspace
DB를 재사용합니다.

Workspace root를 직접 지정하려면 다음 명령을 사용합니다.

```sh
taplctl init --workspace-root /path/to/workspace
```

중첩 repository를 의도적으로 독립 관리할 때는 그 위치에 별도
`.tapl/tapl.db`를 초기화합니다.

### 6. 브라우저 및 선택 가능한 VS Code viewer

초기화된 workspace에서 함께 제공되는 브라우저 viewer를 실행하세요.

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

# 8000 포트를 사용 중이면 다른 로컬 포트 지정
taplctl viewer --port 9000
```

출력된 URL을 브라우저에서 여세요. 서버는 로컬 loopback interface에서만
수신하고 브라우저를 자동으로 열지 않으며 viewer의 읽기 작업만 제공합니다.
foreground 서버는 `Ctrl+C`로 종료합니다.

workspace 안에서 실행하면 가장 가까운 `.tapl/tapl.db`가 우선합니다. Homebrew
로그인 서비스처럼 workspace 밖에서 시작하면 페이지에서 초기화된 workspace
폴더를 입력할 수 있고, 성공한 최근 경로를 해당 브라우저에 기억합니다. 하위
명령 앞에서 DB를 직접 선택할 수도 있습니다.

```sh
taplctl --db /path/to/workspace/.tapl/tapl.db viewer
```

`vscode-extension/`의 VS Code extension은 같은 state를 다음 명령으로 읽습니다.

```sh
taplctl status --json
taplctl archive list --json
taplctl search --json
taplctl item show --id <id> --json
```

Activity bar에서 active run, plan, task, finding, archive, search result를 볼
수 있습니다.

### 7. 병렬 SubAgent dispatch

TAPL은 repo-local SQLite 상태 저장소이자 검증기, execution manifest 조율자입니다.
실제 SubAgent를 spawn하지는 않습니다. 실제 spawn과 관리는 Codex/root runtime의
책임입니다. 기본값은 main agent가 수행하는 순차 task이며, 독점적인 파일 또는
directory 범위를 줄 수 있는 독립 작업에만 병렬 dispatch를 사용하세요.

같은 plan 및 비어 있지 않은 group에 호환되는 `Pending` task를 만듭니다. 병렬
task마다 `parallel` mode, `subagent` executor, 독점 `owned-path`를 선언해야
합니다. Dependency는 선택 사항이지만, 선언했다면 dispatch 전에 모두 반드시
`Completed` 상태여야 합니다.

```sh
# TASK-004는 이미 Completed 상태입니다. 아래 두 task는 별도 path를 소유합니다.
taplctl task create --id TASK-005 --title '집중 테스트 추가' --status Pending \
  --spec-id PLAN-001 --goal '병렬 dispatch 동작을 검증한다' \
  --action '집중 CLI 테스트를 추가한다' --verification '집중 테스트 suite를 실행한다' \
  --execution-mode parallel --executor-kind subagent --parallel-group dispatch-docs \
  --owned-path tapl/tests/test_tapl.py --owned-path tapl/tests/fixtures \
  --depends-on TASK-004 --agent

taplctl task create --id TASK-006 --title '병렬 dispatch 문서화' --status Pending \
  --spec-id PLAN-001 --goal '지원되는 workflow를 문서화한다' \
  --action '사용자 문서를 갱신한다' --verification 'README 예시를 검토한다' \
  --execution-mode parallel --executor-kind subagent --parallel-group dispatch-docs \
  --owned-path README.md --depends-on TASK-004 --agent
```

같은 group의 호환되는 `Pending` task를 두 개 이상 원자적으로 dispatch합니다.
`--batch-id`는 재시도를 식별 가능하게 하고, `--execution-metadata`는 task별
예정 executor reference, model, reasoning effort를 기록합니다. 명령은 task별
`execution_id`를 포함하는 manifest row를 출력합니다.

```sh
taplctl task dispatch TASK-005 TASK-006 --batch-id docs-20260727 \
  --execution-metadata '{
    "TASK-005": {"executor_ref": "tests-worker", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
    "TASK-006": {"executor_ref": "docs-worker", "model": "gpt-5.6-terra", "reasoning_effort": "high"}
  }' --agent
```

Root agent는 이 manifest를 읽고, 반환된 각 task와 `execution_id`마다 서로 다른
SubAgent를 동시에 spawn하며, 각 worker가 선언한 path 안에서만 작업하게 합니다.
TAPL state 작성은 root agent만 합니다. Batch가 관리하는 status를 직접 바꾸지
말고, 각 결과를 정확한 manifest ID로 정산하세요.

```sh
taplctl task complete TASK-005 --execution-id <TASK-005의-execution-id> \
  --verification 'uv run python -m unittest tests.test_tapl' \
  --result '집중 dispatch 테스트를 통과했다' --agent
taplctl task block TASK-006 --execution-id <TASK-006의-execution-id> \
  --verification 'README 검토' --blocker '필요한 제품 결정이 없다' \
  --next-action '결정을 받은 뒤 task를 다시 dispatch한다' --agent
taplctl task skip TASK-006 --execution-id <TASK-006의-execution-id> \
  --result 'Plan 변경 후 더 이상 필요하지 않다' --agent
```

Dispatch는 완료되지 않은 dependency, 서로 다른 plan 또는 group, 겹치는 path
(파일과 그 부모 directory의 충돌 포함), 기존 active work와 충돌하는 owned path를
거부합니다. 한 group의 task는 서로 독립적이어야 하므로 같은 group의 다른 task에
dependency를 걸지 마세요. Worker 일부를 spawn하지 못했거나 root runtime이
중단되면, 실행된 task를 정산하고 active batch 전체를 recover 또는 cancel한 뒤에만
재시도합니다.

```sh
taplctl batch recover docs-20260727 --reason 'Root runtime이 중단되었다' --agent
taplctl batch cancel docs-20260727 --block \
  --reason '한 worker를 시작할 수 없다' --agent
```

`taplctl status --agent`로 active batch와 execution ID를 확인하고,
`taplctl next --agent`로 가장 안전한 다음 lifecycle 명령을 확인하세요. 현재
batch가 active인 동안에는 두 번째 batch를 시작하지 마세요.

## 설치 상세

### 필요 환경

- `venv` 모듈이 포함된 Python 3.11 이상. 함께 제공하는 Homebrew formula는
  `python@3.12`를 사용합니다.
- FTS5와 extension loading을 지원하는 SQLite.
- Windows 독립형 설치 프로그램의 경우 Windows 10 또는 11, 그리고 Windows PowerShell
  5.1 이상 또는 PowerShell 7.
- 함께 제공하는 formula로 설치할 경우 Homebrew.
- Source 개발 또는 build를 할 경우 `uv`.
- `taplctl viewer`용 웹 브라우저. VS Code는 선택 가능한 extension에만 필요합니다.

### Linux (`curl | sh`)

독립형 설치 프로그램은 Linux를 지원하며 함께 제공되는 브라우저 viewer를 포함한
`taplctl` CLI를 설치합니다.

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

`curl`, `venv` 모듈이 포함된 Python 3.11 이상, 그리고 쓰기 가능한 설치 디렉터리가
필요합니다. 기본 설치 경로는 `${XDG_DATA_HOME:-$HOME/.local/share}/tapl` 및
`${XDG_BIN_HOME:-$HOME/.local/bin}`입니다. 다른 경로가 필요하면 해당 XDG 변수 또는
`TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`를 설정하세요.

설치 프로그램은 shell 시작 파일이나 Codex hook을 수정하지 않습니다. `PATH` export가
출력되면 현재 shell에서 실행하고, 이후 shell에도 적용되도록 shell 설정 파일에 추가하세요.
`PATH`에서 `taplctl`을 찾을 수 있게 되면 [Codex hook 설정](#codex-hook-설정)에 나온 것처럼
`taplctl install user`(또는 `taplctl install repo`)를 실행한 다음 `taplctl validate`를
실행하세요.

### Windows (`irm | iex`)

PowerShell 설치 프로그램은 Windows 10과 11을 지원하며 함께 제공되는 브라우저
viewer를 포함한 `taplctl` CLI를 설치합니다.

```powershell
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

Windows PowerShell 5.1 이상 또는 PowerShell 7, `venv` 모듈이 포함된 Python 3.11 이상,
그리고 쓰기 가능한 사용자별 설치 디렉터리가 필요합니다. 기본 관리 설치 루트는
`%LOCALAPPDATA%\tapl`이고 공개 launcher는 `%LOCALAPPDATA%\tapl\bin\taplctl.cmd`입니다.
`TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`, `TAPL_INSTALL_MANIFEST_URL`로 각각 설치 루트,
launcher 디렉터리, release manifest URL을 재정의할 수 있습니다.

설치 프로그램은 launcher 디렉터리가 사용자 `PATH`에 아직 없을 때만 한 번 추가하고,
현재 PowerShell 세션도 갱신합니다. 새 프로세스에는 사용자 `PATH` 항목이 적용되며,
시스템 `PATH`는 바꾸지 않고 관리자 권한도 필요하지 않습니다. Codex hook은 자동으로
설치하지 않습니다. `PATH`에서 `taplctl`을 찾을 수 있게 되면 [Codex hook 설정](#codex-hook-설정)에
나온 것처럼 `taplctl install user`(또는 `taplctl install repo`)를 실행한 다음
`taplctl validate`를 실행하세요.

설치 프로그램은 release manifest를 검증하고, 활성화 전에 내려받은 wheel이 공개된
SHA-256과 일치하는지 확인합니다. `irm | iex` 명령을 사용할 때는 환경의 신뢰 절차에 맞게
script source도 검토하세요. CLI wheel 자체는 platform-independent이지만 Python 의존성은
Windows Python version 및 architecture와 호환되는 wheel이 필요합니다. 일반적인 지원 Windows
Python 환경에서는 pip가 이를 설치하지만, 드문 architecture 또는 아주 새로운 Python release에서는
호환 wheel이 없어 build tool이 필요하거나 설치에 실패할 수 있습니다.

### Homebrew

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
```

그 다음 두 formula 중 하나만 설치합니다.

```sh
# 기본 workflow tracking
brew install taplctl
```

```sh
# Semantic search 지원 포함
brew install taplctl-semantic
```

두 formula 모두 release에 포함된 wheel bundle에서 고정된 MCP runtime을 설치합니다.
Semantic formula는 여기에 선택 기능인 embedding 및 vector search stack을 추가합니다.
Homebrew 설치 중에는 PyPI에서 Python package 의존성을 해석하지 않습니다.

설치한 formula에 맞춰 브라우저 viewer를 로그인 시 자동 시작할 수 있습니다.

```sh
brew services start taplctl
# 또는
brew services start taplctl-semantic
```

두 formula service 모두 `taplctl viewer`를 `127.0.0.1:8000`에서 실행합니다.
해당 URL을 열고 첫 방문 시 workspace를 선택하세요. Semantic formula의 Homebrew
service는 의도적으로 `searchd`를 시작하지 않습니다. Semantic model을 미리
로딩하려면 별도로 실행하세요.

```sh
taplctl searchd start
taplctl searchd status
```

8000 포트가 사용 중이면 Homebrew service를 중지한 뒤
`taplctl viewer --port PORT`를 수동 실행하세요.

### Codex hook 설정

어떤 방식으로 `taplctl`을 설치했든, 다음 중 Codex에 연결할 범위를 선택하세요.

```sh
# 대부분의 사용자: 내 Codex 계정에 한 번 설치
taplctl install user

# 또는 현재 repository에만 설치
taplctl install repo

taplctl validate
```

설치 프로그램은 `taplctl mcp`를 실행하는 활성화된 `mcp_servers.tapl` 항목도
추가합니다. 새 stdio 서버가 로드되도록 설치 후 Codex를 재시작하세요.

설치 후 Codex가 처음 확인을 요청할 때 설치된 hook을 trust 해주세요.

<p align="center">
  <img src="assets/tapl-trust-hook.png" alt="설치된 tapl hook에 대한 Codex trust prompt" />
</p>

설치 병합 정책:

- `hooks.json`은 managed merge를 합니다. 기존 non-tapl hook은 보존하고, tapl이
  관리하는 hook만 교체합니다.
- `.codex/config.toml`은 TOML 병합을 합니다. 기존 사용자 값이 우선하고,
  tapl template에만 있는 누락 key와 TAPL MCP 서버 설정을 추가합니다. MCP
  launcher는 hook과 동일하게 resolve된 `taplctl` 실행 경로를 사용합니다.
- tapl runtime `config.toml`(`.tapl/config.toml` 또는 `~/.tapl/config.toml`)은
  최초 설치 때 생성합니다. 설치된 tapl version이 바뀌면 updated default로
  덮어쓸지, 기존 값을 유지하면서 누락된 default key만 추가할지 묻습니다.
  hook/JSON 같은 non-interactive refresh에서는 기존 값을 유지하고 누락 key만
  추가합니다.
- `--force`는 managed key에 대해 tapl template 값을 우선하게 하되, 관련 없는
  Codex config key는 보존하고 tapl runtime `config.toml`은 덮어씁니다.
- `--tapl-config-policy {prompt,overwrite,merge}`로 tapl runtime config upgrade
  동작을 명시할 수 있습니다.
- Agent template은 기본적으로 create-or-skip이며, `--force`를 주면 덮어씁니다.

### Source

```sh
cd tapl
uv sync
uv run taplctl --version
uv build
```

Source checkout에서 선택 기능인 semantic search를 개발하거나 실행할 때는
`uv sync --extra semantic`을 사용하세요.

### 업데이트

`taplctl update`는 Linux `curl | sh` 또는 Windows PowerShell 설치 프로그램으로 설치한
경우를 관리합니다. 업데이트를 활성화하기 전에 release manifest와 wheel SHA-256을 검증합니다.
Homebrew 또는 source checkout으로 설치한 경우에는 변경하지 않습니다.

```sh
# Linux curl-sh 설치
taplctl update --check
taplctl update

# 동일한 방법: 설치 프로그램을 다시 실행해 최신 관리 release 가져오기
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

```powershell
# Windows PowerShell managed 설치
taplctl update --check
taplctl update

# 동일한 방법: 설치 프로그램을 다시 실행해 최신 managed release 가져오기
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

Homebrew 설치는 설치한 formula에 맞게 업데이트하세요.

```sh
# 기본 formula
brew update && brew upgrade taplctl

# Semantic search formula
brew update && brew upgrade taplctl-semantic
```

Source checkout은 source workflow로 checkout과 의존성을 업데이트하세요. Release CLI
wheel은 platform-independent이지만, Python 의존성에는 대상 platform과 호환되는 wheel이
여전히 필요합니다. 특히 Alpine처럼 musl 기반인 Linux 시스템에서는 호환되는 wheel 또는
로컬 build tool이 필요할 수 있습니다. Windows에서도 드문 architecture 또는 아주 새로운
Python release에서는 같은 상황이 발생할 수 있으며, 의존성을 설치하지 못하면 설치에 실패할 수
있습니다.

## 자주 쓰는 명령

```sh
taplctl init --workspace-root /path/to/workspace
taplctl doctor
taplctl status
taplctl validate
taplctl viewer
taplctl viewer --port 9000
taplctl update --check
taplctl update
taplctl search "query"
taplctl item show --id 1
taplctl archive list
taplctl archive show --id <id>
taplctl reindex
taplctl searchd start
taplctl searchd status

# 고급 수동 workflow 보정/디버깅(flag help only)
taplctl run set --help
taplctl plan set --help
taplctl task set --help
taplctl finding add --help
taplctl approval set --help
taplctl archive create --help
```

`taplctl search`는 기본 7개 결과를 반환합니다. 기본값은 `.tapl/config.toml` 또는
`~/.tapl/config.toml`의 `[search] max_results`로 바꿀 수 있고, 한 번만 바꿀
때는 `--limit`을 사용합니다. 검색 결과가 관련 있고 snippet만으로 맥락이
부족하면, 결과의 numeric `id`를 `taplctl item show --id <id>`에 넘겨
전체 record detail을 확인한 뒤 사용합니다.

### SubAgent 위임 설정

TAPL은 repo-local `.tapl/config.toml`을 `~/.tapl/config.toml`보다 먼저 읽으므로,
두 파일이 모두 있으면 repository 설정이 우선합니다. TAPL이 위임 정책과
model/reasoning allowlist를 MCP 서버 지침에 포함할지 다음과 같이 설정합니다.

```toml
[subagents]
enabled = true

[subagents.models]
"gpt-5.6-sol" = ["xhigh", "max"]
"gpt-5.6-terra" = ["high", "xhigh", "max"]
"gpt-5.6-luna" = ["high", "xhigh"]
```

활성화하면 MCP 정책은 root agent가 모든 실행 작업의 복잡도를 판단하고,
설정된 model/reasoning 조합 중 효율적인 조합으로 해당 작업을 SubAgent에게
위임하도록 합니다. TAPL이 제공하는 MCP 지침 내용을 끄려면 다음처럼 설정합니다.

```toml
[subagents]
enabled = false
```

`enabled = false`이면 TAPL은 SubAgent 위임 정책과 model/reasoning allowlist를
MCP 서버 지침에 포함하지 않습니다. 이 설정은 `AGENTS.md`처럼 다른 출처에 있는 별도의
위임 지시까지 제거하지는 않습니다.

설정한 model 목록은 정책상 allowlist일 뿐이며, runtime에 model을 설치하거나
지원 가능 여부를 보장하지는 않습니다. Root agent는 설정된 model/reasoning
조합과 현재 runtime이 실제 지원하는 조합의 교집합만 사용해야 하며, 지원하지
않는 설정 조합을 선택해서는 안 됩니다. 이 교집합이 비어 있으면 root agent가
해당 작업을 직접 실행합니다.

Plan/task workflow 정책은 config로 바꿀 수 없습니다. TAPL은 항상 매우 상세한
계획, 계획 확정 전의 명시적 사용자 승인, 독립된 edit·migration·verification 단위의
작업 분할, durable edit 전의 실행 승인 기록을 요구합니다. 이 고정 정책은 MCP
서버 지침과 typed tool schema가 제공하며 CLI help는 수동 fallback일 뿐입니다.

## 소스 구조

```text
.
├── .codex/                    # taplctl install repo가 생성하는 repo-local 파일
├── .tapl/config.toml          # Repo-local runtime config
├── tapl/.codex/               # taplctl package에 포함되는 Codex config/hook template
├── tapl/.tapl/config.toml     # 기본 tapl config template
├── tapl/taplctl/              # Python CLI와 workflow harness 구현
├── tapl/tests/                # Python tests
├── tapl/pyproject.toml        # taplctl package metadata
├── vscode-extension/          # Optional VS Code workflow viewer
├── README.md                  # English README
└── README.ko.md               # Korean README
```

Runtime state와 local build output은 source contract에 포함하지 않습니다.

```text
.tapl/tapl.db
tapl/.venv/
tapl/dist/
```

## Contributor 검증

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl build
npm --prefix vscode-extension run compile
git diff --check
taplctl validate
```

## 라이선스

MIT. [LICENSE.md](LICENSE.md)를 참고하세요.
