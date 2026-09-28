2026-09-28 TAPL 컨텍스트·성능 최적화 검증

최종 제품 코드에서 Linux 전체 회귀를 새 VM 3개에서 각각 통과했고, 실제 Codex 대화는 6개 조건을 각각 새 VM에서 3회씩 통과했다. 평가기 보강 후 보존한 실행 증거도 다시 판정했다. 우선순위는 행동·기능, 컨텍스트, 속도 순서로 적용했다.

기준 커밋은 `85407c8e55c06d402e802e046cb70443e8fc6ee4`, 작업 브랜치는 `perf/context-isolated-regression`이다. 최종 코드 해시, 각 대화의 고유 session ID, 결과·로그 해시와 원본 위치는 [측정 JSON](context-optimization-2026-09-28.json)에 있다.

변경과 보존 범위

- `prompt.py`: 필요한 템플릿 변수만 계산한다. 공개 `template_variables()`는 유지하고 설정·정책을 캐시하지 않는다. override, 중복·미지·잘못된 placeholder의 출력 동등성을 검사했다.
- `mcp_server.py`: 초기 안내문을 정책 진입 안내로 줄였다. `tapl_get_next`에서 전체 정책·설정·위임 지침을 읽는 절차와 정책 소실 후 재조회 요구는 유지한다. 사용자 지정 instructions와 빈 문자열도 유지한다.
- 실행 기록에서 드러난 오해를 고쳤다. canonical metadata의 JSON 객체 모양, 동일 PLAN의 병렬 배치 제약, 파일별 독립성과 별도 주제의 구분을 명시했다. MCP envelope의 중복 출력도 피하도록 안내한다.
- 29개 도구의 이름·입출력 스키마·기본값·annotations 해시는 기준과 동일하다. 설명문은 의도적으로 보강했으므로 전체 설명 텍스트의 바이트 동일성을 주장하지 않는다. DB, 승인 검증, 실행·복구·기억·검색·설정·아카이브 구현은 변경하지 않았다.

기능·행동 검증

```text
Linux fresh VM × 3: 472 passed, 12 skipped, 221 subtests passed
macOS:             473 passed, 11 skipped, 221 subtests passed
Real Codex:        18/18 passed (6 conditions × 3 fresh VMs)
```

| 실제 대화 조건 | 통과 | 실행 시간 3회, 초 |
|---|---:|---|
| 수정·검증·완료 | 3/3 | 77.291, 58.655, 73.651 |
| 기억 옵션 활성화·이유 있는 skip | 3/3 | 70.282, 46.376, 72.869 |
| 계획만 수립·승인 전 편집 금지 | 3/3 | 44.343, 44.743, 45.569 |
| 저장된 작업 재개 | 3/3 | 64.517, 66.064, 79.914 |
| 실제 병렬 위임·정확한 정산 | 3/3 | 110.144, 111.685, 119.329 |
| 독립 주제별 계획·작업 연결 | 3/3 | 99.767, 103.523, 94.236 |

모든 대화는 morae-mcp/libkrun에서 Codex CLI 0.153.4, `gpt-6-astra/high`로 실행했다. 각 VM은 별도 git fixture, TAPL DB·설정과 Codex 세션을 사용했다. 일반 진입의 catalog 생략, 정책 진입 횟수, 완료·아카이브 상태, 요구한 파일 내용도 검사했다. 계획 전용 조건은 실행 승인·작업 실행·완료·아카이브가 없음을 확인했다. 재개 조건은 원래 RUN과 TASK ID 및 저장된 본문 조회를 확인했다.

병렬 위임은 성공한 spawn receipt를 실제 child session에 연결하고, 담당 파일→task→execution 연결, 성공한 편집·검증 명령의 call ID와 exit code, child 완료 후 정산, 실행 구간 중첩까지 확인했다. 세 실행의 child 구간은 각각 3초·4초·10초 겹쳤다. 자식의 직접 TAPL 쓰기 등 6가지 가짜 통과 사례를 거부하는 평가기 테스트와 2가지 정상 사례도 추가했다. 독립 주제는 PLAN 수뿐 아니라 각 주제의 담당 파일과 TASK의 spec_id 연결을 검사한다.

옵션 120조합은 `검색 4종 × recall on/off × 위임 5상태 × profile 3종`이다. 각 조건은 서로 다른 workspace·DB·config에서 전체 정책·설정, retained/stale revision, 불완전 catalog, 상세 status·events 옵션을 검증한다. 이 전체 행렬을 독립 VM 3개에서 반복했다. 기존 검색·기억·복구·설정·viewer·CLI·installer·packaging 테스트도 전체 suite에 포함된다. recall 실제 대화 조건은 빈 기억 저장소의 reasoned skip 경로이며, 실제 기억 내용 검색·수정·강화 경로는 기존 자동 테스트로 검증했다.

