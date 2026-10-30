# 설정

[문서 홈](../README.ko.md) · [English](configuration.md)

현재 작업 폴더에 적용되는 설정 파일을 선택하고 유효값을 확인하며, 다른 TOML 내용을 유지한 채 지원 설정을 변경하는 방법을 안내합니다.

## 작업 공간과 파일 선택

Codex 세션은 정확한 작업 폴더의 `.tapl/tapl.db`를 사용합니다. Hook은 존재하는 절대 경로 `cwd`가 필요하며 누락되거나 잘못된 값은 거부합니다. Hook의 `--db`도 그 폴더의 DB를 가리켜야 합니다. MCP 서버는 시작 폴더에 수명 전체 동안 고정됩니다. 부모 DB, Git root, 저장소 표식을 탐색하지 않습니다. `repo/packages/app`에서 시작하면 `repo/.tapl/tapl.db`가 있어도 `repo/packages/app/.tapl/tapl.db`를 사용합니다. 폴더별 이력은 독립적이며 기존 DB를 이동하거나 병합하지 않습니다. 관리 CLI는 명시적인 `--db`, `--workspace-root`를 지원합니다.

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

`get`은 없는 파일을 생성하지 않습니다. `KEY`를 생략하면 전체 유효 설정을, section이나 점으로 구분한 키를 지정하면 해당 값을 읽습니다. 문자열은 그대로, 그 외 값은 JSON으로 출력합니다. `--json`은 선택 경로, 파일 존재 여부, 키와 값을 포함합니다. `--agent`는 빈 값과 미설정 catalog의 `null`도 `<value format="json">`에 JSON으로 유지합니다. 알 수 없는 키나 잘못된 설정 파일은 0이 아닌 종료 코드로 실패합니다.

`set KEY VALUE`는 TOML 값을 받으며 enum 문자열은 따옴표 없이 쓸 수 있습니다. 배열과 TOML 문자열은 shell 따옴표로 감싸세요. `unset KEY`는 저장된 값을 제거해 기본값을 적용합니다. 두 명령 모두 최종 설정 전체를 검증하고 주석과 무관한 설정을 보존합니다. 로컬·사용자 파일이 모두 없으면 로컬 경로를 만듭니다. 로컬 파일 없이 사용자 파일만 있으면 편집도 사용자 파일에 적용되므로, 목적지를 명시하려면 `--config`를 사용하세요.

```sh
taplctl config set subagents.preference '"Prefer independent bounded tasks."'
taplctl config set viewer.allowed_origins '["https://viewer.example.invalid"]'
```

예제 origin은 자리표시자이며 실제 신뢰하는 브라우저 origin으로 바꿉니다. scheme, host, 선택적 port만 허용하고 자격 증명·경로·query·fragment는 넣지 않습니다. Viewer는 계속 loopback에서 수신합니다. 프록시는 [Viewer와 서비스](viewer.ko.md)를 참고하세요.

## 공개 설정 키

아래 표의 canonical key를 `config set`·`config unset`에서 지원합니다. 런타임 기본값은 설치나 최초 설정에서 선택한 값과 다를 수 있습니다.

| 키 | 형식 / 허용값 | 내장 기본값 |
| --- | --- | --- |
| `workflow.authoring_detail` | `precise`, `normal`, `minimal` | `precise` |
| `recall.enabled` | Boolean | `true` |
| `search.mode` | `semantic`, `bm25`, `word`, `hybrid` | `hybrid` |
| `search.max_results` | 1 이상 정수 | `12` |
| `search.hybrid_semantic_ratio` | 0.0–1.0 숫자 | `0.65` |
| `search.semantic_provider` | `local`, `daemon`, `auto` | `auto` |
| `search.searchd_model_idle_timeout_seconds` | 0 이상 정수; `0`이면 유휴 모델 해제 안 함 | `1800` |
| `viewer.allowed_origins` | 중복 없는 HTTP(S) origin의 TOML 문자열 배열 | `[]` |
| `subagents.enabled` | Boolean; 실제 위임에는 설정 완료도 필요 | `true` |
| `subagents.strategy` | `conservative`, `balanced`, `aggressive` | `aggressive` |
| `subagents.setup_complete` | Boolean | 새 설정은 `false`; 생략했을 때 비어 있지 않은 모델 허용 목록이 있거나 위임이 꺼져 있으면 `true` 추론 |
| `subagents.preference` | TOML 문자열 | `""` |
| `subagents.models.<model-id>` | reasoning effort 문자열의 비어 있지 않은 고유 배열 | 사전 지정 모델 조합 없음 |
| `subagents.profiles` | 순서 있는 TOML inline table 배열; `[]`로 profile 비활성화 | candidate가 빈 모델 중립 profile 4개 |

읽기 전용·유효값에는 `search.hybrid_bm25_ratio`(`1 - hybrid_semantic_ratio`, 기본 `0.35`)와 `subagents.available_models`(저장된 runtime catalog, 없으면 `null`)도 있습니다. 이들은 `config set`·`unset`으로 편집할 수 없습니다. Catalog 설정·갱신은 에이전트의 `tapl_configure_subagents` 절차를 사용합니다. 구조화된 출력의 `path`와 `exists`는 선택된 출처이며 편집 가능한 런타임 설정이 아닙니다.

Profile table은 `name`, 선택적 `description`, `characteristics`, `delegation_bias`(`inherit`, `prefer`, `neutral`, `avoid`), 순서 있는 `candidates`를 사용합니다. Candidate에는 `model`, `reasoning_effort`가 필요합니다. 이름은 고유해야 하고 candidate는 모델 허용 목록에 있어야 합니다. 사용자 profile은 내장값을 대체합니다. 설정·선택 규칙은 [SubAgent](subagents.ko.md)를 참고하세요.

## 검증과 적용

```sh
taplctl config set --help
taplctl config get --json
taplctl doctor
```

변경 전 출력된 출처 경로를 확인하세요. 선택 파일이 잘못되었으면 다른 파일로 넘어가지 않고 실패합니다. 값을 제거한 뒤에도 전체 설정이 유효해야 합니다. 예를 들어 완료된 활성 위임 설정에는 허용된 모델 조합이 필요합니다. `config get`은 기본값과 추론값도 보여 주므로 키를 지워도 유효값이 사라지는 것은 아닙니다.

다음 전체 MCP 정책 조회에서 변경된 설정과 새 `policy_revision`을 전달합니다. MCP/hook 연결 변경 뒤에는 Codex를, origin 설정 변경 뒤에는 Viewer 서비스를 다시 시작합니다. 설치 시 config 병합·덮어쓰기 정책은 런타임 파일 선택과 별개입니다. [설치](../getting-started/installation.ko.md)를 참고하세요.

## 관련 페이지

[작성 상세도](authoring-detail.ko.md) · [SubAgent](subagents.ko.md) · [기억](memory.ko.md) · [검색](search.ko.md) · [CLI 참조](../reference/cli.ko.md)
