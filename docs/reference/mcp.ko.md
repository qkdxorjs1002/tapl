# MCP 도구 참조

[문서 홈](../README.ko.md) · [English](mcp.md)

`tapl-mcp`는 MCP stdio로 워크플로 애플리케이션을 제공합니다. 관리 명령은 [CLI](cli.ko.md)를 사용합니다. 이 페이지는 [`mcp_server.py`](../../tapl/taplctl/mcp_server.py)에 등록된 **공개 도구 30개 전체**를 다룹니다. 정확한 입력 검증은 연결된 서버의 JSON schema가 기준입니다.

## 공통 계약

읽기를 포함해 **모든 호출에 현재 Codex hook `session_id`**를 전달합니다. 대부분의 schema에서는 호환성을 위해 선택 인자이지만 생략하면 다른 세션의 활성 RUN이 아닌 격리된 legacy 범위(`""`)를 선택합니다. 식별자는 최대 256자이며 앞뒤 공백과 제어 문자를 허용하지 않습니다. `tapl_discard_run`은 legacy RUN의 `""`까지 포함해 소유자를 명시해야 합니다.

응답은 구조화된 객체입니다. 코드 모드에서는 필요한 도구를 정확한 이름으로 함께 탐색하고 전체 도구 목록은 출력하지 않습니다. `structuredContent`를 한 번 출력하고 필요할 때만 텍스트를 파싱해 대체합니다. envelope의 두 표현을 모두 출력하지 않습니다. 쓰기 응답은 현재 권고와 축약 검증을 제공합니다. 차단 오류는 모두 남기며 생략한 경고 수는 `omitted_issue_count`로 알립니다.

PLAN ID는 `PLAN-001` 또는 legacy `SPEC-001`, TASK ID는 `TASK-001` 형태로 세 자리 이상의 숫자를 사용합니다. 작업의 `spec_id`는 해당 주제의 기존 계획을 가리킵니다. 구조화된 계획·작업 필드를 전달하면 애플리케이션이 병합하고 Markdown으로 렌더링합니다. 생략한 계획 필드는 유지합니다.

`custom_fields`는 검색 가능한 영속 메타데이터용 JSON 객체입니다. 키와 값 타입을 보존합니다. 기존 키는 병합하며 최상위 값 `null`은 해당 키를 삭제합니다. 기본 `precise`에서는 모든 실행 작업에 아래 표준 객체를 사용합니다. `normal`·`minimal`의 일반 root 작업은 형식적인 판단 메타데이터를 생략할 수 있지만, 모델 선택·프로필 예외의 선택 근거와 표준 필드에 없는 지속적 사실은 기록합니다.

```json
{
  "Task Profile": {"name": "none", "match_reason": "적용할 권고 프로필이 없습니다."},
  "Task Characteristics": {
    "independence": "문서 파일 하나를 소유합니다.",
    "context": "현재 CLI 도움말입니다.",
    "risk": "되돌릴 수 있는 낮은 위험의 텍스트 변경입니다.",
    "coordination_cost": "작습니다.",
    "parallel_value": "동시 편집의 이점이 없습니다."
  },
  "Execution Decision": {
    "executor": "main",
    "delegation_reason": "범위가 작은 편집은 주 에이전트가 수행합니다.",
    "override": false
  }
}
```

모델을 선택하면 `Execution Decision`에 `model`, `reasoning_effort`, `model_reason`을 추가합니다. Dispatch는 manifest를 반환하기 전에 legacy `SubAgent Model`을 기록합니다. 메타데이터도 기록이므로 읽을 수 있는 문장으로 작성합니다. [기록](../concepts/records.ko.md)과 [SubAgent](../guides/subagents.ko.md)를 참고하세요.

## 진입·조회·설정

공통 `session_id`는 필수인 경우 외에는 표에서 생략합니다.

| 도구 | 필수 인자 | 선택 인자와 동작 |
| --- | --- | --- |
| `tapl_get_next` | 없음 | `known_policy_revision`; 명시적 설정 확인용 `available_models`, `catalog_complete=false`. 정책·설정·상태 요약·다음 행동을 반환합니다. |
| `tapl_get_status` | 없음 | `full=false`, `include_events=false`, `events_limit=12` (0–100). 조회·재개·복구용 상세이며 `full=true`는 기록 본문도 포함합니다. |
| `tapl_validate_state` | 없음 | 계획 상세, 작업 계약, 의존성, 실행 순서, 승인을 검증합니다. |
| `tapl_get_context` | 없음 | `event="Manual"`로 수명주기 지침을 선택합니다. |
| `tapl_configure_subagents` | `user_confirmed`, `enabled`, `strategy`, `models`, `available_models` | `preference=""`, `profiles`. 확인받은 설정을 적용 설정 경로에 저장합니다. `strategy`: `conservative`, `balanced`, `aggressive`. |

