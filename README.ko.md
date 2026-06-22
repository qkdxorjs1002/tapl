<p align="center">
  <img src="assets/tapl-readme-hero-with-text.png" alt="tapl: Harness over prompting. State over files." />
</p>

# tapl

[English](README.md)

`tapl`은 Codex CLI가 저장소 안에서 진행하는 개발 작업을 놓치지 않도록
기록합니다. 요청마다 사용자의 지시, Codex의 plan, task, finding, approval,
lifecycle event, archive, 검색 가능한 history를 repo-local SQLite DB에
저장합니다. 코드는 여전히 Codex가 쓰고, `tapl`은 작업 중 상태 확인과
context가 사라진 뒤의 재개를 가능하게 합니다.

```sh
####################################
# Homebrew tap 추가
####################################

brew tap qkdxorjs1002/tap
brew trust qkdxorjs1002/tap

####################################
# taplctl 설치
####################################

### Choice 1. 의미 검색 없이 설치
brew install taplctl

### Choice 2. 의미 검색 포함 설치 (권장)
brew install taplctl-semantic

### Option. 미리 로딩된 의미 검색 데몬 자동 시작
brew services start taplctl-semantic

####################################
# Codex hooks, configs 설치
####################################

### Choice 1. 사용자 전역에 설치 (권장)
taplctl install user

### Choice 2. 레포지터리에 설치
taplctl install repo

####################################
# taplctl 점검
####################################

taplctl doctor --json
```

`taplctl install user` 또는 `taplctl install repo` 실행 후에는 Codex가 처음
확인을 요청할 때 설치된 hook을 trust 해줘야 합니다.

<p align="center">
  <img src="assets/tapl-trust-hook.png" alt="설치된 tapl hook에 대한 Codex trust prompt" />
</p>

## 어떻게 동작하나요?

핵심은 또 하나의 prompt template이 아닙니다. 평범한 Codex CLI 요청 주변에
상태가 생기는 것입니다. 아래 capture-style 이미지는 이번 README 재작성 중
`tapl`이 기록한 명령 흐름을 반영합니다.

<p align="center">
  <img src="assets/tapl-codex-iterm-demo.svg" alt="README 파일을 편집하기 전에 tapl state를 사용하는 Codex CLI terminal-style 캡처" />
</p>

위 terminal 흐름은 `tapl`이 Codex에게 노출하는 workflow contract입니다.

```sh
taplctl status --json
taplctl search 'README self PR codex cli screenshot' --json
taplctl plan set --id PLAN-001 ...
taplctl task set --id TASK-001 ...
taplctl approval set --decision approved ...
```

상태는 `.tapl/tapl.db`에 저장됩니다. 그래서 다음 Codex session, hook, 사람,
VS Code viewer가 같은 run을 확인할 수 있습니다.

## 왜 필요한지

Codex session은 일을 잘합니다. 하지만 긴 개발 작업에는 마지막 prompt 이상의
정보가 필요합니다.

- 사용자가 무엇을 요청했나?
- agent가 어떤 plan을 골랐나?
- 아직 남은 task는 무엇인가?
- durable file edit가 승인됐나?
- 구현 중 무엇을 배웠나?
- 다음 session이 그 history를 검색할 수 있나?

`tapl`은 하나의 전역 CLI와 repo-local SQLite DB로 이 질문에 답합니다.

## 기능

설치 후에는 이 workflow가 Codex 사용 중 자동으로 실행됩니다. Hook이
`taplctl`을 호출하고, lifecycle context가 Codex에게 어떤 state를 기록해야
하는지 알려줍니다.

### 1. 편집 전 상태 확인

`taplctl status --json`은 현재 run의 source of truth입니다.

```json
{
  "active_run": {
    "request_summary": "Rewrite README.* as self-PR docs..."
  },
  "approvals": {
    "execution": {
      "state": "approved"
    }
  },
  "task_counts": {
    "In Progress": 1,
    "Pending": 3
  }
}
```

Workflow contract가 없으면 hook이 경고하거나 막을 수 있습니다. Agent는 chat
history를 추측하지 않고 저장된 state에서 이어갈 수 있습니다.

### 2. 도구가 읽을 수 있는 plan과 task

Plan과 task는 흩어진 Markdown 메모가 아니라 first-class record입니다.
Plan과 task를 설정한 뒤에는 task 실행을 시작하거나 이어가기 전에 execution
approval을 설정합니다.

```sh
taplctl plan set \
  --id PLAN-001 \
  --title "Example implementation plan" \
  --summary "REQ-001: approach, files, order, risks, validation" \
  --status Finalized \
  --json

taplctl task set \
  --id TASK-001 \
  --title "Implement the change" \
  --status "In Progress" \
  --spec-id PLAN-001 \
  --goal "Make the requested behavior work" \
  --action "Edit the relevant files" \
  --required-subagent "@senior-worker" \
  --verification "Run focused checks" \
  --json

taplctl approval set \
  --decision approved \
  --prompt "Execute PLAN-001 tasks" \
  --json

taplctl task set \
  --id TASK-001 \
  --status Completed \
  --result "Focused checks passed" \
  --json
```

