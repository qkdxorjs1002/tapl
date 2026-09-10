# TAPL 설치·운영 가이드

[README로 돌아가기](../README.ko.md) · [English guide](guide.md)

[필수 환경](#requirements) · [Homebrew](#homebrew) · [Linux](#linux) · [Windows](#windows) · [Codex 연결](#connect) · [Viewer](#viewer) · [설정](#configuration) · [SubAgent](#subagents) · [문제 해결](#troubleshooting)

<a id="requirements"></a>

## 필수 환경

- `venv` 모듈을 포함한 Python 3.11 이상. Homebrew는 `python@3.12`를 사용합니다.
- FTS5와 확장 로딩을 지원하는 SQLite.
- formula 설치에는 Homebrew, 소스 개발에는 `uv`.
- Windows 설치 스크립트에는 Windows PowerShell 5.1 이상 또는 PowerShell 7.
- `taplctl viewer`에는 웹 브라우저, 선택 확장 기능에는 VS Code.

TAPL의 릴리즈 wheel은 플랫폼에 독립적이지만, Python 의존성에는 호환되는 wheel이 필요합니다. 드문 아키텍처, 새로 출시된 Python, Alpine 같은 musl Linux에서는 로컬 빌드 도구가 필요할 수 있습니다.

<a id="homebrew"></a>

## Homebrew

먼저 tap을 추가한 뒤 필요한 채널 **하나만** 설치하세요. 세 formula는 같은 실행 파일을 설치하므로 함께 설치할 수 없습니다. 채널을 바꿀 때는 기존 formula를 먼저 제거하세요.

```sh
brew tap qkdxorjs1002/tap

# 안정판: SQLite 전문 검색
brew trust --formula qkdxorjs1002/tap/taplctl
brew install taplctl
taplctl install user
```

```sh
# 안정판: 시맨틱 검색 의존성 포함
brew trust --formula qkdxorjs1002/tap/taplctl-semantic
brew install taplctl-semantic
taplctl install user
```

```sh
# 프리릴리즈를 포함해 가장 최근에 공개된 릴리즈
brew trust --formula qkdxorjs1002/tap/taplctl-pre
brew install taplctl-pre
taplctl install user
```

`taplctl-pre`에는 `taplctl@pre` 별칭도 있습니다. 이 가이드에서는 정식 formula 이름을 사용합니다. `taplctl`과 `taplctl-semantic`은 안정판만 따릅니다.

Homebrew는 릴리즈에 포함된 wheel 묶음의 고정 의존성을 설치하며, 설치 중 PyPI에서 패키지를 해석하지 않습니다. 현재 formula는 `taplctl`, `tapl-mcp`, `tapl-hook`을 모두 연결하므로 실행 경로를 따로 지정할 필요가 없습니다.

formula를 업그레이드하거나 재설치하면 해당 TAPL viewer 서비스가 이미 실행 중일 때만 자동 재시작을 시도합니다. 중지된 서비스와 신규 설치는 중지 상태로 유지됩니다. 직접 실행한 `searchd`나 MCP stdio 프로세스에는 적용되지 않습니다.

<a id="linux"></a>

## Linux 독립형 설치

```sh
curl -fsSL https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.sh | sh
```

installer에는 `curl`, Python 3.11+와 `venv`, 쓰기 가능한 install directory가 필요합니다. 기본값은 `${XDG_DATA_HOME:-$HOME/.local/share}/tapl`과 `${XDG_BIN_HOME:-$HOME/.local/bin}`입니다. 해당 XDG 변수 또는 `TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`로 바꿀 수 있습니다.

shell startup file이나 Codex hook은 수정하지 않습니다. 출력된 `PATH` export를 적용하고 필요하면 영구적으로 설정한 뒤, 아래에서 TAPL을 Codex에 연결하세요.

<a id="windows"></a>

## Windows 독립형 설치

```powershell
irm https://raw.githubusercontent.com/qkdxorjs1002/tapl/main/install.ps1 | iex
```

installer는 Windows 10/11, Windows PowerShell 5.1+ 또는 PowerShell 7, Python 3.11+와 `venv`, 쓰기 가능한 user directory를 지원합니다. 기본값은 `%LOCALAPPDATA%\tapl`, launcher는 `%LOCALAPPDATA%\tapl\bin\taplctl.cmd`입니다. `TAPL_INSTALL_ROOT`, `TAPL_BIN_DIR`, `TAPL_INSTALL_MANIFEST_URL`로 경로나 manifest를 바꿀 수 있습니다.

user `PATH`만 갱신하고 administrator 권한은 필요하지 않습니다. activation 전에 release manifest를 검증하고 wheel SHA-256을 확인합니다. Codex hook은 자동 설치하지 않습니다. 별도의 신뢰 절차가 필요한 환경이라면 script를 먼저 검토하세요.

<a id="connect"></a>

## TAPL을 Codex에 연결

Homebrew의 세 formula 모두 같은 명령으로 연결합니다.

```sh
taplctl install user
```

설치 프로그램이 `PATH`에서 `taplctl`을 찾고 같은 디렉터리의 `tapl-mcp`와
`tapl-hook`을 사용합니다. 일반적인 Homebrew 설치에서는 경로 옵션이 필요하지 않습니다.

<details>
<summary>선택 사항: 특정 설치본 지정</summary>

자동 탐색이 다른 실행 파일을 선택하거나 특정 설치본을 지정해야 할 때만
`--taplctl-command`를 사용하세요. 예를 들면 다음과 같습니다.

```sh
taplctl install user --taplctl-command "$(brew --prefix taplctl)/libexec/bin/taplctl"
```

`taplctl-semantic`이나 `taplctl-pre`를 설치했다면 formula 이름을 바꾸세요.
지정한 실행 파일을 기준으로 해당 설치본의 MCP와 hook 경로를 찾습니다.

</details>

독립형 설치는 아래처럼 실제 `taplctl` 실행 파일을 지정합니다. 독립형 설치 스크립트의 기본 채널은 최신 안정판입니다.

Linux 독립형 설치:

```sh
taplctl install user --taplctl-command "$(realpath "$(command -v taplctl)")"
```

Windows 독립형 설치:

```powershell
$taplRoot = if ($env:TAPL_INSTALL_ROOT) { $env:TAPL_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA "tapl" }
$taplInstall = Get-Content -Raw (Join-Path $taplRoot "install.json") | ConvertFrom-Json
taplctl install user --taplctl-command (Join-Path $taplInstall.venv "Scripts\taplctl.exe")
```

위 명령은 현재 사용자의 Codex 환경 전체에 연결합니다. 현재 저장소에만 연결하려면 `user`를 `repo`로
바꾸세요.

이 명령은 `tapl-mcp`를 위한 활성화된 `mcp_servers.tapl` entry와 `tapl-hook` Codex
lifecycle hook을 추가합니다. 이후 Codex를 재시작하세요. Codex가 처음 확인을 요청하면
설치된 hook을 신뢰합니다.

<p align="center">
  <img src="../assets/tapl-trust-hook.png" alt="설치된 TAPL hook에 대한 Codex trust prompt" />
</p>

<a id="viewer"></a>

## Viewer 열기

초기화된 작업 공간에서 실행합니다.

```sh
taplctl viewer
# tapl viewer: http://127.0.0.1:8000

taplctl viewer --port 9000  # 8000 포트가 사용 중일 때
```

viewer는 `127.0.0.1`에서만 수신하고 브라우저를 자동으로 열지 않으며 `Ctrl+C`로
종료합니다. 가장 가까운 `.tapl/tapl.db`가 선택됩니다. Homebrew 로그인 서비스처럼
작업 공간 없이 시작하면 초기화된 작업 공간 폴더를 선택하는 화면이 나타납니다.
브라우저는 마지막으로 연결에 성공한 폴더를 기억합니다.

### 리버스 프록시와 터널

다른 주소로 viewer를 제공하려면 브라우저가 접근하는 정확한 origin을 허용하세요.

```sh
taplctl viewer --allowed-origin https://tapl.example.com
```

서비스에 지속해서 적용하려면 `~/.tapl/config.toml`에 저장하고 설치한 formula의 서비스를 재시작합니다.

```toml
[viewer]
allowed_origins = ["https://tapl.example.com", "https://tapl.internal.example"]
```

```sh
brew services restart taplctl
```

origin은 HTTP(S) 스킴, 호스트, 선택적인 포트만 포함합니다. 여러 origin은 `--allowed-origin`을 반복하거나 설정 배열에 추가하세요. CLI와 설정의 origin은 합쳐집니다. TAPL은 계속 loopback에서만 수신하며, 인증과 TLS는 프록시에서 처리합니다. 신뢰할 수 없는 네트워크에 노출할 때는 와일드카드 origin 규칙을 피하세요.

### 서비스와 시맨틱 검색

설치한 Homebrew formula를 login 때 자동 시작하려면 `brew services start taplctl`,
`brew services start taplctl-semantic`, 또는 `brew services start taplctl-pre`를
사용하세요. 모든 service는 8000 포트에서 viewer를 제공합니다.

semantic formula는 preloaded search process를 의도적으로 시작하지 않습니다. 필요하면
`taplctl searchd start`와 `taplctl searchd status`를 실행하세요.

선택 VS Code extension은 workspace별 persistent `tapl-mcp` client를 사용합니다.
executable을 못 찾으면 `taplWorkflow.taplMcpPath`를 설정하세요.

### 재개와 검색

Codex는 typed MCP tool로 current state, archive detail, history를 읽습니다. SQLite FTS는
모든 설치에서 동작합니다. embedding/vector search에는 semantic extra 또는
`taplctl-semantic` formula를 설치하고, 기존 workspace의 index를 다시 만들 때는
`taplctl reindex`를 사용하세요.

### 병렬 작업

TAPL은 execution manifest를 조율하지만 worker를 spawn하지는 않습니다. Codex/root
runtime이 SubAgent를 만들고 관리합니다. 병렬 executable task는 dependency가 완료되고
서로 겹치지 않는 file 또는 directory를 소유할 때만 유효합니다. `strategy`는 강제 결과가 아니라
판단 bias입니다. agent는 task independence, 필요한 context, risk, coordination cost,
parallel value를 평가한 뒤 root 실행 또는 위임을 선택합니다. 순차 task, 공유 file 또는
state, root 수준의 결정은 main agent가 수행합니다. 사용자 task profile은 반복 작업에
대한 advisory 특성과 순서가 있는 model/effort 선호를 추가할 수 있습니다. 이는 model ID의
영구 역할이 아닌 교체 가능한 preset이며, agent는 이유를 기록하고 profile이나 candidate를
override할 수 있습니다.

범위가 정해진 읽기 전용 파일 탐색이나 조사는 계획 전후에 host SubAgent에 위임할 수
있으며, 이를 위해 task, batch, `owned_paths`를 별도로 만들 필요는 없습니다. workflow
mode 분류 전, 요청 자체로 충분하거나 이미 파악한 범위가 충분하면 scout를 생략합니다.
알려진 대상의 확인 한 번이면 충분할 때는 root가 조회합니다. 저장소의 대상, dependency,
검증 범위가 불명확하면 **자격을 충족하는 읽기 전용 SubAgent 하나**를 우선하며,
중첩 helper는 허용하지 않습니다. root는 요청과 기존 context로 위임 여부를 판단하며,
이를 결정하려고 전체 scout를 먼저 수행하지 않습니다.
이 TAPL 지침은 setup이 완료되고 위임이 활성화된 경우에 적용됩니다.
사용자 선호와 기존 strategy 및 profile을 따르며, 설정된 allowlist와
현재 runtime catalog에 모두 있는 model/effort 조합만 선택합니다.
setup이 pending이거나 위임이 비활성화되었거나 적절한 runtime candidate가 없으면
root가 조회합니다.

helper에게는 요청, 읽기·검색 범위, 남은 조회 한도, 응답 분량 제한, 제약, 중단 조건만 전달하며,
기본적으로 전체 대화 이력을 fork하지 않습니다. source, 설정, 테스트를 우선 살피고
생성 파일, dependency, minified 파일의 대량 출력을 피합니다. `file:line` 근거,
dependency, 필요한 검증, risk와 미확인 사항, 사용한 조회 횟수를 간결하게 보고합니다.

요청 분류 전에는 **root와 helper를 합쳐 대상을 좁힌 local 읽기 전용 조회를 최대 3회**까지
할 수 있습니다. root는 검색을 반복하지 않고 보고를 활용하며, 미해결 모순이나 필수 질문에만
남은 조회 한도를 씁니다. 실패해도 한도는 복구되지 않으며, 사용량이 보고되지 않으면
helper에게 배정한 한도를 모두 사용한 것으로 처리합니다. scout 중에는 root와 helper 모두
수정, 테스트 실행, 외부 조사, history 검색, TAPL 상태 변경을 할 수 없습니다. helper는
부수 효과가 있는 작업이나 workflow 기록 쓰기를 할 수 없으며, 최종 workflow mode 결정,
계획 수립, scout 이후 TAPL 상태 쓰기는 root만 담당합니다. 분류 후 조사는 해당 source와
history 규칙을 따릅니다. 저장되거나 실행 가능한 task에는 아래의 승인, dependency,
소유 범위, dispatch, 정산 요건이 그대로 적용되며, scout는 실행 승인을 우회하지 않습니다.
이는 새 설정이나 database field를 추가하지 않는 지침 정책이며, 지연 시간이나 전체 token
사용량 절감을 보장하지 않습니다.

## 워크플로와 관리 명령

`tapl-mcp`는 워크플로 애플리케이션을 직접 호출합니다. `tapl-hook`은 Codex의 수명 주기 지점에서 현재 상태를 전달하고, 실행 승인 전에 지속되는 변경이 일어나지 않도록 확인합니다. 두 구성 요소와 viewer는 저장소의 `.tapl/tapl.db`를 공유합니다.

실행 전 승인은 필요하지만 **수정·테스트·구현·검증을 직접 요청한 것 자체도 명시적인 실행 승인**입니다. 매 요청마다 별도 승인 질문이 필요한 것은 아닙니다. 작업의 범위와 위험에 따라 흐름을 분류하며, 간단한 읽기 전용 요청은 계획과 작업을 만들지 않는 가벼운 기록으로 끝날 수 있습니다.

`taplctl`은 설치와 관리용입니다. 공개 명령은 `init`, `doctor`, `update`, `install`, `config`, `viewer`, `reindex`, `searchd`의 여덟 가지입니다. 워크플로 기록 생성·조회·검색과 작업 실행 상태 관리는 에이전트가 MCP 도구로 수행합니다.

## 설치 관리

| 명령 | 용도 |
| --- | --- |
| `taplctl init --workspace-root /path/to/workspace` | workspace root 선택 또는 초기화 |
| `taplctl doctor` | 설치와 workspace 문제 진단 |
| `taplctl install SCOPE` | Codex integration 설치 또는 갱신 |
| `taplctl config set/unset` | 지원 runtime config 값 편집 |
| `taplctl viewer [--port 9000]` | local browser viewer 열기 |
| `taplctl update --check` / `update` | 독립형 설치 업데이트 확인 또는 실행 |
| `taplctl reindex` | search index 다시 만들기 |
| `taplctl searchd start` / `status` | 선택 semantic search process 관리 |

<a id="updates"></a>

### 업데이트

Linux와 Windows 독립형 설치:

```sh
taplctl update --check
taplctl update
```

updater는 release manifest와 wheel SHA-256을 검증합니다. Homebrew와 source checkout은
업데이트하지 않습니다. Homebrew라면 설치한 formula에 맞춰 `brew update` 후
`brew upgrade taplctl`, `brew upgrade taplctl-semantic`, 또는 `brew upgrade taplctl-pre`를
사용하세요.

<a id="configuration"></a>

## 작업 공간과 설정

TAPL은 `.tapl/config.toml`을 `~/.tapl/config.toml`보다 먼저 읽습니다. database는
workspace anchor 역할도 합니다. 상위 database가 없으면 첫 hook이 payload working
directory를 초기화하고, nested Git repository는 가장 가까운 workspace database를
재사용합니다. 의도적으로 독립된 nested repository에는 그 안에서
`taplctl init --workspace-root PATH`를 실행해 별도 history를 만드세요.

installation은 관련 없는 Codex setting을 보존합니다. `hooks.json`은 managed merge되고,
`.codex/config.toml`은 기존 user value를 우선하는 TOML merge입니다. runtime config는 첫
install에 생성됩니다. upgrade 때 default overwrite 또는 누락 key merge를 물을 수
있습니다. TAPL managed template value를 우선하려면 `--force`를, runtime config policy를
명시하려면 `--tapl-config-policy {prompt,overwrite,merge}`를 사용하세요.

TOML을 직접 편집하지 않고 runtime 값을 바꿀 수 있습니다.

```sh
taplctl config set search.mode hybrid
taplctl config set search.max_results 20
taplctl config set viewer.allowed_origins '["https://tapl.example.com"]'
taplctl config set subagents.strategy balanced
taplctl config unset search.mode
```

`set`은 점 표기 `KEY`와 `VALUE` 하나를 받습니다. 값은 TOML 문법을 사용하며 enum 문자열은
따옴표 없이 전달할 수 있습니다. 배열은 위 예시처럼 보통 shell에서 따옴표로 감싸세요.
`unset`은 `KEY`만 받고 해당 값을 제거해 내장 기본값을 복원합니다. 두 명령 모두 변경 후의
전체 config를 검증하며 주석과 관련 없는 설정을 보존합니다. 지원 key, 값 형식, enum
허용값, 예시는 `taplctl config --help` 또는 `taplctl config set --help`에서 확인할 수
있습니다.

지원 key는 `search.mode`(`semantic`, `bm25`, `word`, `hybrid`),
`search.max_results`(1 이상의 정수), `search.hybrid_semantic_ratio`(0.0–1.0),
`search.semantic_provider`(`local`, `daemon`, `auto`),
`search.searchd_model_idle_timeout_seconds`(0 이상의 정수),
`viewer.allowed_origins`(중복 없는 HTTP(S) origin 문자열의 TOML 배열),
`subagents.enabled`(`true` 또는 `false`), `subagents.strategy`(`conservative`,
`balanced`, `aggressive`), `subagents.setup_complete`(`true` 또는 `false`),
`subagents.preference`(free-form 문자열), `subagents.models.<model-id>`(중복 없는
reasoning-effort 문자열의 비어 있지 않은 TOML 배열), `subagents.profiles`(inline
profile table의 TOML 배열)입니다.

별도 지정이 없으면 위에서 설명한 repo-local, user-global 순서로 대상을 선택하고 두 파일이
모두 없으면 repo-local 경로를 생성합니다. 다른 파일을 편집하려면 global option을 명령
앞에 놓으세요.

```sh
taplctl --config /path/to/config.toml config set search.mode bm25
```

## 연상 기억

`[recall] enabled = true`가 기본값입니다. `tapl_summarize_run`은 선택적으로
`recall_query`를 받고 run당 한 번 최대 3개의 짧은 기억 단서를 제공합니다.
Hook, status, next-action 조회에서는 기억을 검색하지 않습니다. 먼저 단서로 탐색하고
원본 item/archive를 확인하며, 부족하면 `tapl_search_history`를 사용합니다.
기억 내용은 검토할 자료이며 실행 지시가 아닙니다.
자동 주입은 전체 1,200 UTF-8 바이트 이내로 제한합니다. 같은 SQLite의 FTS를
사용하므로 임베딩, 추가 모델 호출, 상주 프로세스가 필요하지 않습니다.

`tapl_finish_run`의 선택 필드 `memory_candidates`, `memory_uses`로 기억을
저장하거나 실제 사용을 기록합니다. 후보는 slot 1 또는 2, cue 3–5개,
240자 이하 note, `source_run_id`와 선택적 `source_item_id`를 가집니다.
검증한 함정이나 재사용할 결정처럼 원본 근거가 있는 교훈만 저장하고, 일반 완료 요약,
비밀값, 원문 덤프, 추측은 제외합니다. 사용 기록에는 memory ID와 revision,
`source_checked=true`, 구체적인 `usage`가 필요합니다. 단순 노출은 사용이 아닙니다.
기억 인자를 하나라도 전달할 때 `expected_run_id`를 반드시 지정합니다.

최종 결과를 먼저 저장한 뒤 선택적 기억 처리를 수행하므로 기억 오류가 완료 기록을
되돌리지 않습니다. 반환된 후보/사용별 오류를 확인하고 동일 run과 slot으로 재시도하되,
해당 run이 활성 상태일 때만 가능합니다. 보관된 run의 재시도가 다음 run을 수정하지
못하도록 검사합니다. 내용 수정은 신선도를 초기화하며, 검증된 재사용은 내용 수정 시각을
바꾸지 않고 반감기를 7일에서 최대 90일까지 늘릴 수 있습니다.
같은 run에서는 한 번만 강화하며, 직전 내용 수정·강화 후 24시간이 지나야 합니다.
오래된 기억도 관련성이 높으면 회상할 수 있고, 시간이 지났다는 이유로 삭제하지 않습니다.

Viewer는 기억 목록/검색, 상세, 원본 조회만 제공합니다. 기억 수정/삭제는 사용자에게서
명시적 요청을 받은 Agent가 MCP `tapl_update_memory`, `tapl_delete_memory`와
현재 `expected_revision`으로 수행합니다. 충돌 시 최신 revision을 확인합니다.
삭제한 기억은 tombstone으로 남으며 회상에서 제외됩니다. `tapl_recall`은 수동 읽기 도구입니다.

```sh
taplctl config set recall.enabled false
taplctl config unset recall.enabled  # 기본값 true 복원
```

비활성화하면 자동 저장·회상·강화가 중단되지만 수동 조회·수정·삭제는 가능합니다.
기억 workflow는 MCP를 사용하며 관리 CLI에 별도 workflow 명령을 추가하지 않습니다.
기존 DB를 schema 11로 전환할 때 원본을 `.tapl/tapl.db.pre-v11.bak`에 한 번 백업합니다.
원본 작업 기록은 유지됩니다. 이전 버전으로 되돌릴 때는 서버를 종료한 뒤 이 백업을 사용하며,
백업 이후의 작업은 별도로 보존해야 합니다.

<a id="subagents"></a>

## SubAgent 위임 설정

```toml
[subagents]
# 첫 구체적인 TAPL 요청에서 사용자 선호를 묻습니다.
setup_complete = false
enabled = true
# strategy는 판단 bias이며 각 task를 agent가 평가합니다.
strategy = "aggressive"
preference = ""

[subagents.models]
# first-use setup이 현재 runtime에서 model을 기록합니다.
```

첫 번째 구체적인 TAPL 요청 시 agent는 현재 runtime이 제공하는 model ID와 reasoning
effort를 확인한 뒤 SubAgent 사용 여부와 preference를 묻습니다. 답변은 현재 적용되는
설정 파일에 저장되고 setup이 완료됩니다. 이 과정에서 TAPL은 provider API를
호출하거나 외부 model 목록을 포함하지 않습니다. `enabled = true`는 setup 완료 후에만
효력이 있습니다. runtime catalog를 확인할 수 없으면 setup은 pending으로 남고 work는
root agent가 처리합니다. 답변을 받은 뒤 agent는 `tapl_configure_subagents`로 저장하며,
그 답변 자체가 user confirmation입니다. 명시적 model allowlist가 있거나
`enabled = false`인 기존 configuration은 완료 상태를 유지하고 user가 업데이트할 때까지
선택을 보존합니다. 새 model 설정은 user가 요청할 때에만 적용됩니다.

사용자 답변 뒤에는 전체 모델 목록도 `subagents.available_models`에 저장합니다. 각 세션의 첫 요청에서 에이전트가 현재 목록을 `tapl_get_next`에 전달하며, 모델 추가·제거 또는 추론 옵션 변경이 있으면 재설정 여부를 제안합니다. 기존 설정을 유지하겠다고 답하면 선택한 모델은 그대로 두고 확인한 목록만 갱신하므로 같은 변경을 반복해서 묻지 않습니다. 목록이 없는 기존 설정도 계속 사용할 수 있으며, 에이전트가 변화 감지 기준을 한 번 기록하도록 제안할 수 있습니다.

설치 템플릿은 다음 model-neutral advisory profile을 안전 우선 순서로 포함합니다.

| Profile | 적용 task | Bias |
| --- | --- | --- |
| `high-risk-cross-cutting` | risk가 높고 범위가 넓거나 shared context·coordination이 큰 작업 | `avoid` |
| `deep-reasoning` | 복잡하거나 불확실하고 많은 context가 필요한 판단 | `neutral` |
| `general-implementation` | 일반적인 범위의 구현 작업 | `inherit` |
| `bounded-routine` | 작고 local하며 예측 가능하고 risk가 낮은 작업 | `prefer` |

profile의 candidate는 setup이 runtime-supported model/effort pair를 제공할 때까지
비어 있습니다. profile은 task characteristics와 delegation bias를 설명하며 model ID에
영구 role을 부여하지 않습니다.

명시적 `profiles = []`는 profile을 비활성화합니다. 비어 있지 않은 사용자
`subagents.profiles` 배열은 template profile을 완전히 대체하며 candidate는
`subagents.models`에 있어야 합니다.

활성화하면 TAPL은 delegation policy, 활성 profile, model/reasoning allowlist를
`tapl_get_next`로 전달합니다. matching은 advisory입니다. agent는 모든 task 특성을 평가하고
가장 구체적인 profile을 우선하며 설정 순서는 동률일 때만 사용합니다. 필요한 경우 이유를
기록해 profile/candidate를 override하고, 사용할 수 없는 candidate는 건너뛰며, 필요하면
다른 allowlisted pair 또는 root로 fallback합니다. 설치된 `.tapl/config.toml`은 선택한
model과 preference를 기록하고 모든 runtime option의 type과 허용값을 주석으로 설명합니다.

예를 들어 아래 배열은 template profile을 하나의 model-neutral preference로 대체합니다.

```toml
[[subagents.profiles]]
name = "release-automation"
characteristics = "bounded deployment steps with a known rollback"
delegation_bias = "prefer"
candidates = []
```

`strategy`는 위임 방향의 bias를 결정합니다.

- `aggressive`(기본값)는 task가 독립적이고 필요한 context가 충분히 전달되며 risk가
  관리 가능하고 parallel value나 root context 절감 효과가 클 때 위임을 선호합니다.
  context 공유나 coordination cost 때문에 root가 더 나으면 위임하지 않습니다.
- `balanced`는 같은 판단 기준을 방향성 없이 적용합니다.
- `conservative`는 root 실행을 선호하며 parallel value나 root context 절감 효과가
  context 전달, coordination, risk 비용을 명확히 넘어설 때만 위임합니다.

저장되거나 실행 가능한 task에는 어떤 strategy에서도 execution approval, dependency
readiness, 배타적이고 겹치지 않는 `owned_paths`, 원자적 dispatch, 정확한 `execution_id`를
사용한 정산이 필요합니다. TAPL write와 task 간 결정은 root만 담당합니다.
dispatch는 runtime이 SubAgent를 spawn하기 전에 manifest의 model과 reasoning effort를
legacy `SubAgent Model` custom field에
기록합니다. bias를 바꾸려면 `strategy = "balanced"` 또는 `"conservative"`로, TAPL의
delegation guidance를 비활성화하려면 `enabled = false`로 설정하세요. 다른 source(예:
`AGENTS.md`)의 delegation instruction까지 제거하지는 않습니다.

각 executable task는 lifecycle 전체에서 다음 네 가지 canonical task custom field를
사용합니다.

- `Task Profile`: 선택한 profile(또는 match 없음)과 match 이유를 기록합니다.
- `Task Characteristics`: independence, 필요한 context, risk, coordination cost,
  parallel value를 기록합니다.
- `Execution Decision`: root 또는 SubAgent, model/effort, rationale, profile/model
  override를 기록합니다. task 설계 시, dispatch 전, decision이 바뀐 settlement 후에
  생성하거나 갱신합니다.
- `User Notes`: 조건부 field입니다. standard field에 없는 durable user-relevant fact만
  간결한 category/content/impact entry로 기록합니다.

legacy `SubAgent Model`은 호환성을 위해 atomic dispatch에서 계속 기록하고 SubAgent가
실행되지 않으면 생략합니다. 설정은 preference input이며 실제 runtime 지원, safety gate,
기록된 decision이 최종 기준입니다.

실행 작업은 계획과 독립적인 작업 단위, 변경 전에 기록된 실행 승인을 사용합니다. 사용자의 명시적인 수정·테스트·구현·검증 요청도 실행 승인으로 인정됩니다.

<a id="troubleshooting"></a>

## 문제 해결

| 증상 | 할 일 |
| --- | --- |
| Codex가 TAPL을 찾지 못함 | `taplctl doctor` 실행, 위 환경별 연결 명령으로 갱신 후 Codex 재시작 |
| 독립형 설치 뒤 `taplctl`을 찾지 못함 | installer가 출력한 `PATH` export를 적용하고 shell profile에 추가 |
| viewer가 workspace를 찾지 못함 | 초기화하거나 `.tapl/tapl.db`가 있는 folder를 선택 |
| 8000 포트 사용 중 | Homebrew service를 멈추거나 `taplctl viewer --port PORT` 실행 |
| Homebrew formula 충돌 | 다른 formula를 선택하기 전에 설치된 TAPL formula 제거 |