MCP 초기화는 짧은 진입 안내를 제공합니다. 단순하지 않거나 불확실한 작업을 시작하기 전에 `tapl_get_next`를 **한 번** 호출해 전체 `workflow_policy`, `subagent_guidance`, `config`를 유지합니다. SessionStart bootstrap과 hook 진입은 같은 호출을 공유합니다. 일반 진입에서는 모델 목록 인자를 생략합니다. `state_summary`에는 RUN 식별·분류, 결과 기록 여부, 작업·대기·배치 수, 실행 승인이 들어 있습니다. 부족한 상세나 조회 권고가 있을 때만 `tapl_get_status`를 사용합니다.

`policy_revision`은 정책·위임 지침·설정의 정확한 내용을 나타냅니다. 세 내용 전체가 현재 문맥에 남아 있을 때만 `known_policy_revision`을 전달합니다. 일치하면 바뀌지 않은 정책 필드를 생략하지만 상태·권고와 요청된 완전한 모델 목록 비교는 새로 반환합니다. 모르는 revision이나 내용 변경 시 전체 정책을 반환합니다. 새 세션, 문맥 압축 후, 내용 보존이 불확실할 때는 생략합니다. 상태 캐시나 승인 근거가 아닙니다.

사용자가 요청한 설정 비교에서는 고정 역할 모델까지 포함한 **현재 위임 도구의 전체 모델 목록**과 `catalog_complete=true`를 전달합니다. 검증된 빈 목록은 제거를 확인할 수 있습니다. 기본값 `false`에서는 전달된 목록을 불완전하게 취급하고(`comparison_status="incomplete"`) 변경을 추론하거나 재설정을 요청하지 않습니다. 부족한 live 항목을 저장 설정으로 채우지 마세요. 설정 확인은 실제 사용자 답변이나 정확한 변경 요청이어야 하며 시간 초과는 확인이 아닙니다. 모델은 provider API 목록이 아닌 현재 위임 도구가 노출한 값이어야 합니다. 빈 `models`는 비활성일 때만 허용하며 `profiles=[]`는 권고 프로필을 끕니다.

상태 검증은 트랜잭션상 일관된 스냅샷 하나를 사용합니다. 성공한 쓰기 응답의 권고를 바로 따르세요. 쓰기·읽기 전용 상태 조회·Stop hook 때문에 진입 호출을 반복할 필요는 없습니다. 실패·잘린 응답, 정책·문맥 유실, 다른 주체에 의한 워크플로 변경 가능성이 있으면 새로 읽습니다.

## 이력과 메모리

| 도구 | 필수 인자 | 선택 인자와 동작 |
| --- | --- | --- |
| `tapl_search_history` | `query` (1–500자) | `limit` (1–50, 생략 시 설정 기본값). 활성·아카이브 원본을 검색합니다. |
| `tapl_get_item` | `item_id` (양의 정수) | `compact=false`. 계획·작업·발견 사항을 읽습니다. 축약 모드는 표준 필드로 정확히 복원할 수 있는 생성 본문만 생략하며 사용자 지정·raw 본문과 발견 사항은 보존합니다. |
| `tapl_list_archives` | 없음 | `limit` (1–100). 최근 아카이브 목록. |
| `tapl_get_archive` | `archive_id` | 문자열 형태의 숫자 ID 또는 안정된 slug. 항목·이벤트를 반환합니다. |
| `tapl_recall` | 없음 | `query=""` (최대 500자), `limit=3` (1–50), `offset=0` (0 이상). 빈 쿼리는 목록 조회이며 캡처·강화하지 않습니다. |
| `tapl_get_memory` | `memory_id` | 메모리와 원본을 반환하며 없거나 삭제된 메모리는 null입니다. |
| `tapl_update_memory` | `memory_id`, `expected_revision` (양의 정수) | `note` (1–240자), `cue` (3–5개), `state` (`active` 또는 `superseded`). 명시적 사용자 요청이 필요합니다. |
| `tapl_delete_memory` | `memory_id`, `expected_revision` (양의 정수) | 명시적 사용자 요청이 필요하며 tombstone 처리해 회상·강화에서 제외합니다. |