설정된 workflow guidance는 Codex lifecycle context로 주입됩니다. 정확한 필드
규칙은 command help에 둡니다.

```sh
taplctl plan set --help
taplctl task set --help
taplctl approval set --help
```

### 3. 검색 가능한 완료 작업 history

지난 작업은 archive로 남기고 검색할 수 있습니다.

```sh
taplctl finding add \
  --title "Important implementation note" \
  --finding "What was learned" \
  --impact "Why it matters" \
  --json

taplctl archive create \
  --slug completed-change \
  --summary "What changed, how it was verified, and what remains" \
  --json

taplctl search "workflow dashboard" --json
taplctl search "workflow dashboard" --limit 5 --json
```

Search는 SQLite FTS를 사용하고, semantic dependency를 설치하면 semantic/vector
search도 사용할 수 있습니다.

### 4. Codex lifecycle 주변의 hook

`tapl`은 다음 Codex hook wiring을 설치합니다.

- `UserPromptSubmit`
- `PreToolUse`
- `PermissionRequest`
- `PostToolUse`
- `Stop`

Hook은 `taplctl hook-event`를 호출하고 현재 workflow state를 읽은 뒤, 짧은
lifecycle context를 반환합니다. Agent는 의도를 해석하고, hook은 경계를 지킵니다.

### 5. 하나의 CLI, repo-local state

`taplctl`은 한 번 설치합니다. 각 repository는 자기 `.tapl/tapl.db`를 가집니다.

이 분리는 설치를 단순하게 유지하면서도 한 workspace의 workflow state가 다른
workspace로 새지 않게 합니다.

### 6. 선택 가능한 VS Code viewer

`vscode-extension/`의 VS Code extension은 같은 state를 다음 명령으로 읽습니다.

```sh
taplctl status --json
taplctl archive list --json
taplctl search --json
taplctl item show --id <id> --json
```

Activity bar에서 active run, plan, task, finding, archive, search result를 볼
수 있습니다.

## 설치 상세

### 필요 환경

- Python 3.11 이상. 함께 제공하는 Homebrew formula는 `python@3.12`를 사용합니다.
- FTS5와 extension loading을 지원하는 SQLite.
- 함께 제공하는 formula로 설치할 경우 Homebrew.
- Source 개발 또는 build를 할 경우 `uv`.
- Workflow viewer를 사용할 경우에만 VS Code.

### Homebrew

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
```

Semantic search 지원까지 설치할 경우:

```sh
brew install taplctl-semantic
```

그 다음 Codex에 연결합니다.

```sh
# 사용자 레벨 Codex hook과 agent template
taplctl install user

# repo-local hook, config, .tapl/tapl.db
taplctl install repo

taplctl validate --json
```

설치 병합 정책:

- `hooks.json`은 managed merge를 합니다. 기존 non-tapl hook은 보존하고, tapl이
  관리하는 hook만 교체합니다.
- `config.toml`은 TOML 병합을 합니다. 기존 사용자 값이 우선하고, tapl
  template에만 있는 누락 key를 추가합니다.
- `--force`는 managed key에 대해 tapl template 값을 우선하게 하되, 관련 없는
  사용자 key는 보존합니다.
- Agent template은 기본적으로 create-or-skip이며, `--force`를 주면 덮어씁니다.

### Source

```sh
cd tapl
uv sync
uv run taplctl --version
uv build
```

## Command Map

```sh
taplctl init
taplctl doctor --json
taplctl status --json
taplctl validate --json
taplctl context --event UserPromptSubmit --json
taplctl run set --summary "..." --json
taplctl plan set --help
taplctl task set --help
taplctl finding add --help
taplctl approval set --help
taplctl archive create --help
taplctl search "query" --json
taplctl item show --id 1 --json
taplctl reindex --json
```

`taplctl search`는 기본 7개 결과를 반환합니다. 기본값은 `.tapl/config.toml` 또는
`~/.tapl/config.toml`의 `[search] max_results`로 바꿀 수 있고, 한 번만 바꿀
때는 `--limit`을 사용합니다. 검색 결과가 관련 있고 snippet만으로 맥락이
부족하면, 결과의 numeric `id`를 `taplctl item show --id <id> --json`에 넘겨
전체 record detail을 확인한 뒤 사용합니다.

Plan/task validation은 같은 config 파일의 `[plan-task-execute]`로 제어합니다.
`plan_detail`, `task_granularity`, `planning_approval_level`,
`level_subagent_aggressiveness`, `require_execution_approval` 같은 설정은 lifecycle
context와 validation issue에 반영됩니다.

## 저장소 구조

```text
.
├── .codex/                    # taplctl install repo가 생성하는 repo-local 파일
├── .tapl/config.toml          # Repo-local runtime config
├── tapl/.codex/               # taplctl package에 포함되는 Codex hook/agent template
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

## 개발 검증

```sh
uv --directory tapl sync --extra test
uv --directory tapl run --extra test python -m unittest discover -s tests
uv --directory tapl build
npm --prefix vscode-extension run compile
git diff --check
taplctl validate --json
```

## 라이선스

MIT. [LICENSE.md](LICENSE.md)를 참고하세요.
