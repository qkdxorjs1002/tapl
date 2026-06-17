<p align="center">
  <img src="assets/tapl-readme-hero-with-text.png" alt="tapl: Harness over prompting. State over files." />
</p>

# tapl

[English](README.md)

`tapl`은 Codex를 위한 workflow harness입니다. 사용자 전역에는 하나의
`taplctl` command를 설치하고, 각 저장소의 workflow state는 SQLite로
repo-local에 보관하며, Codex hook으로 agent 작업을 추적 가능하고 다시
이어갈 수 있게 만듭니다.

## 소개

Agent 작업은 보통 프롬프트에서 시작하지만, 실제 개발 작업에는 프롬프트
텍스트만으로 부족한 부분이 있습니다. 현재 plan, 실행 가능한 task, finding,
lifecycle event, 검색 가능한 history, tool 사용을 관찰하거나 차단할 경계가
필요합니다.

`tapl`은 그 작은 제어면을 제공합니다. Agent를 대체하지 않고, context 압축,
session resume, 긴 repository 작업을 지나도 남아 있는 durable workflow surface를
agent에게 제공합니다.

## 이게 무엇인지

`tapl`은 다섯 가지로 구성됩니다.

- `taplctl`: agent, hook, 사람, VS Code viewer가 함께 사용하는 CLI.
- `.tapl/tapl.db`: active run, plan, task, finding, approval, event, archive,
  embedding을 저장하는 repo-local SQLite DB.
- Codex hooks: `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`,
  `PostToolUse`, `Stop` lifecycle wiring.
- Lifecycle context: 현재 repo state, 적용 지침, command help 위치를 알려주는
  짧은 상태 기반 안내.
- Search/archive 도구: 현재 작업과 완료된 작업을 FTS 및 semantic search로 찾는 기능.

설치된 command는 전역이고 workflow state는 저장소별 local입니다. 이 분리는
설치를 단순하게 유지하면서도 한 workspace의 상태가 다른 workspace로 새지 않게
합니다.

## 왜 사용하는지

Codex 작업을 감사 가능하고 복구 가능하게 만들어야 할 때 `tapl`을 사용합니다.

- 긴 작업을 저장된 plan/task state에서 다시 이어갈 수 있습니다.
- 이전 결정과 finding을 다시 발견하지 않고 검색할 수 있습니다.
- Active workflow state 없이 durable edit가 일어나려 할 때 hook이 경고할 수 있습니다.
- 완료된 작업을 archive로 남겨 이후 검색할 수 있습니다.
- 사람과 agent가 같은 CLI를 통해 같은 SQLite state를 읽습니다.
- `AGENTS.md`를 workflow source of truth로 쓰지 않아도 됩니다.

실용적인 효과는 프롬프트 기억에 덜 의존하고, 도구가 확인할 수 있는 상태에 더
의존하게 되는 것입니다.

## 철학

- **프롬프트보다 harness**: 프롬프트는 의도를 안내하고, hook과 state는 workflow
  경계를 지킵니다.
- **파일보다 상태**: 진행 중인 workflow record는 흩어진 Markdown 대신 SQLite에
  저장합니다.
- **수동 index보다 검색**: 과거 작업은 손으로 관리하는 index 없이 발견할 수 있어야
  합니다.
- **enforce 전에 observe**: 먼저 lifecycle event와 warning을 기록하고, 유용성이
  확인된 경계에서만 blocking을 켭니다.
- **전역 command, repo-local state**: `taplctl`은 한 번 설치하고, 각 저장소의
  `.tapl/tapl.db`는 분리합니다.
- **agent와 hook의 역할 분리**: agent는 사용자 의도를 해석하고, hook은 lifecycle과
  tool-use 경계를 지킵니다.

## 원리

`tapl`은 작은 운영 모델을 따릅니다.

1. Codex가 시작되거나 사용자의 prompt를 받습니다.
2. Hook이 `taplctl hook-event`를 호출하고 현재 repo state를 읽습니다.
3. 작업이 non-trivial이면 agent가 `taplctl status --json`을 확인하고,
   config가 반영된 plan/task 규칙은 `plan_task_execute.guidance`를 따르며,
   과거 작업을 검색합니다.