회상한 단서를 사용하기 전에 `tapl_get_item` 또는 `tapl_get_archive`로 원본 근거를 확인합니다. 메모리 revision 충돌은 새 내용을 검토한 뒤 재시도해야 합니다. `recall.enabled=false`는 자동 회상·캡처·검토·강화를 끄지만 수동 조회는 유지합니다. 순위와 관리 절차는 [연상 메모리](../guides/memory.ko.md)를 보세요.

## RUN·계획·발견 사항·승인

| 도구 | 필수 인자 | 선택 인자와 동작 |
| --- | --- | --- |
| `tapl_summarize_run` | `summary` (1–2000자), `work_type`, `workflow_mode` | `recall_query` (최대 500자). RUN당 자동 회상 한 번. |
| `tapl_split_run` | `requests` (객체 2–20개) | 객체마다 `key`, `summary`, `work_type`, `workflow_mode`, 선택 `depends_on=[]`가 있으며 앞선 키만 참조합니다. 계획 전 명시적으로 분리한 RUN 수명주기에 사용합니다. |
| `tapl_apply_plan` | schema상 없음 | `plan_id="PLAN-001"`, `title`, `summary`, `objective`, `requirements_trace`, `selected_approach`, `affected_files`, `execution_order`, `risks`, `validation`, `approval_needs`, `notes`, `custom_fields`, `status`. 워크플로 검증에는 충분한 계획이 필요합니다. |
| `tapl_add_finding` | `title` | `source=""`, `finding=""`, `impact=""`, `related_ids=""`. 판단에 필요한 근거와 출처를 기록합니다. |
| `tapl_approve_execution` | `prompt` | `source="explicit_user"` 또는 `"request_user_input"`. 실제 받은 실행 승인만 기록합니다. |
| `tapl_reject_execution` | `prompt` | 같은 `source` 값. 명시적 거절을 보존합니다. |
| `tapl_finish_run` | `result` | `expected_run_id`, `memory_candidates`, `memory_uses`, `memory_review`. 아래 완료 절차 참고. |
| `tapl_finish_archive` | `slug` (1–120자) | `summary=""` (최대 2000자). 작업·배치 정리와 완료 검토 후 호출합니다. |
| `tapl_discard_run` | `run_id`, `confirmed`, `confirmation_run_id`, `session_id` | 모두 필수이며 아래 확인된 폐기 참고. |

`work_type`: `answer`, `investigation`, `analysis`, `planning`, `implementation`, `mixed`. `workflow_mode`: `fast`, `standard`, `strict`. TAPL이 `record_mode`를 계산합니다. Fast의 비영속 답변·조사·분석·계획만 lightweight가 될 수 있으며 영속 작업과 Standard/Strict 작업은 계획·작업을 사용합니다. 다른 주제는 보통 RUN을 나누지 않고 하나의 RUN 안에서 별도 PLAN을 만듭니다.

`tapl_split_run`의 키는 1–100자이며 영문·숫자로 시작하고 이후 영문·숫자·`.`·`_`·`-`를 허용합니다. 뒤의 키를 의존 대상으로 지정할 수 없습니다. 하나의 결과에 대한 요구 사항은 같은 주제 계획에 유지합니다.

## 작업과 병렬 배치

| 도구 | 필수 인자 | 선택 인자와 동작 |
| --- | --- | --- |
| `tapl_create_task` | `task_id`, `title`, `spec_id`, `goal`, `action`, `verification` | `execution_mode="sequential"`, `executor_kind="main"`, `parallel_group`, `owned_paths`, `depends_on`, `custom_fields`. Pending 작업 생성. |
| `tapl_start_task` | `task_id` | `custom_fields`. 의존성이 준비된 순차 작업 시작. |
| `tapl_dispatch_tasks` | `task_ids` (최소 2개) | `batch_id`, `failure_policy="continue"`, `execution_metadata`. 원자적 병렬 dispatch 후 실행 manifest 반환. |
| `tapl_complete_task` | `task_id`, `verification`, `result` | `execution_id`, `custom_fields`. 구현과 검증 후 완료. |
| `tapl_block_task` | `task_id`, `blocker`, `next_action` | `execution_id`, `verification`, `custom_fields`. 구체적 차단 사유와 다음 행동 보존. |
| `tapl_skip_task` | `task_id`, `result` | `execution_id`, `custom_fields`. 의도적 제외 사유 기록. |
| `tapl_cancel_batch` | `batch_id`, `reason` | `block_tasks=true`; false이면 Pending으로 반환. 활성 실행 취소. |
| `tapl_recover_batch` | `batch_id`, `reason` | 중단된 활성 작업을 안전한 재시도를 위해 Pending으로 반환. |

