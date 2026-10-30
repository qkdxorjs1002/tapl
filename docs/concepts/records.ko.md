# 기록 구조와 메타데이터

[문서 홈](../README.ko.md) · [English](records.md)

TAPL 기록은 `.tapl/tapl.db`의 구조화된 데이터이며 typed field로부터 읽기 쉬운 Markdown 본문을 생성합니다. Agent는 MCP로 기록을 작성·갱신하고 CLI는 설치를 관리합니다. 이 페이지는 각 기록과 `custom_fields`에 무엇을 넣는지 설명합니다.

## 표준 필드에 작업 내용 기록

| 기록 | 주요 필드와 목적 |
| --- | --- |
| RUN | 요청 `summary`, `work_type`, `workflow_mode`, 도출된 `record_mode`, 세션 소유자, 최종 `result` |
| PLAN | `plan_id`, `title`, `summary`, `objective`, `requirements_trace`, `selected_approach`, `affected_files`, `execution_order`, `risks`, `validation`, `approval_needs`, `notes`, `status` |
| TASK | `task_id`, `title`, `spec_id`, `goal`, `action`, `verification`. 완료 시 `result`, 차단 시 `blocker`·`next_action` |
| TASK 실행 | `execution_mode`, `executor_kind`, `parallel_group`, `owned_paths`, `depends_on` |
| FINDING | `title`, `source`, `finding`, `impact`, `related_ids` |
| APPROVAL | 실행 결정, 승인 범위와 출처. 명시적 승인은 `explicit_user` 또는 `request_user_input` |
| ARCHIVE | 안정된 slug, 요약과 나중에 확인할 RUN 기록 |

계획은 `PLAN-001` 같은 숫자형 고정 ID(`SPEC-001`도 허용), Task는 `TASK-001` 같은 ID를 사용합니다. ID는 RUN 안에서 유일합니다. Task의 `spec_id`는 그 주제의 계획을 참조하며 자유 형식 문서 경로가 아닙니다.

실행 Task에는 수행 가능한 목표·행동·검증이 필요합니다. 완료 Task에는 결과와 검증 근거, 차단 Task에는 차단 사유와 구체적인 다음 행동이 필요합니다. 병렬 Task에는 batch에 필요한 실행·소유권 필드도 필요합니다. [워크플로](workflow.ko.md)와 [SubAgent](../guides/subagents.ko.md)를 참고하세요.

## Typed field로 작성

계획·Task 내용을 도구의 이름 있는 인자로 전달합니다. TAPL은 기록 병합 시 템플릿으로 저장 Markdown 본문을 만듭니다. 구조화 필드를 직접 꾸민 정책 덤프로 대체하거나 존재하지 않는 CLI 워크플로 명령을 만들지 마세요.

다음은 `PLAN-001`이 존재할 때의 `tapl_create_task` 인자 예시입니다. 세션 자리표시자는 현재 Codex hook의 식별자로 바꿉니다.

```json
{
  "task_id": "TASK-001",
  "title": "설정 경로 처리 수정",
  "spec_id": "PLAN-001",
  "goal": "선택한 설정 파일을 일관되게 해석한다.",
  "action": "명시한 설정 경로를 보존하도록 파서를 수정한다.",
  "verification": "상대·절대 경로에 대한 파서 검사를 실행한다.",
  "session_id": "CURRENT_CODEX_SESSION_ID"
}
```

표준 필드 예제이며 실행 선택 메타데이터는 아래 설명한 작성 상세도에 따라 달라집니다. 생성하면 Pending Task가 됩니다. 시작·정리에는 별도 수명주기 도구를 사용하며 해당하는 실행 승인이 필요합니다. 정확한 필드는 [MCP 참조](../reference/mcp.ko.md)에 있습니다.

여러 줄 값에는 필요한 경우 Markdown 제목·목록·간결한 라벨을 사용하세요. 한국어 띄어쓰기를 포함해 사용자 언어의 자연스러운 문법과 간격을 지킵니다. 식별자·경로·명령·인용문은 그대로 보존합니다. 예를 들어 다음과 같이 작성합니다.

```text
objective: 개발 앱 설정을 준비한 뒤 Task 1개를 실행하고 결과를 확인한다.
action: APP_CONFIG_YML 경로를 확인하고 검증 결과를 기록한다.
```

이는 작성 예시이며 새 요구사항이 아닙니다. TAPL은 띄어쓰기로 입력을 거부하거나 문장을 자동 수정하지 않으며 과거 기록의 문체도 바꾸지 않습니다.

## 추가 사실은 Custom field로 보존

`custom_fields`는 표준 필드에 없는 지속적이고 검색 가능한 메타데이터에 사용합니다. 장기 사용자 제약, 실행 선택 이유, 나중에 작업을 해석하는 데 필요한 도메인 사실 등이 해당합니다. `goal`, `verification`이나 계획 전체를 메타데이터에 중복하지 마세요. 공통 사실은 계획, Task별 사실은 Task에 둡니다.

