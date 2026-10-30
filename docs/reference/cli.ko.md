# CLI 참조

[문서 홈](../README.ko.md) · [English](cli.md)

`taplctl`은 설치·설정·런타임 확인·인덱싱·로컬 서비스를 관리합니다. Agent는 [MCP 도구](mcp.ko.md)로 워크플로 기록을 생성·실행·검색·조회합니다. 워크플로 명령은 공개 관리 CLI에 포함되지 않습니다.

## 호출과 출력

```text
taplctl [--session-id ID] [--db PATH] [--config PATH] COMMAND ...
```

전역 옵션은 명령 앞에 둡니다. `taplctl --help`, `taplctl COMMAND --help`, `taplctl install repo --help` 같은 하위 도움말로 설치 버전의 정확한 인터페이스를 확인하세요.

| 전역 옵션 | 의미 |
| --- | --- |
| `--session-id ID` | Codex 세션 식별자. 기본값은 `TAPL_SESSION_ID`, 없으면 격리된 legacy 범위 |
| `--db PATH` | DB를 사용하는 명령의 명시적 SQLite 경로 |
| `--config PATH` | 명시적 TOML 설정 파일 |
| `--version` | 설치 버전을 출력하고 종료 |
| `-h`, `--help` | 도움말을 출력하고 종료 |

DB를 명시하지 않으면 DB 사용 명령은 현재 작업 폴더의 `.tapl/tapl.db`를 선택하며 상위 DB를 찾지 않습니다. 설정은 정확한 작업 폴더의 `.tapl/config.toml`, 다음으로 `~/.tapl/config.toml`을 선택합니다. [설정](../guides/configuration.ko.md)을 참고하세요.

`init`, `doctor`, `update`, 두 `install`·`uninstall` 범위, 모든 `config` 하위 명령, `reindex`, 공개 `searchd` 하위 명령은 `--json`(구조화 JSON)과 `--agent`(간결한 XML 유사 Agent 출력) 중 **하나**를 받습니다. `viewer`에는 두 출력 옵션이 없습니다. `--dry-run`은 `install`, `uninstall`, `reindex`에만 있으며 해당 명령의 관리 변경을 미리 보여 줍니다. 모든 시작·DB 활동을 읽기 전용으로 바꾸는 공통 모드는 아닙니다.

일부 DB·서비스 명령은 명시적 `--db`나 `--config`가 없으면 실행 전에 기존 설치를 갱신할 수 있습니다. 도움말과 버전은 handler 실행 전에 종료합니다. `doctor`는 DB 상태를 초기화할 수 있고 `config get`은 파일을 쓰지 않습니다.

## 명령 목록

| 명령 | 목적 |
| --- | --- |
| `init` | 작업 공간 DB 초기화 |
| `doctor` | 런타임·설정·DB·의존성 정보 출력 |
| `install user` / `install repo` | Codex 연결·갱신 |
| `uninstall user` / `uninstall repo` | 연결 해제. 기본적으로 설정·데이터 보존 |
| `config get` / `set` / `unset` | 지원 설정 읽기·수정 |
| `viewer` | Loopback에서 브라우저 Viewer 제공 |
| `update` | 공식 독립 설치의 업데이트 확인·실행 |
| `reindex` | 선택적 시맨틱 인덱스 생성 |
| `searchd start` / `status` / `stop` | 선택적 Unix 소켓 시맨틱 데몬 관리 |

## init

```sh
taplctl init
taplctl init --workspace-root /path/to/workspace --json
taplctl --db /path/to/tapl.db init
```

`--workspace-root PATH`는 해당 폴더의 작업 공간을 명시적으로 초기화합니다. 전역 `--db`와 함께 사용할 수 없습니다. 생략하면 선택한 DB를 열거나 초기화합니다. 초기화는 Codex 연결을 설치하지 않습니다.

## doctor

```sh
taplctl doctor
taplctl --db /path/to/tapl.db doctor --json
```

TAPL·SQLite 버전, 설정, 선택 DB, 확장 로딩 기능, 스키마와 선택 의존성 상태를 출력합니다. 이 출력은 진단 정보이며 시맨틱 의존성이 없다고 전문 검색까지 사용할 수 없는 것은 아닙니다. 의도한 작업 공간에서 실행하거나 DB를 지정하세요.

## install

```sh
taplctl install user --dry-run
taplctl install user
taplctl install repo --repo /path/to/repository --mode enforce
```

