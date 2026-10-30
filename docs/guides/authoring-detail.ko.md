# PLAN·TASK 작성 상세도

[문서 홈](../README.ko.md) · [English](authoring-detail.md)

`workflow.authoring_detail`은 PLAN·TASK 본문과 작업 분할 수준을 조절합니다. 기본값 `auto`는 활성 RUN의 Fast/Standard/Strict 모드에 따라 상세도를 결정합니다. 기록이 필요한 경우에만 적용하므로 Fast lightweight는 여전히 PLAN·TASK가 필요 없습니다. 분류·승인·완료 gate는 유지합니다.

## 수준 선택

| 값 | 작성 방식 |
| --- | --- |
| `auto` · 기본 | Fast → `minimal`, Standard → `normal`, Strict → `precise`. 활성 RUN이 없으면 `normal`로 동작합니다. |
| `precise` · 정확하게 | 상세한 작성으로 고정하며 독립적인 편집·마이그레이션·검증 단계를 나눕니다. |
| `normal` · 보통 | 간결한 작성으로 고정하며 관련 편집을 묶고 실질적인 검증이나 독립 위험은 필요할 때 분리합니다. |
| `minimal` · 최소 | 목표·실행·검증 중심으로 고정하며 공유 PLAN을 참조하고 관련 변경과 검증을 묶습니다. |

직접 지정한 `precise`·`normal`·`minimal`은 RUN 모드가 바뀌어도 고정됩니다. 설치·업데이트는 기존에 명시한 수준을 보존합니다. 자동 선택을 쓰려면 `auto`를 설정하거나 키를 제거하세요.

```sh
taplctl config set workflow.authoring_detail auto
taplctl config set workflow.authoring_detail precise
taplctl config set workflow.authoring_detail normal
taplctl config set workflow.authoring_detail minimal
taplctl config get workflow.authoring_detail
taplctl config unset workflow.authoring_detail  # 기본값 auto 복원
```

어느 수준도 TASK 개수나 글자·토큰 수 목표를 고정하지 않습니다. 복잡도·위험·소유권·의존성·검증 경계에 따라 나눕니다. 보통·최소는 중복 설명과 불필요한 분할을 줄이며 실제 토큰 절감량은 작업과 모델에 따라 달라집니다. Strict를 포함해 필요한 위험·인터페이스·복구/롤백·검증 근거는 유지합니다. 작성 상세도는 실행 승인·소유권·의존성·위임 보호 절차를 완화하지 않습니다.