표준 필드에 없는 지속적인 사용자 요구의 예시는 다음과 같습니다.

```json
{
  "custom_fields": {
    "사용자 참고사항": {
      "종류": "호환성",
      "내용": "PowerShell 5.1에서 명령을 계속 사용할 수 있어야 한다.",
      "영향": "지원 셸을 기준으로 구문과 예제를 확인한다."
    }
  }
}
```

영문 대응 이름은 `User Notes`와 `category`, `content`, `impact`입니다. 실제 지속적 사용자 사실에만 사용하고 추측한 요구사항이나 일시적 진행 상황은 넣지 않습니다. 이 이름은 작성 관례이며 도메인별 다른 키도 사용할 수 있습니다.

값은 모든 JSON 타입을 사용할 수 있습니다. 갱신은 최상위 키 단위로 병합합니다. 생략한 키는 보존하고 지정한 키는 값 전체를 교체하며 최상위 `null`은 그 키를 삭제합니다. 중첩 객체는 재귀적으로 부분 병합하지 않고 값 전체를 교체하므로 갱신할 때 필요한 키·타입을 보존하세요.

```json
{
  "custom_fields": {
    "Obsolete duplicate": null
  }
}
```

메타데이터는 이력 검색 텍스트에 포함됩니다. 설명을 읽기 쉽게 유지하고 검색 결과를 근거로 사용하기 전에 원본 기록을 확인하세요. [검색](../guides/search.ko.md)을 참고하세요.

## 작성 상세도별 선택 메타데이터

기본 `precise`에서는 실행 Task가 설계 시점과 dispatch 직전에 다음 표준 JSON 객체를 유지하며, 정리 과정에서 결정이 바뀌면 갱신합니다.

| 키 | 내용 |
| --- | --- |
| `Task Profile` | 선택한 profile 또는 `none`인 `name`, `match_reason` |
| `Task Characteristics` | `independence`, `context`, `risk`, `coordination_cost`, `parallel_value` |
| `Execution Decision` | `executor`, `delegation_reason`, `override`. 모델 선택 시 `model`, `reasoning_effort`, `model_reason` 추가 |

`normal`·`minimal`의 일반적인 root 작업에는 형식적인 advisory 메타데이터가 필요 없습니다. 모델 선택이나 profile 재정의에는 간결한 표준 `Task Profile`, 관련 `Task Characteristics`, `Execution Decision`과 이유를 유지하고 해당하면 선택한 모델·추론 수준도 기록합니다. 표준 필드 밖의 지속적 사실은 모든 상세도에서 `custom_fields`에 남깁니다. 분량을 줄여도 승인·의존성·소유권·검증 요건은 유지합니다.

Dispatch는 manifest에서 `<model-id> (<effort>)` 같은 legacy `SubAgent Model` 필드를 기록합니다. Root가 Agent 시작 전에 확인하고 이후 갱신에서도 보존합니다. SubAgent가 실행하지 않으면 넣지 않습니다. 기존 이유 필드 별칭도 허용하지만 새 선택 메타데이터는 표준 객체를 사용하세요. [작성 상세도](../guides/authoring-detail.ko.md)와 [SubAgent](../guides/subagents.ko.md)를 참고하세요.

## 발견 사항·현재 상태·확인 방법

요구사항·계획·Task·검증에 영향을 주는 발견 사항을 출처와 영향과 함께 기록합니다. 예를 들어 “hook은 이벤트의 정확한 작업 폴더를 사용한다”는 결론과 그로 인해 접근법이 어떻게 달라지는지 간결하게 남깁니다. 검색 원문 덤프·긴 후보 목록·오래된 사실은 다음 검색의 유용성을 떨어뜨립니다.

기록은 현재 상태로 유지합니다. 변경된 사실을 갱신하고 생략 필드를 보존하며 대화를 계속 덧붙이지 않습니다. 실행 상태는 Task 결과·차단 필드에, 최종 보존 결과는 아카이브에 둡니다. 연상 기억은 검증한 원본에 연결하는 별도의 짧은 교훈입니다. [기억](../guides/memory.ko.md)을 참고하세요.

[Viewer](../guides/viewer.ko.md)에서 계획·Task·발견 사항·아카이브를 확인하거나 Agent에 `tapl_get_item`(`compact=true`는 구조화 필드)과 `tapl_get_archive`로 상세 내용을 요청하세요. 검증은 ID·필수 실행 상태·승인·의존성·소유권과 관련 내용 지침을 확인합니다. 유효한 기록이 있어도 작업의 정확성을 입증하려면 실제 검사가 필요합니다.
