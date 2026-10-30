# PLAN·TASK 작성 상세도

[문서 홈](../README.ko.md) · [English](authoring-detail.md)

`workflow.authoring_detail`은 PLAN·TASK 본문의 설명량과 작업 분할 수준을 선택합니다. 기본값은 `precise`입니다. 기록의 목적·필수 내용·실행 승인·검증을 유지하면서 중복 설명과 불필요한 분할을 조절할 수 있습니다.

## 수준 선택

| 값 | 작성 방식 |
| --- | --- |
| `precise` · 정확하게, 기본 | 현재의 상세한 작성과 TASK 분할 기준을 유지합니다. |
| `normal` · 보통 | 관련 편집을 묶고 필요한 내용을 간결하게 기록합니다. 독립적인 위험이나 별도 검증이 필요한 작업은 분리합니다. |
| `minimal` · 최소 | 목표·실행·검증 중심으로 작성하고 공유 PLAN 내용을 반복하지 않습니다. 함께 처리할 수 있는 변경과 검증을 묶습니다. |

```sh
taplctl config set workflow.authoring_detail normal
taplctl config set workflow.authoring_detail minimal
taplctl config get workflow.authoring_detail
taplctl config unset workflow.authoring_detail  # 기본값 precise 복원
```

보통·최소는 TASK 개수나 글자·토큰 수를 고정하지 않습니다. 복잡도·위험·소유권·의존성·검증 경계에
따라 나누며, 기존 TASK 개수 휴리스틱은 적용하지 않습니다. 설명 중복과 불필요한 분할을 줄여
토큰 사용을 줄이는 작성 지침이며 실제 절감량은 작업과 모델에 따라 달라집니다.
Fast/Standard/Strict 모드, 승인, 필수 필드와 완료 검증은 유지합니다. Strict에 필요한 위험·인터페이스·
롤백·검증 경계도 생략하지 않습니다.

설정은 [설정 파일 선택 규칙](configuration.ko.md#작업-공간과-파일-선택)을 따릅니다. 특정 파일을 바꾸려면 `--config`를 사용하세요.
MCP는 다음 전체 정책 조회에서 변경된 상세도와 새 `policy_revision`을 전달합니다.

## 필수 내용과 custom fields

모든 수준에서 요구사항 추적과 실행 가능한 검증을 유지합니다. TASK에는 `goal`, `action`, `verification`이 필요하며 완료 시 `result`, 차단 시 `blocker`와 `next_action`을 기록합니다. 기존 기록을 갱신할 때는 바뀐 필드만 전달하고 공유 PLAN 사실을 참조합니다. 자연어는 사용자 언어의 문법과 띄어쓰기를 유지하고 식별자·경로·명령·인용은 원문 그대로 둡니다.

`precise`는 독립적인 편집·마이그레이션·검증 단계를 각각 나누는 기존 기준을 유지합니다. `normal`은 관련 편집을 일관된 TASK로 묶고, 소유권·의존성·검토가 달라지는 실질적인 검증이나 독립 위험은 분리합니다. `minimal`은 같은 목표의 관련 실행과 검증을 가능한 작은 일관된 단위로 묶으며, 독립 위험·소유권·의존성·실질적인 검증 경계가 있으면 나눕니다.

`normal`·`minimal`의 일반 root 작업에는 형식만 채우는 advisory `custom_fields`가 필요하지 않습니다. 표준 필드에 없는 지속적인 사실만 간결하게 추가합니다. 단, 모델 선택이나 profile override가 있으면 다음 정보는 유지합니다.

- `Task Profile`: `name`, `match_reason`.
- 관련 `Task Characteristics`: 독립성, context, risk, coordination cost, parallel value.
- `Execution Decision`: `executor`, `delegation_reason`, `model`, `reasoning_effort`, `model_reason`. Override는 이유를 설명합니다.

공유 사실은 PLAN을 참조하고 JSON key와 type을 유지합니다. Dispatch가 쓴 `SubAgent Model`을 보존하고 root는 spawn 전에 manifest를 확인합니다. 중복 custom field 삭제에는 최상위 `null`만 사용합니다. 조건부 `User Notes`도 표준 필드에 없는 지속적인 사용자 사실이 있을 때만 기록합니다.

## 선택 예시와 검증

관련 handler 수정과 회귀 검증이 같은 소유권·위험 경계를 가지면 `normal`·`minimal`에서 함께 기록할 수 있습니다. 별도의 마이그레이션 위험이나 독립적인 검증 책임이 있으면 나눕니다. 이는 예시이며 TASK 수 목표가 아닙니다.

설정을 바꾼 후 `taplctl config get workflow.authoring_detail`과 다음 전체 `tapl_get_next` 응답의 `config.workflow.authoring_detail`, `workflow_policy`, `policy_revision`을 확인합니다. 설정 변경은 이전 기록을 자동으로 다시 작성하지 않습니다. `normal`·`minimal`에서도 승인·소유권·의존성·필수 필드 오류는 계속 검사하며, `precise`의 TASK 개수 휴리스틱만 적용하지 않습니다.

참고 측정에서는 기록 크기와 출력 토큰 중앙값이 감소했지만 전체 입력 절감은 명확하지 않았습니다. 실제 수치·측정법·캐시 포함 여부·해석 한계는 [참고 벤치마크](../reference/benchmarks.ko.md)에 있습니다.

## 관련 페이지

[설정](configuration.ko.md) · [기록과 메타데이터](../concepts/records.ko.md) · [SubAgent](subagents.ko.md) · [워크플로](../concepts/workflow.ko.md)