| 범위 옵션 | 기본값 |
| --- | --- |
| `user --codex-home PATH` | `~/.codex` |
| `repo --repo PATH` | 현재 작업 디렉터리 |

두 범위의 공통 옵션입니다.

| 옵션 | 의미 |
| --- | --- |
| `--taplctl-command COMMAND` | 같은 위치의 `tapl-mcp`·`tapl-hook`을 찾는 기준 실행 파일 |
| `--mode {observe,enforce}` | Hook 동작. 기본값 `observe` |
| `--tapl-config-policy {prompt,overwrite,merge}` | 기존 런타임 설정 정책. 기본값 `prompt` |
| `--force` | 관리 템플릿·설정 값이 기존 관리 값을 덮어쓰도록 허용 |
| `--dry-run` | 관리 파일 쓰기 미리 보기 |
| `--json` / `--agent` | 출력 형식 선택 |

`prompt`는 버전 변경 시 기존 런타임 설정 처리를 묻고 같은 버전의 설정은 보존합니다. 명시적 `merge`는 기존 값을 유지하고 누락 기본값을 추가하며 `overwrite`는 기본값으로 교체합니다. 두 명시적 정책은 같은 버전에서도 적용됩니다. `--force`는 관리 템플릿에도 영향을 주며 런타임 설정 처리는 명시적 정책으로 선택할 수 있습니다.

사용자 또는 저장소 연결 범위를 선택하고 Codex를 재시작한 뒤 요청 시 hook을 신뢰하세요. 패키지 설치는 별개입니다. 독립 설치의 실제 실행 경로·자동 갱신·보존 규칙은 [Agent 연결](../getting-started/integrations.ko.md)에 있습니다.

## uninstall

```sh
taplctl uninstall user --dry-run
taplctl uninstall repo --repo /path/to/repository
taplctl uninstall user --purge-config --purge-db --dry-run
```

`user`는 `--codex-home PATH`, `repo`는 `--repo PATH`를 받으며 기본값은 설치와 같습니다. 두 범위 모두 `--dry-run`, `--json`, `--agent`와 다음 옵션을 받습니다.

| 옵션 | 연결 외 추가 삭제 대상 |
| --- | --- |
| `--purge-config` | 선택 범위의 `.tapl/config.toml` |
| `--purge-db` | 선택 범위의 `.tapl/tapl.db`와 `-wal`·`-shm`·`-journal` 보조 파일 |

기본 uninstall은 TAPL MCP 항목·인식되는 hook·설치 버전 표시를 제거합니다. 무관한 Codex 설정·hook, TAPL 설정·DB·백업과 다른 작업 공간은 보존합니다. Purge 옵션은 독립적이므로 두 종류를 모두 지우려는 경우에만 조합하세요. DB 삭제 전 대상 DB를 사용하는 세션을 닫으세요.

`user` 대상은 `--codex-home`(기본 `~/.codex`)을 포함한 홈 디렉터리이며 모든 프로젝트 DB를 지우지 않습니다. 실행 파일과 서비스는 남습니다. 제거하려면 [설치 방법](../getting-started/installation.ko.md)을 따르세요. 보존된 설정만으로 해제한 연결이 다시 활성화되지는 않습니다.

## config

```text
taplctl [--config PATH] config get [KEY]
taplctl [--config PATH] config set KEY VALUE
taplctl [--config PATH] config unset KEY
```

`get`은 기본값을 포함한 실제 적용값을 읽습니다. `KEY`를 생략하면 전체 설정, `search` 같은 값을 지정하면 해당 절을 읽습니다. `set`은 TOML 값 문법으로 지원 키를 쓰며 `hybrid` 같은 enum 문자열은 따옴표를 생략할 수 있습니다. `unset`은 명시적 값을 지워 내장 기본값이 적용되게 합니다. 수정 시 주석과 무관한 설정을 보존하고 변경 후 전체 설정도 유효해야 합니다.

```sh
taplctl config get
taplctl config get search.mode --json
taplctl config set search.mode hybrid
taplctl config set workflow.authoring_detail normal
taplctl config set viewer.allowed_origins '["https://tapl.example.com"]'
taplctl config unset workflow.authoring_detail
```

지원 키는 다음과 같습니다.