4. Durable edit 전에 plan과 실행 가능한 task를 기록합니다.
5. `PreToolUse`와 `PostToolUse` hook이 workflow boundary를 observe 또는 enforce합니다.
6. 완료된 작업은 archive로 남기고 이후 `taplctl search`로 찾습니다.

설치에 사용되는 source template은 `tapl/.codex`와 `tapl/.tapl/config.toml`에
있습니다. `taplctl install user`와 `taplctl install repo`는 이 template을 사용자
Codex home, 사용자 tapl config 디렉터리, 또는 대상 저장소에 필요한 형태로
복사합니다. Runtime config는 repo `.tapl/config.toml`을 먼저 읽고, 없으면
`~/.tapl/config.toml`을 읽습니다.

## 설치방법

### 필요 환경

- Python 3.11 이상. 함께 제공하는 Homebrew formula는 `python@3.12`를 사용합니다.
- FTS5와 extension loading을 지원하는 SQLite.
- 함께 제공하는 formula로 설치할 경우 Homebrew.
- Source 개발 또는 build를 할 경우 `uv`.
- Workflow viewer를 사용할 경우에만 VS Code.

### `taplctl` 설치

Homebrew 사용시:

```sh
brew tap qkdxorjs1002/tap
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
# 또는 의미 검색 사용시
brew install taplctl-semantic
```

그 다음 Codex workflow wiring을 설치합니다.

```sh
# 사용자 폴더 전역 적용시
taplctl install user

# 현재 Repo에 적용시
taplctl install repo

taplctl doctor --json
```

`install user`는 사용자 레벨 Codex hook과 agent template 및
`~/.tapl/config.toml`을 기록합니다. `install repo`는 repo-local hook/config
파일을 만들고 `.tapl/tapl.db`를 초기화합니다.

Codex 설치 병합 정책:

- `hooks.json`은 managed merge를 합니다. 기존 non-tapl hook은 보존하고,
  tapl이 관리하는 hook만 교체합니다.
- `config.toml`은 TOML 병합을 합니다. 파일이 없으면 tapl template으로
  만들고, 파일이 있으면 기존 사용자 값이 우선하며 tapl template에만 있는
  누락 key만 추가합니다. `[features]` 같은 nested table은 재귀 병합합니다.
- `--force`는 managed `config.toml` key에 대해 tapl template 값을 우선하게
  하되, 관련 없는 사용자 key는 보존합니다. 기존 TOML을 파싱할 수 없으면
  `--force`가 template으로 교체합니다.
- Agent template은 기본적으로 create-or-skip이며, `--force`를 주면
  덮어씁니다.

Source 개발:

```sh
cd tapl
uv sync
uv run taplctl --version
uv build
```

## 사용 방법

현재 workflow state 확인:

```sh
taplctl status --json
taplctl validate --json
taplctl context --event UserPromptSubmit --json
```

`taplctl status --json`은 active run, count, approval, config, 현재 적용되는
guidance를 확인하는 workflow source of truth입니다. 현재 적용되는 plan/task
규칙은 `plan_task_execute.guidance` 아래에 있고, `taplctl validate --json`은
같은 계약을 warning 또는 error로 보고합니다.

Lifecycle context는 상태, workflow 순서, 다음에 어디를 볼지에 집중합니다. 명령
문법, 정적인 필드 작성 규칙, status/subagent 값, 예시는 하위 명령 help에서
확인합니다.

```sh
taplctl --help
taplctl plan upsert --help
taplctl task upsert --help
taplctl approval record --help
```

Plan 기록:

```sh
taplctl plan upsert \
  --id SPEC-EXAMPLE \
  --title "Example implementation plan" \
  --summary "REQ-001: 접근, 영향 파일, 실행 순서, 위험, 검증 방법을 기록한다." \
  --status Finalized \
  --json
```