Windows 전용 11개 테스트는 실행 환경상 제외했다. Linux에서는 macOS 전용 테스트 1개도 제외했으며 macOS 전체 실행으로 보완했다. 검증한 범위의 기능 보존을 확인한 결과이며, 모든 플랫폼과 모든 모델 출력에 대한 절대적인 100% 보증은 아니다.

컨텍스트·속도 측정

| 항목 | 기준 | 최종 |
|---|---:|---:|
| 초기 안내문 문자 수 | 2,743 | 867 |
| 도구별 안내문 반복 크기 추산, 문자 | 118,763 | 64,437 |
| 전체 진입 응답 JSON 문자 수 | 20,747 | 21,141 |
| retained-policy 진입 응답 문자 수 | 793 | 793 |
| 동일 수정 대화 누적 입력 토큰 | 251,123 | 154,516 |
| 동일 수정 대화 시간, 초 | 77.854 | 73.651 |

반복 크기 추산은 `직렬화한 도구 JSON + 도구 수 × 초기 안내문`이며 45.7% 감소했다. 실제 context window 토큰 측정값은 아니다. 정확한 행동 안내를 보강해 한 번 읽는 전체 정책 응답은 조금 커졌고, 반복되는 안내문 비용이 크게 줄었다.

동일 수정 대화의 누적 입력 토큰 중앙값은 38.5% 줄었다. 최종 값은 3회 중앙값, 기준 대화는 유효 표본 1회다. input_tokens는 여러 모델 요청의 입력 합계이며 캐시 입력도 포함하므로 최대 컨텍스트 점유량과 구분해야 한다. 대화 시간은 모델·캐시·호스트 부하의 영향을 받으므로 일반적인 속도 보장으로 해석하지 않는다.

| 렌더 함수 | 기준 μs | 최종 μs | 관측 배율 |
|---|---:|---:|---:|
| `session_start` | 15.000 | 1.666 | 9.0배 |
| `user_prompt` | 18.730 | 5.458 | 3.4배 |
| `stop` | 15.833 | 2.542 | 6.2배 |
| `full_policy` | 113.459 | 97.521 | 1.2배 |

각 렌더 측정은 300회 표본 중앙값이며, 최종 수치는 독립 VM 3개의 중앙값이다. Python 렌더 비용의 변화이며 전체 Codex 대화 속도와는 별개다.

수정·재검증 루프

초기 대화에서 문자열 metadata로 인한 완료 재시도를 발견해 객체 모양을 명확히 했다. 이후 병렬 조건에서 파일마다 PLAN을 나누어 dispatch가 실패했고, 다음 후보에서는 배치 제한을 이유로 승인된 병렬 실행을 포기했다. 결과 목적 중심으로 계획을 묶고 잘못 나눈 계획을 수정하도록 안내한 최종 후보는 실제 병렬 실행 3회를 통과했다. 별도 주제 분리가 유지되는지도 추가 조건으로 3회 확인했다.

검증기 오류도 구분해 고쳤다. 필요한 AGENTS 메타데이터 탐색을 정책 위반으로 오판하던 검사를 좁혔고, CLI JSON 스트림에 나오지 않는 spawn은 rollout의 실제 세션으로 판정했다. 원본 결과를 덮어쓰지 않고 강화된 평가기로 재검사했다. stdin 종료, 지원하지 않는 모델, 네트워크 relay 포트 충돌, Box clone 실패 등 실행이 성립하지 않은 환경 오류는 통과 표본에 포함하지 않았다. guest 완료 후 MCP 종료 응답 오류가 발생한 경우에는 저장된 Codex exit code·완료 이벤트·결과 파일을 확인했다.

재현

```sh
TMPDIR=/private/tmp PATH="$PWD/tapl/.venv/bin:$PATH" tapl/.venv/bin/python -m pytest tapl/tests -q
tapl/.venv/bin/python .github/scripts/tapl_context_probe.py
tapl/.venv/bin/python .github/scripts/tapl_codex_regression.py --condition delegation --audit-directory /path/to/evidence
```

실제 대화는 새 morae-mcp Box마다 설치된 변경본, Codex CLI와 정상 인증을 준비한 후 `tapl_codex_regression.py --isolated --condition <조건> --model <사용 가능한 모델>`을 실행한다. 스크립트는 morae guest kernel marker를 확인하고 인증 파일을 종료 시 삭제한다. 일반 호스트에서는 live 모드를 실행하지 않는다. `--audit-directory`는 호스트에서 읽기 전용으로 실행할 수 있다. [공식 Codex 비대화형 실행 문서](https://developers.openai.com/codex/noninteractive/)의 JSON 실행 방식을 사용했다.

적용은 변경 커밋을 설치하고 MCP 서버를 다시 시작한 뒤 확인한다. 롤백은 이 변경 커밋을 revert하면 되며 데이터 마이그레이션은 없다.
