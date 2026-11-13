# 설정

[문서 홈](../README.ko.md) · [English](configuration.md)

현재 작업 폴더에 적용되는 설정 파일을 선택하고 유효값을 확인하며, 다른 TOML 내용을 유지한 채 지원 설정을 변경하는 방법을 안내합니다.

위임 선호는 클라이언트별로 구분합니다. `[subagents]`는 Codex, `[clients.claude-code.subagents]`는 Claude Code 설정입니다. `taplctl config get clients.claude-code.subagents --json`으로 Claude 설정을 읽고 같은 명시적 접두사로 `config set`·`unset`을 사용합니다. Claude MCP·hook 호출의 논리적 `subagents` 값은 해당 호스트로 해석됩니다. Claude는 빈 effort 배열과 명시적 상속 선택을 허용하며, [Claude 가이드](../getting-started/claude-code.ko.md#모델과-agent-실행)를 참고하세요.

## 작업 공간과 파일 선택

Agent 세션은 선택한 작업 영역의 `.tapl/tapl-{UUID}.db`에 기록하고 같은 폴더의 다른 `tapl-*.db` 이력을 읽습니다. Codex hook은 검증된 주 세션 또는 Subagent 메타데이터로 작업 영역을 정하며, 검증에 실패하면 이벤트의 기존 절대 경로 `cwd`로 돌아갑니다. Hook의 `--db`는 해석한 작업 영역의 현재 로컬 DB를 가리켜야 합니다. MCP 서버는 시작 폴더에 고정됩니다. 부모 DB·Git 루트·저장소 표식은 탐색하지 않으므로 하위 폴더의 이력은 별개입니다. 관리 CLI는 명시적인 `--db`와 `--workspace-root`를 지원합니다. UUID 보존과 기존 DB 이전은 [로컬 식별자와 공유 이력](storage.ko.md)을 참고하세요.

설정은 다음 순서로 **파일 하나를 선택**합니다.

1. 전역 `--config PATH`를 지정했다면 해당 파일. 파일이 없어도 이 경로를 선택합니다.
2. 현재 작업 폴더의 `.tapl/config.toml`이 있으면 해당 파일.
3. `~/.tapl/config.toml`이 있으면 해당 파일.
4. 둘 다 없으면 현재 폴더의 `.tapl/config.toml` 경로를 선택하고 파일을 만들기 전까지 런타임 기본값을 사용합니다.

부모 폴더 탐색이나 로컬·사용자 파일의 키별 병합은 없습니다. 로컬 파일이 있으면 누락된 키는 사용자 파일 값이 아니라 내장 기본값을 사용합니다. repo 범위 설치는 선택한 폴더에 로컬 설정을 쓰며, Git root를 찾는 규칙이 아닙니다.

## 조회와 편집

```sh
taplctl config get
taplctl config get search
taplctl config get workflow.authoring_detail
taplctl config get subagents.available_models --json
taplctl config set search.mode hybrid
taplctl config set search.max_results 20
taplctl config set subagents.strategy balanced
taplctl config unset search.mode
taplctl --config /path/to/config.toml config get search.mode --json
taplctl --config /path/to/config.toml config set search.mode bm25
```

`workflow.authoring_detail`은 기본 `auto`를 포함한 설정 선택값을 보여 주며 RUN 모드에 맞춰 변환하지 않습니다. 런타임 `authoring_policy`가 `configured`·`effective`·`workflow_mode`를 별도로 제공합니다. `auto`는 Fast → `minimal`, Standard → `normal`, Strict → `precise`이며 활성 RUN이 없으면 `normal`입니다. 직접 지정한 수준은 고정되고 설치·업데이트도 기존 선택을 보존합니다. 정책 갱신·검증은 [작성 상세도](authoring-detail.ko.md)를 참고하세요.

`get`은 없는 파일을 생성하지 않습니다. `KEY`를 생략하면 전체 유효 설정을, section이나 점으로 구분한 키를 지정하면 해당 값을 읽습니다. 문자열은 그대로, 그 외 값은 JSON으로 출력합니다. `--json`은 선택 경로, 파일 존재 여부, 키와 값을 포함합니다. `--agent`는 빈 값과 미설정 catalog의 `null`도 `<value format="json">`에 JSON으로 유지합니다. 알 수 없는 키나 잘못된 설정 파일은 0이 아닌 종료 코드로 실패합니다.

`set KEY VALUE`는 TOML 값을 받으며 enum 문자열은 따옴표 없이 쓸 수 있습니다. 배열과 TOML 문자열은 shell 따옴표로 감싸세요. `unset KEY`는 저장된 값을 제거해 기본값을 적용합니다. 두 명령 모두 최종 설정 전체를 검증하고 주석과 무관한 설정을 보존합니다. 로컬·사용자 파일이 모두 없으면 로컬 경로를 만듭니다. 로컬 파일 없이 사용자 파일만 있으면 편집도 사용자 파일에 적용되므로, 목적지를 명시하려면 `--config`를 사용하세요.

```sh
taplctl config set subagents.preference '"Prefer independent bounded tasks."'
taplctl config set viewer.allowed_origins '["https://viewer.example.invalid"]'
```

예제 origin은 자리표시자이며 실제 신뢰하는 브라우저 origin으로 바꿉니다. scheme, host, 선택적 port만 허용하고 자격 증명·경로·query·fragment는 넣지 않습니다. Viewer는 계속 loopback에서 수신합니다. 프록시는 [Viewer와 서비스](viewer.ko.md)를 참고하세요.

## Viewer 설정

브라우저 Viewer나 VS Code 확장에서 **관리 → 설정**을 엽니다. CLI의 편집 레지스트리에 있는 모든 키를 다루며, Codex와 Claude Code의 모델 허용 목록 및 순서가 있는 프로필·후보를 구분합니다. 모델 ID, 추론 강도 목록, 프로필과 Origin은 구조화된 입력으로 편집합니다. 표시 언어·레이아웃·확장 MCP 실행 파일은 같은 파일의 `viewer.language`, `viewer.layout`, `viewer.mcp_path`로 관리합니다. 저장하면 적용하며 `auto`는 호스트 언어와 화면 폭을 따릅니다.

표시된 파일 경로를 확인하세요. 현재 작업공간에서 위 우선순위를 따르며, 명시적 `--config PATH`로 시작한 브라우저 Viewer는 그 파일에 고정됩니다. 과거 RUN이나 다른 원본 DB를 선택해도 설정 대상은 바뀌지 않습니다. **변경 사항 저장**은 전체 후보를 검증하고 변경된 값을 한 번에 원자적으로 기록하며 주석과 무관한 설정을 유지합니다. 외부에서 설정이 바뀌면 문서 revision이 무효화되므로 다시 불러온 뒤 저장하세요. 저장에 실패해도 입력은 유지되며 작업공간을 바꾸거나 Viewer를 새로 열기 전까지 설정 페이지로 돌아와 편집을 이어갈 수 있습니다.

**모두 기본값으로 초기화**는 확인 후 두 클라이언트의 모든 편집 가능 재정의와 기존 별칭을 이 파일에서 제거합니다. 내장 기본값을 적용하며 주석·무관한 키·저장된 모델 카탈로그는 유지합니다. 개별 항목의 **기본값 사용**은 입력값을 바꾸므로 저장해야 반영됩니다. 초기화하면 표시 언어와 레이아웃도 `auto`로 돌아갑니다. Origin 변경은 브라우저 Viewer 서비스를 재시작해야 적용됩니다. 설정을 지원하지 않는 백엔드는 업데이트 안내를 표시합니다. TAPL을 업데이트하고 MCP/Viewer 프로세스를 다시 시작하세요. 위 CLI 명령도 계속 사용할 수 있습니다.

확장은 MCP 시작 전에 이 초기 연결 필드를 직접 읽습니다. 설정 페이지 조회·저장은 MCP로, 브라우저는 HTTP로 같은 Python 검증 서비스에 요청합니다. 작업공간·사용자 설정 파일 변경은 Viewer를 갱신하며 MCP 실행 파일 변경은 진행 중 저장 응답을 받은 뒤 재연결합니다. 이전 VS Code 설정 `taplWorkflow.language`, `taplWorkflow.layout`, `taplWorkflow.taplMcpPath`는 무시합니다. 새 TOML 키를 직접 지정하며 사용자 파일에 자동 이관하지 않습니다.

## 공개 설정 키

아래 표의 canonical key를 `config set`·`config unset`에서 지원합니다. 런타임 기본값은 설치나 최초 설정에서 선택한 값과 다를 수 있습니다. 표는 Codex의 `subagents.*` 키를 사용하며 Claude Code의 같은 위임 설정에는 `clients.claude-code.subagents.*`를 사용합니다.

| 키 | 형식 / 허용값 | 내장 기본값 |
| --- | --- | --- |
| `workflow.authoring_detail` | `auto`, `precise`, `normal`, `minimal` | `auto` |
| `recall.enabled` | Boolean | `true` |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` | `hybrid` |
| `search.max_results` | 1 이상 정수 | `12` |
| `search.hybrid_semantic_ratio` | 0.0–1.0 숫자 | `0.65` |
| `search.semantic_provider` | `local`, `daemon`, `auto` | `auto` |
| `search.searchd_model_idle_timeout_seconds` | 0 이상 정수; `0`이면 유휴 모델 해제 안 함 | `1800` |
| `viewer.language` | `auto`, `ko`, `en` | `auto`: 호스트 언어 사용 |
| `viewer.layout` | `auto`, `small`, `medium`, `large` | `auto`: 화면 폭에 맞춤 |
| `viewer.mcp_path` | 실행 파일 경로나 명령 이름 하나; shell 인자 미지원 | `""`: 확장에서 자동 검색 |
| `viewer.allowed_origins` | 중복 없는 HTTP(S) origin의 TOML 문자열 배열 | `[]` |
| `subagents.enabled` | Boolean; 실제 위임에는 설정 완료도 필요 | `true` |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` | `aggressive` |
| `subagents.setup_complete` | Boolean | 새 설정은 `false`; 생략했을 때 비어 있지 않은 모델 허용 목록이 있거나 위임이 꺼져 있으면 `true` 추론 |
| `subagents.preference` | TOML 문자열; [최초 설정·선호 변경](subagents.ko.md#최초-설정) 시 에이전트가 영어로 요약 | `""` |
| `subagents.models.<model-id>` | 중복 없는 reasoning effort 문자열 배열; Codex는 비어 있지 않아야 하며 Claude Code는 `[]`도 허용 | 사전 지정 모델 조합 없음 |
| `subagents.profiles` | 순서 있는 TOML inline table 배열; `[]`로 profile 비활성화 | candidate가 빈 모델 중립 profile 4개 |

읽기 전용·유효값에는 `search.hybrid_bm25_ratio`(`1 - hybrid_semantic_ratio`, 기본 `0.35`)와 `subagents.available_models`(저장된 runtime catalog, 없으면 `null`)도 있습니다. 이들은 `config set`·`unset`으로 편집할 수 없습니다. Catalog 설정·갱신은 에이전트의 `tapl_configure_subagents` 절차를 사용합니다. 구조화된 출력의 `path`와 `exists`는 선택된 출처이며 편집 가능한 런타임 설정이 아닙니다.

Profile table은 `name`, 선택적 `description`, `characteristics`, `delegation_bias`(`inherit`, `prefer`, `neutral`, `avoid`), 순서 있는 `candidates`를 사용합니다. Candidate에는 `model`, `reasoning_effort`를 사용합니다. Claude Code에서 `reasoning_effort` 생략이나 빈 문자열은 effort 미지정이며 빈 effort 배열인 허용 목록 항목과 일치해야 합니다. Codex는 비어 있지 않은 effort가 필요합니다. 이름은 고유해야 하고 candidate는 모델 허용 목록에 있어야 합니다. 사용자 profile은 내장값을 대체합니다. 설정·선택 규칙은 [SubAgent](subagents.ko.md)를 참고하세요.

## 검증과 적용

```sh
taplctl config set --help
taplctl config get --json
taplctl doctor
```

변경 전 출력된 출처 경로를 확인하세요. 선택 파일이 잘못되었으면 다른 파일로 넘어가지 않고 실패합니다. 값을 제거한 뒤에도 전체 설정이 유효해야 합니다. 예를 들어 완료된 활성 위임 설정에는 허용된 모델 조합이 필요합니다. `config get`은 기본값과 추론값도 보여 주므로 키를 지워도 유효값이 사라지는 것은 아닙니다.

다음 전체 MCP 정책 조회에서 변경된 설정과 새 `policy_revision`을 전달합니다. MCP/hook 연결 변경 뒤에는 해당 호스트를, origin 설정 변경 뒤에는 Viewer 서비스를 다시 시작합니다. 설치 시 config 병합·덮어쓰기 정책은 런타임 파일 선택과 별개입니다. [설치](../getting-started/installation.ko.md)를 참고하세요.

## 관련 페이지

[작성 상세도](authoring-detail.ko.md) · [SubAgent](subagents.ko.md) · [기억](memory.ko.md) · [검색](search.ko.md) · [CLI 참조](../reference/cli.ko.md)