| 키 | 값 |
| --- | --- |
| `workflow.authoring_detail` | `precise`, `normal`, `minimal` |
| `recall.enabled` | Boolean |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` |
| `search.max_results` | 1 이상 정수 |
| `search.hybrid_semantic_ratio` | 0 이상 1 이하 숫자 |
| `search.semantic_provider` | `local`, `daemon`, `auto` |
| `search.searchd_model_idle_timeout_seconds` | 0 이상 정수 |
| `viewer.allowed_origins` | 중복 없는 HTTP(S) origin 문자열의 TOML 배열 |
| `subagents.enabled`, `subagents.setup_complete` | Boolean |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` |
| `subagents.preference` | 문자열 |
| `subagents.models.<model-id>` | 비어 있지 않고 중복 없는 추론 수준 문자열의 TOML 배열 |
| `subagents.profiles` | Profile inline table의 TOML 배열. 후보 모델·추론 수준 쌍은 허용 목록에 있어야 함 |

추측한 모델 ID를 설정에 복사하지 마세요. 호스트의 실제 위임 도구 목록과 [SubAgent 설정](../guides/subagents.ko.md)을 사용합니다. 파일 범위·기본값·예제는 [설정](../guides/configuration.ko.md)을 참고하세요.

## viewer

```sh
taplctl viewer
taplctl viewer --port 9000
taplctl viewer --allowed-origin https://tapl.example.com
taplctl --db /path/to/workspace/.tapl/tapl.db viewer
```

`--port PORT` 기본값은 `8000`입니다. `--allowed-origin ORIGIN`을 반복해 HTTP(S) 브라우저 origin을 추가할 수 있으며 CLI 값은 `viewer.allowed_origins`와 합칩니다. 경로 없이 스킴·호스트·선택 포트만 사용합니다.

서비스는 `127.0.0.1`에서만 수신하고 브라우저를 자동으로 열지 않으며 `Ctrl+C`로 종료합니다. DB 재정의가 없으면 현재 폴더의 DB만 사용하고, 없을 때 페이지에서 초기화된 작업 공간을 선택할 수 있습니다. 공개 `--workspace` 옵션은 없습니다. 서비스 시작·프록시 접속·RUN 폐기는 [Viewer와 서비스](../guides/viewer.ko.md)를 참고하세요.

## update

```sh
taplctl update --check
taplctl update --json
```

`--check`는 설치하지 않고 확인합니다. 생략하면 manifest와 SHA-256을 검증한 뒤 사용 가능한 새 릴리스를 설치합니다. 두 형식 모두 유효한 공식 독립 설치 메타데이터가 필요합니다. Homebrew·소스 설치는 각자의 업데이트 방법을 사용해야 합니다. 채널 보존과 의도적 버전 변경은 [설치](../getting-started/installation.ko.md#업데이트)를 참고하세요.

## reindex

```sh
taplctl reindex --dry-run
taplctl reindex --json
```

선택한 작업 공간의 기록으로 선택적 시맨틱 인덱스를 만듭니다. `--dry-run`은 인덱싱 작업을 미리 보여 줍니다. 시맨틱 인덱싱에는 선택 의존성이 필요하지만 전문 검색에는 필요하지 않습니다. Provider·fallback·인덱싱은 [검색](../guides/search.ko.md)을 참고하세요.

## searchd

```sh
taplctl searchd start
taplctl searchd status --json
taplctl searchd stop
```

| 하위 명령 | 출력 형식 외 옵션 |
| --- | --- |
| `start` | `--socket PATH`, `--idle-timeout SECONDS`, `--timeout-ms MS`, `--no-wait` |
| `status` | `--socket PATH`, `--timeout-ms MS` |
| `stop` | `--socket PATH`, `--timeout-ms MS` |

`--socket`은 `TAPL_SEARCHD_SOCKET`보다 우선하며 둘 다 없으면 `~/.tapl/searchd.sock`을 사용합니다. `--idle-timeout`은 0 이상이고 기본값은 `search.searchd_model_idle_timeout_seconds`(1800초)입니다. 데몬을 종료하지 않고 유휴 모델을 해제하며 `0`은 유휴 해제를 끕니다. `--timeout-ms`는 양수이며 기본값은 시작 준비 15000ms, 상태·중지 요청 250ms입니다. `--no-wait`는 준비를 기다리지 않고 반환합니다.

데몬은 Unix domain socket이 필요해 Windows에서는 사용할 수 없습니다. Windows는 로컬 시맨틱 검색이나 전문 검색 fallback을 사용할 수 있습니다. `searchd` 시작·중지는 Viewer나 Codex MCP 프로세스를 시작·중지하지 않습니다. [검색](../guides/search.ko.md)을 참고하세요.