병렬 작업은 `execution_mode="parallel"`, `executor_kind="subagent"`, 같은 계획과 비어 있지 않은 `parallel_group`, 완료된 의존 작업, 겹치지 않는 독점 `owned_paths`, 실행 승인이 필요합니다. Root가 원자적으로 dispatch하고 기록된 `SubAgent Model`을 확인한 뒤 실제 에이전트를 생성합니다. `execution_metadata`는 작업 ID별 런타임 선택 객체이며 모델을 선택하면 완전한 `model`/`reasoning_effort` 쌍과 근거를 포함합니다. TAPL 상태 쓰기는 root만 담당하며 각 작업은 manifest의 정확한 **`execution_id`**로 정리합니다. 중단·생성 실패 시 기존 배치를 복구하거나 취소한 뒤 재시도합니다. 안정된 `batch_id`는 같은 RUN·작업 집합의 멱등 재시도에 사용하며 다른 배치를 재사용하는 수단이 아닙니다.

## 순차 수명주기 예제

다음은 기본 `precise` 작성에 따른 순서대로 호출할 MCP 개요이며 무조건 실행하는 셸 명령이나 스크립트가 아닙니다. `call(name, arguments)`는 호스트의 MCP 호출을 뜻합니다. `sid`는 실제 hook 식별자로 바꿉니다. 정책·관련 이력을 확인하고 계획을 확정하기 전에 사용자 확인을 받으세요. 실제 실행 승인이 있을 때만 승인을 기록하고 완료 필드에는 구체적 검증 근거를 넣습니다.

```javascript
const sid = "<hook session_id>";
const call = (name, args) => host.callTool(name, { ...args, session_id: sid });
await call("tapl_get_next", {});
const run = await call("tapl_summarize_run", {
  summary: "오래된 CLI 예제를 수정하고 문서를 검증합니다.",
  work_type: "implementation", workflow_mode: "standard"
});
await call("tapl_search_history", { query: "CLI documentation example" });
// 사용자가 계획을 확인한 뒤:
await call("tapl_apply_plan", {
  plan_id: "PLAN-001", title: "CLI 문서 수정", status: "Finalized",
  summary: "현재 명령 도움말에 예제를 맞춥니다.",
  objective: "독자가 문서의 명령을 실행할 수 있게 합니다.",
  requirements_trace: "REQ-001: 현재 명령과 양언어 예제 일치.",
  selected_approach: "해당 주제의 영문·국문 예제를 수정합니다.",
  affected_files: "docs/reference/cli.md; docs/reference/cli.ko.md",
  execution_order: "TASK-001 편집 후 TASK-002 검증.",
  risks: "복사한 예제가 오래될 수 있습니다.",
  validation: "명령 도움말, 번역, 링크, git diff --check를 확인합니다.",
  approval_needs: "저장소 편집 전 명시적 사용자 승인이 필요합니다."
});
// 기본 precise 작성에서는 실행 작업마다 앞의 표준 custom_fields를 포함합니다.
await call("tapl_create_task", {
  task_id: "TASK-001", title: "예제 갱신", spec_id: "PLAN-001",
  goal: "현재 CLI 인자를 사용합니다.", action: "양언어 예제를 편집합니다.",
  verification: "두 예제를 명령 도움말과 비교합니다.", custom_fields: metadata
});
await call("tapl_create_task", {
  task_id: "TASK-002", title: "문서 검증", spec_id: "PLAN-001",
  goal: "공개 안내의 일관성을 확인합니다.", action: "링크와 양언어 대응을 확인합니다.",
  verification: "링크 검사와 git diff --check를 실행합니다.",
  depends_on: ["TASK-001"], custom_fields: metadata
});
// 실제 실행 지시나 확인을 받은 뒤에만:
await call("tapl_approve_execution", {
  source: "explicit_user", prompt: "CLI 예제를 수정하고 검증해 주세요."
});
await call("tapl_start_task", { task_id: "TASK-001" });
// 승인된 편집과 검증을 수행한 뒤 완료:
await call("tapl_complete_task", {
  task_id: "TASK-001", verification: "양언어 예제가 현재 CLI 도움말과 일치합니다.",
  result: "영문·국문 명령 예제를 갱신했습니다."
});
await call("tapl_start_task", { task_id: "TASK-002" });
// 선언한 검사를 수행한 뒤 완료:
await call("tapl_complete_task", {
  task_id: "TASK-002", verification: "링크·양언어 대응 확인 및 diff 검사 통과.",
  result: "문서 검증을 통과했습니다."
});
await call("tapl_finish_run", {
  result: "예제를 수정하고 검증했습니다.", expected_run_id: run.active_run.id,
  memory_review: { decision: "skip", reason: "원본 문서 외에 반복적으로 재사용할 교훈이 없습니다." }
});
// 반환된 메모리 검토를 확인하고 남은 실패를 먼저 해결합니다.
await call("tapl_finish_archive", {
  slug: "2026-10-30-cli-example", summary: "CLI 예제를 현재 동작에 맞추고 검증했습니다."
});
```

