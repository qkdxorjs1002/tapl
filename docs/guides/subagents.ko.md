# SubAgent 위임

[문서 홈](../README.ko.md) · [English](subagents.md)

TAPL은 실행 manifest를 조율하며 Codex/root runtime이 SubAgent를 생성하고 관리합니다. 실행할 TASK는 의존성이 완료되고 파일·디렉터리 소유 범위가 겹치지 않아야 합니다. 순차 작업, 공유 상태, TASK 사이의 결정은 root가 맡습니다. strategy와 profile은 판단을 돕는 선호이며 위임을 강제하지 않습니다.

## 최초 설정

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

사용자 답변 뒤에는 전체 모델 목록도 `subagents.available_models`에 저장합니다.
일반 `tapl_get_next` 진입에서는 모델 목록 인자를 생략하고 저장된 선호를 사용합니다.
매 세션 시작마다 새 모델을 점검하지 않습니다. 위임 직전에는 선택한 model/effort가
현재 도구와 허용 목록에 모두 있는지 확인하고, 가능한 조합이 없으면 메인에서 진행합니다.
저장된 모델 목록은 현재 가용성의 근거로 사용하지 않습니다.

최초 설정이나 사용자가 요청한 설정 점검에서만
`tapl_get_next(available_models=..., catalog_complete=true)`로 전체 live 목록을 비교합니다.
선택 가능한 모델뿐 아니라 agent 역할에 고정된 모델도 포함해야 합니다. 목록은 전달했지만
완전성을 명시하지 않으면 `comparison_status="incomplete"`이며 변경 추론·설정 질문 없이 작업을 계속합니다.
목록 보완을 위한 재호출도 필요하지 않습니다. 완전한 비교는 `"compared"`, 기존 기준 목록이
없으면 `"no_baseline"`입니다. 완전한 빈 목록은 제거를 확인할 수 있지만 불완전·미전달
목록은 그렇지 않습니다. 확인된 추가·제거·effort 변경에는 설정 변경/유지를 제안하고 실제
답변 뒤에만 `tapl_configure_subagents`로 저장합니다. 유지를 선택하면 허용 목록은 그대로
두고 확인한 전체 목록을 갱신합니다. 기준 목록이 없는 기존 설정도 계속 사용할 수 있으며
설정 점검 시점에 기준을 기록합니다.

## Profile과 모델 선택

설치 템플릿은 다음 model-neutral advisory profile을 안전 우선 순서로 포함합니다.

| Profile | 적용 task | Bias |
| --- | --- | --- |
| `high-risk-cross-cutting` | risk가 높고 범위가 넓거나 shared context·coordination이 큰 작업 | `avoid` |
| `deep-reasoning` | 복잡하거나 불확실하고 많은 context가 필요한 판단 | `neutral` |
| `general-implementation` | 일반적인 범위의 구현 작업 | `inherit` |
| `bounded-routine` | 작고 local하며 예측 가능하고 risk가 낮은 작업 | `prefer` |

`inherit`는 전역 strategy를 따르고, `prefer`는 위임, `neutral`은 방향성 없는 판단, `avoid`는 root 실행을 선호합니다. 모두 판단을 돕는 bias입니다.

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

## Strategy와 실행 경계

`strategy`는 위임 방향의 bias를 결정합니다.

- `aggressive`(기본값)는 task가 독립적이고 필요한 context가 충분히 전달되며 risk가
  관리 가능하고 parallel value나 root context 절감 효과가 클 때 위임을 선호합니다.
  context 공유나 coordination cost 때문에 root가 더 나으면 위임하지 않습니다.
- `balanced`는 같은 판단 기준을 방향성 없이 적용합니다.
- `conservative`는 root 실행을 선호하며 parallel value나 root context 절감 효과가
  context 전달, coordination, risk 비용을 명확히 넘어설 때만 위임합니다.