설정은 [설정 파일 선택 규칙](configuration.ko.md#작업-공간과-파일-선택)을 따릅니다. 특정 파일을 바꾸려면 `--config`를 사용하세요.

## 필수 내용과 custom fields

모든 수준에서 요구사항 추적과 실행 가능한 검증을 유지합니다. TASK에는 `goal`, `action`, `verification`이 필요하며 완료 시 `result`, 차단 시 `blocker`와 `next_action`을 기록합니다. 바뀐 필드를 갱신하고 공유 PLAN 사실을 참조합니다. 자연어는 사용자 언어의 문법과 띄어쓰기를 유지하고 식별자·경로·명령·인용은 원문 그대로 둡니다.

작업 묶음은 유효 상세도를 따릅니다. `precise`는 독립적인 편집·마이그레이션·검증을 나눕니다. `normal`은 관련 편집을 일관된 TASK로 묶고 위험·소유권·의존성·검토가 다르면 분리합니다. `minimal`은 이 경계를 지키면서 관련 실행과 검증을 가능한 작은 일관된 단위로 묶습니다.

유효 상세도가 `normal`·`minimal`인 일반 root 작업에는 형식만 채우는 advisory `custom_fields`가 필요하지 않습니다. 표준 필드에 없는 지속적인 사실만 간결하게 추가합니다. 단, 모델 선택이나 profile override가 있으면 다음 정보는 유지합니다.

- `Task Profile`: `name`, `match_reason`.
- 관련 `Task Characteristics`: 독립성, context, risk, coordination cost, parallel value.
- `Execution Decision`: `executor`, `delegation_reason`, `model`, `reasoning_effort`, `model_reason`. Override는 이유를 설명합니다.

공유 사실은 PLAN을 참조하고 JSON key와 type을 유지합니다. Dispatch가 쓴 `SubAgent Model`을 보존하고 root는 spawn 전에 manifest를 확인합니다. 중복 custom field 삭제에는 최상위 `null`만 사용합니다. 조건부 `User Notes`도 표준 필드에 없는 지속적인 사용자 사실이 있을 때만 기록합니다. 표준 객체와 dispatch 요건은 [기록](../concepts/records.ko.md)과 [SubAgent](subagents.ko.md)를 참고하세요.

## 선택 예시와 검증

관련 handler 수정과 회귀 검증이 같은 소유권·위험 경계를 가지면 유효 `normal`·`minimal`에서 함께 기록할 수 있습니다. 별도의 마이그레이션 위험이나 독립적인 검증 책임이 있으면 나눕니다. 이는 예시이며 TASK 수 목표가 아닙니다.

`taplctl config get workflow.authoring_detail`과 `config.workflow.authoring_detail`은 `auto`를 포함한 설정 선택값을 반환합니다. 런타임 상태·`tapl_get_next`·context·검증과 해당 쓰기 응답에는 별도의 `authoring_policy`가 있습니다.

```json
{
  "configured": "auto",
  "effective": "normal",
  "workflow_mode": "standard"
}
```

활성 RUN이 없으면 `workflow_mode`는 `null`이고 `auto`는 `normal`로 결정됩니다. 조회한 세션의 활성 RUN을 사용하므로 다른 세션의 모드가 영향을 주지 않습니다.

유효 정책도 revision에 포함하므로 모드가 바뀌면 `policy_revision`이 달라집니다. `tapl_summarize_run`, RUN 분할, 아카이브·Stop 후 다음 RUN 활성화 등으로 모드나 유효 상세도가 바뀌면 응답은 `policy_refresh_required=true`를 표시하고 `tapl_get_next`를 최우선으로 권고합니다. 계속하기 전에 이 권고를 따라 현재 PLAN과 미완료 TASK의 근거를 재검토하고 새 엄격도에 맞는 위험·인터페이스·복구·검증을 보완합니다. 정책과 검증을 재평가해도 완료·보관 기록을 자동으로 다시 쓰거나 정리된 TASK를 재분할하지 않습니다.

`known_policy_revision`은 해당 revision의 전체 정책·SubAgent 지침·설정을 현재 context에 보유할 때만 전달합니다. 쓰기 응답에서 새 revision을 받았다는 이유만으로 그 전체 정책을 조회했다고 볼 수 없습니다. 전체 내용이 없거나 보유 여부가 불확실하면 revision을 생략하세요. [MCP 진입](../reference/mcp.ko.md#진입조회설정)을 참고하세요.

검증은 필수 필드·승인·소유권·의존성을 계속 확인합니다. 현재 확정된 Strict PLAN에 미완료 작업이 있거나 TASK가 없으면 비어 있는 typed `risks`·`affected_files`·`validation`에 비차단 경고를 내어 실제 위험·인터페이스·롤백·검증 근거의 보완을 안내합니다. 모든 TASK가 정리된 PLAN은 이 경고에서 제외합니다. 구조 검사이며 NLP·키워드·단어 수로 의미를 평가하거나 근거의 충분성을 입증하지 않습니다.

공개된 beta3 벤치마크는 직접 선택한 수준을 비교했으며 당시 `precise`가 비교 기준이었습니다. 현재 기본값 `auto`는 그 비교의 측정 대상이 아닙니다. 수치·측정법·캐시 포함 여부·해석 한계는 [참고 벤치마크](../reference/benchmarks.ko.md)에 있습니다.

## 관련 페이지

[설정](configuration.ko.md) · [기록과 메타데이터](../concepts/records.ko.md) · [SubAgent](subagents.ko.md) · [워크플로](../concepts/workflow.ko.md)