`metadata`는 앞의 표준 객체, `host`는 도구의 구조화된 결과를 파싱해 반환하는 MCP 클라이언트 어댑터를 뜻합니다. 설명용 이름이며 TAPL이 export하는 API가 아닙니다. 쓰기 후에는 정기적인 상태·진입 폴링 없이 응답 권고를 사용합니다. 검증 상세가 필요하면 `tapl_validate_state`를 호출합니다. 계획 전용 작업은 사용자가 종료·아카이브를 명시적으로 선택할 때까지 활성 상태로 둡니다.

## 완료와 메모리 인자

`tapl_finish_run`은 검증한 결과를 저장하며 아카이브는 별도 호출입니다. 실행할 작업과 활성 배치를 모두 정리해야 합니다. 메모리 인자를 하나라도 사용하면 `expected_run_id`가 활성 RUN을 가리켜야 합니다.

- `memory_candidates`: 최대 두 객체. `slot` (1 또는 2), `cue` (서로 다른 3–5개), `note` (1–240자), `source_run_id`, 선택적 양의 `source_item_id`, 선택적 `replaces_memory_id`를 가집니다. 반복 단서가 있고 향후 탐색을 줄이는 검증된 교훈만 캡처합니다. 후보가 있으면 capture로 간주합니다.
- `memory_uses`: 최대 50개. `memory_id`, 양의 `revision`, Boolean `source_checked`, `usage` (1–500자)를 가집니다. 원본을 확인한 뒤 실제 사용한 경우만 넣습니다.
- `memory_review`: `{ "decision": "capture" | "skip", "reason": "..." }`. skip에는 1–240자의 사유가 필요합니다. 후보와 검토를 모두 생략하면 검토 대상 RUN은 `review_required`로 남습니다.

캡처가 실패해도 작업 결과는 보존합니다. 응답을 확인해 실패한 slot만 입력을 고쳐 한 번 재시도하고, 해결하지 못한 실패는 사유와 함께 명시적으로 skip한 뒤 아카이브합니다. [연상 메모리](../guides/memory.ko.md)를 참고하세요.

<a id="confirmed-discard"></a>

## 확인된 폐기

`tapl_discard_run`은 literal `confirmed=true`, 선택한 전체 `run_id`와 대소문자·공백까지 일치하는 `confirmation_run_id`, 명시적 소유 세션이 필요합니다. 선택한 RUN과 같은 소유자·split group의 모든 대기 RUN을 의존성 연결 여부와 무관하게 함께 처리합니다. 각 RUN은 정말 비어 있으면 삭제하고 보존할 기록이 있으면 강제 아카이브합니다. 활성 DB 실행·배치를 취소하며 다른 RUN을 시작하지 않습니다. 외부 에이전트 프로세스를 종료하지 않습니다. 일반 완료·아카이브와 구분되는 명시적 Viewer 닫기 동작입니다. [Viewer](../guides/viewer.ko.md#run-폐기)를 보세요.

## 가용성과 검증

현재 서버는 위 도구를 모두 등록합니다. 선택적 의미 검색 의존성은 도구 등록이 아닌 검색 실행에 영향을 줍니다. `searchd`는 Unix 전용입니다. 자동 회상을 꺼도 수동 메모리 조회는 유지합니다. 메모리 변경에는 여전히 명시적 사용자 요청과 현재 revision이 필요합니다. Viewer는 `associativeMemory`, `discardRun` 기능 표시에 따라 구버전 서버에서 지원하는 화면을 유지합니다.

Schema·세션·수명주기는 `tapl/tests`의 `test_mcp_native.py`, `test_session_mcp.py`, `test_application.py`, `test_context_optimization.py`, 메모리·폐기 테스트에서 검증합니다. [아키텍처](../development/architecture.ko.md), [기여와 검증](../development/contributing.ko.md), [워크플로](../concepts/workflow.ko.md)를 참고하세요.