병렬 batch는 같은 PLAN, 같은 `parallel_group`, `execution_mode="parallel"`, `executor_kind="subagent"`인 TASK를 원자적 `tapl_dispatch_tasks`로 시작합니다. Root는 각 `SubAgent Model` 기록과 manifest를 확인한 뒤 소유 범위 안에서 하나씩 SubAgent를 생성하고, 반환된 정확한 `execution_id`로 완료·차단·건너뛰기를 정산합니다. Spawn 실패나 중단이 있으면 재시도 전에 batch를 복구하거나 취소하며 부분 batch를 남겨 새 batch로 우회하지 않습니다.

저장되거나 실행 가능한 task에는 어떤 strategy에서도 execution approval, dependency
readiness, 배타적이고 겹치지 않는 `owned_paths`, 원자적 dispatch, 정확한 `execution_id`를
사용한 정산이 필요합니다. TAPL write와 task 간 결정은 root만 담당합니다.
dispatch는 runtime이 SubAgent를 spawn하기 전에 manifest의 model과 reasoning effort를
legacy `SubAgent Model` custom field에
기록합니다. bias를 바꾸려면 `strategy = "balanced"` 또는 `"conservative"`로, TAPL의
delegation guidance를 비활성화하려면 `enabled = false`로 설정하세요. 다른 source(예:
`AGENTS.md`)의 delegation instruction까지 제거하지는 않습니다.

`workflow.authoring_detail = "precise"`에서는 executable task의 lifecycle 전체에서 다음 canonical custom field로 결정을 기록합니다.

- `Task Profile`: 선택한 profile(또는 match 없음)과 match 이유를 기록합니다.
- `Task Characteristics`: independence, 필요한 context, risk, coordination cost,
  parallel value를 기록합니다.
- `Execution Decision`: root 또는 SubAgent, model/effort, rationale, profile/model
  override를 기록합니다. task 설계 시, dispatch 전, decision이 바뀐 settlement 후에
  생성하거나 갱신합니다.
- `User Notes`: 조건부 field입니다. standard field에 없는 durable user-relevant fact만
  간결한 category/content/impact entry로 기록합니다.

`normal`·`minimal`의 일반 root 작업은 advisory filler를 생략할 수 있습니다. 모델 선택이나 profile override에는 `Task Profile`, 관련 `Task Characteristics`, `Execution Decision`에 model·effort·이유를 유지하고 override를 설명합니다. [작성 상세도](authoring-detail.ko.md)를 참고하세요.

legacy `SubAgent Model`은 호환성을 위해 atomic dispatch에서 계속 기록하고 SubAgent가
실행되지 않으면 생략합니다. 설정은 preference input이며 실제 runtime 지원, safety gate,
기록된 decision이 최종 기준입니다.

실행 작업은 사용자가 승인한 범위를 따릅니다. 명시적인 수정·테스트·구현·검증 요청은 해당 작업의 실행 승인으로 인정되지만, 조사만 요청한 경우 수정까지 승인한 것은 아닙니다. 적용되는 승인과 실행 상태를 기록하며 이미 받은 승인을 다시 묻지 않습니다.

## 읽기 전용 탐색

범위가 정해진 읽기 전용 파일 탐색이나 조사는계획 전후에 host SubAgent에 위임할 수
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

## 설정 확인과 변경

```sh
taplctl config get subagents --json
taplctl config set subagents.strategy balanced
taplctl config set subagents.enabled false
```

위임하지 않을 때는 `setup_complete`, 모델 허용 목록과 기록된 판단을 확인합니다. 지침을 비활성화해도 다른 출처의 위임 승인은 유지됩니다. TAPL은 DB의 실행 상태를 조율하며 worker를 직접 시작하지 않고, batch 복구 시 외부 worker 프로세스를 종료하지도 않습니다.

## 관련 페이지

[설정](configuration.ko.md) · [작성 상세도](authoring-detail.ko.md) · [워크플로](../concepts/workflow.ko.md) · [MCP 도구](../reference/mcp.ko.md)