실행 가능한 task 기록:

```sh
taplctl task upsert \
  --id TASK-EXAMPLE \
  --title "Implement the change" \
  --status "In Progress" \
  --spec-id SPEC-EXAMPLE \
  --goal "Make the requested change" \
  --action "Edit the relevant files" \
  --required-subagent "@junior-worker" \
  --verification "Run focused checks" \
  --json
```

durable edit 전에 명시적 실행 승인을 기록합니다.

```sh
taplctl approval record \
  --decision approved \
  --prompt "Execute TASK-EXAMPLE from SPEC-EXAMPLE" \
  --json

taplctl approval status --json
```

실행 가능한 task가 남아 있는 상태에서 새 prompt가 들어오면 lifecycle context는
남은 일을 먼저 할지, 새 요청과 합칠지, 보류하거나 archive할지, active run을
버리고 새로 시작할지를 물으라고 안내합니다.

Finding 추가와 history 검색:

```sh
taplctl finding add \
  --title "Important implementation note" \
  --finding "What was learned" \
  --impact "Why it matters" \
  --json

taplctl search "workflow dashboard" --json
taplctl search "workflow dashboard" --limit 5 --json
```

`taplctl search`는 기본 7개 결과를 반환합니다. 기본값은
`.tapl/config.toml` 또는 `~/.tapl/config.toml`의 `[search] max_results = 12`로
바꿀 수 있고, 한 번만 바꿀 때는 `--limit`을 사용합니다.

Plan/task validation은 같은 config 파일의 `[plan-task-execute]`로 제어합니다.
`plan_detail`, `task_granularity`, `level_subagent_aggressiveness`,
`require_execution_approval` 같은 설정은 `taplctl status --json`과
`taplctl validate --json`에 반영됩니다.

완료된 작업 archive:

```sh
taplctl archive create \
  --slug completed-change \
  --summary "What was completed and how it was verified" \
  --json
```

완료 보고에는 변경 파일과 동작, 검증 명령과 결과, 남은 위험 또는 block된 일,
workflow archive 여부를 짧게 포함합니다. Archive summary에는 원 요청, 선택한
계획, 완료된 task와 결과, 검증, 남은 일을 compact하게 남깁니다.

Semantic search index 재생성:

```sh
taplctl reindex --json
```

`vscode-extension/`의 VS Code extension은 `taplctl status`,
`taplctl archive list`, `taplctl search`, `taplctl item show`를 통해 같은 state를
읽습니다.

## 의존성 목록

`tapl/pyproject.toml` 기준 runtime dependency:

| 의존성 | 용도 |
| --- | --- |
| Python `>=3.11` | `taplctl` CLI runtime. |
| `numpy>=1.26` | Embedding과 vector operation을 위한 numeric support. |
| `sentence-transformers>=5.0.0` | Archive/search용 semantic embedding. |
| `sqlite-vec>=0.1.6` | SQLite vector search extension. |
| SQLite FTS5 | Keyword search fallback과 hybrid search 지원. |

개발 및 packaging dependency:

| 의존성 | 용도 |
| --- | --- |
| `uv` | Source environment, lockfile, package build workflow. |
| `pytest>=8` | Python test dependency. |
| `pyyaml>=6.0` | Test/development dependency. |
| Homebrew | Local formula install과 formula test. |
| Node.js 및 npm | VS Code extension build workflow. |
| TypeScript | `vscode-extension/src`를 `vscode-extension/out`으로 compile. |
| VS Code `^1.90.0` | Optional workflow viewer host. |

설치 후 `taplctl doctor --json`으로 dependency 상태를 확인할 수 있습니다.

```json
{
  "numpy": true,
  "sentence_transformers": true,
  "sqlite_vec": true
}
```

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
├── tap/Formula/taplctl.rb     # Homebrew formula
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
ruby -c tap/Formula/taplctl.rb
git diff --check
taplctl validate --json
```

## 라이선스

MIT. [LICENSE.md](LICENSE.md)를 참고하세요.
