2026-09-28 TAPL 추가 컨텍스트 최적화와 격리 회귀

기준 커밋은 `ef40aaf`, 작업 브랜치는 `perf/context-roundtrip-regression`, 최종 제품 후보는 `v4`다. 행동·기능, 컨텍스트, 속도 순서로 평가했다. **최종본의 실제 Codex 대화 11조건을 각각 새 Morae Box에서 3회 검증했다(33회 통과).** 초기 후보와 준비 실패는 최종 통과 횟수에 포함하지 않았다.

```text
Linux fresh VM 1: 588 passed, 12 skipped, 221 subtests passed
Linux fresh VM 2: 588 passed, 12 skipped, 221 subtests passed
Linux fresh VM 3: 588 passed, 12 skipped, 221 subtests passed
macOS:           589 passed, 11 skipped, 221 subtests passed
Option matrix:   120 configurations × 3 Linux VMs
Real Codex:      11 conditions × 3 fresh Boxes
```

제품 변경

- `tapl_get_item(compact=true)`는 반환한 canonical 필드로 기존 renderer가 본문을 정확히 재현할 때만 plan/task의 중복 `body`를 생략한다. 생략 또는 `compact=false`는 기존 전체 응답을 유지한다. finding, raw text, 사용자 본문, 다른 필드와 오류도 보존한다. 필드 누락·비문자열 값·공백 차이·오래된 본문은 축약하지 않는다.
- 간결 검증 응답이 경고 세 개 뒤의 차단 오류를 가리던 문제를 수정했다. 모든 dictionary 형태 오류를 유지하고 경고만 제한하며 `omitted_issue_count`를 제공한다. 정상 validator 출력 형식과 네 개 이상 오류를 포함한 경우를 검증했다.
- 최초 진입 훅에서 필요한 도구명만 탐색하고 전체 도구 목록을 출력하지 않도록 명시했다. MCP 진입 안내는 필요한 도구를 정확한 이름으로 찾도록 정리했다. 기억 원문은 손실 없는 `compact=true` 조회를 우선하도록 안내한다.
- 추가했던 일반적인 연속 호출 지시는 실제 대화에서 입력량 감소 효과가 일관되지 않아 제거했다. 기존 승인·원문 확인·검증·dispatch·복구·기억 검토 규칙을 유지하고 정책 길이 제한도 원래의 12,500자로 복원했다.
- 도구 29개를 유지했다. 새 optional `compact` 인자를 제외한 기존 도구 계약·스키마 해시는 기준본과 동일하다. DB, 검색, 설정 저장, 승인·dispatch·복구 구현은 변경하지 않았다.

실제 대화 범위

`inspection`, `planning`, `edit`, `recall`, `resume`, `delegation`, `topics`, `scout`, `memory_reuse`, `batch_recovery`, `context_loss`를 각각 3회 통과했다. 모든 조건·반복은 별도 Box, 작업 디렉터리, DB, 설정, Codex 대화를 사용했다. 실제 대화는 네트워크 프록시 제약에 따라 순차 실행했다.

- 읽기 전용 조사와 계획 전용 요청에서 파일 수정·미승인 실행·불필요한 완료/보관이 없는지 확인했다.
- 승인된 수정, 기억 검토 생략, 기존 작업 재개, 별도 주제별 계획 연결을 검사했다.
- 실제 SubAgent 두 명의 병렬 작업은 모델·effort·짧은 handoff, 서로 다른 소유 파일, 실제 수정과 검증, 정확한 manifest execution ID 정산을 확인했다. 읽기 전용 helper는 관찰만 수행하고 TAPL 상태를 쓰지 않는지 검사했다.
- `memory_reuse`는 비어 있지 않은 기억의 정확한 원문, 원문 확인 이후의 실제 bytes 검증, 정확한 revision의 `memory_uses`를 검사했다.
- `batch_recovery`는 dispatch 후 실제 spawn 전에 중단된 상태를 준비하고, 기존 실행 ID 조회·정확한 batch 복구·같은 task의 순차 실행 전환과 정산을 검사했다. 실제 spawn 오류를 주입한 실험은 아니다.
- `context_loss`는 첫 대화에서 계획·작업만 저장하고, 이전 대화가 없는 두 번째 Codex 세션에서 같은 ID와 본문을 복원한 뒤 승인된 작업을 완료한다. 실제 자동 compaction과는 구분한다.

120개 옵션 조합은 검색 4종 × recall 2상태 × 위임 5상태 × profile 3종이다. 각각 별도 임시 workspace·DB·config에서 완전한 정책·현재 설정·revision 갱신을 검사하며, 행렬 전체를 새 Linux VM 세 곳에서 반복했다. 세 VM의 실제 로드된 제품 소스 해시도 최종 후보와 일치했다. 실제 모델 대화는 위 11개 흐름을 대상으로 하며, 120개 조합 모두를 모델 대화로 실행한 것은 아니다.

측정 결과

기준본과 최종본의 기본 수정·기억 재사용은 각각 3회 독립 실행했다. 아래 값은 중앙값이며, 누적 입력 토큰과 최대 단일 요청 입력은 다른 지표다.

| 조건·지표 | 기준본 | 최종본 | 변화 |
|---|---:|---:|---:|
| 기본 수정: 누적 입력 | 171,905 | 143,801 | −16.35% |
| 기본 수정: 최대 단일 입력 | 25,652 | 24,868 | −3.06% |
| 기본 수정: 실행 시간 | 64.912초 | 70.237초 | +8.20% |
| 기억 재사용: 누적 입력 | 250,181 | 233,645 | −6.61% |
| 기억 재사용: 최대 단일 입력 | 28,880 | 29,308 | +1.48% |
| 기억 재사용: 실행 시간 | 98.389초 | 107.114초 | +8.87% |

누적 입력은 두 조건에서 감소했지만 기억 재사용의 최대 단일 입력은 증가했고, 실행 시간도 개선되지 않았다. 따라서 전체 작업의 컨텍스트 창 사용량이나 속도가 항상 좋아진다고 주장하지 않는다. 표본은 각 3회이며 모델 행동과 서비스 지연의 편차가 있다. 기준본/v1은 교대로 실행했고 이후 후보들은 뒤이어 실행했으므로, 시간 비교는 관측값이며 인과 효과나 통계적 유의성의 증거는 아니다.

같은 probe의 문자 수 측정은 다음과 같다.

| 항목 | 기준본 | 최종본 |
|---|---:|---:|
| 초기 MCP 안내 | 867자 | 854자 |
| 전체 진입 응답 JSON | 20,792자 | 20,961자 |
| 도구별 초기 안내 반복 크기 추산 | 64,349자 | 64,179자 |
| 대표 task 전체 응답 | 2,620자 | 2,620자 |
| 대표 task 축약 응답 | 미지원 | 1,767자 |

대표 축약 응답은 32.6% 작고, 제외한 본문을 재구성하면 전체 응답과 정확히 같다. 합성 fixture의 문자 수이며 일반적인 기록 전체의 토큰 절감률은 아니다. 전체 진입 응답은 0.8% 증가했다. 모델 요청 수는 누적 usage 갱신으로 추정하며, discovery 응답 bytes에는 같은 코드 셀의 다른 출력도 포함된다. 원본 계정 rate-limit 정보는 증거에서 제거했다.

개선·재시험에서 발견한 문제

1. v1의 긴 연속 호출 안내는 기능 검사를 통과했지만 기본 수정의 누적 입력 중앙값이 기준보다 32.3% 증가했다. v2로 줄였으나 기본 수정 입력 +2.4%, 기억 재사용 입력 +11.2%여서 해당 일반 지시를 제거했다.
2. v3의 한 대화가 전체 도구 정의를 출력해 15,868-token 응답이 잘렸다. 이후 정책 재조회는 정당했고 실제 기능도 유지됐지만, 컨텍스트 낭비를 줄이기 위해 v4의 최초 훅을 보완했다. 최종 반복은 v4로 다시 실행했다.
3. 평가기가 Python heredoc에서 `beta.txt`를 수정한 뒤 두 파일의 diff를 읽는 명령을 두 파일 수정으로 오인했다. 수정 구간과 뒤따르는 읽기를 분리하고, 다른 파일의 실제 추가 쓰기는 계속 감지하도록 회귀 검사를 추가했다. 원본 실패 결과와 검토 결과를 각각 보존했다.
4. 대화 복원 시험에서 단순 DB 파일 복사가 WAL의 최신 완료 기록을 누락했다. `sqlite3.Connection.backup`으로 바꾸고, 연결이 열린 상태의 committed WAL 회귀 검사를 추가했다. 불완전한 증거 표본은 제외하고 새 환경에서 재실행했다.
5. 네트워크가 활성화된 Morae Box의 병행 시작 두 건은 gvproxy의 호스트 포트 2222 충돌로 실제 Codex 실행 전에 실패했다. 해당 Box를 삭제하고 새 환경에서 순차 재실행했다. macOS 준비 실행의 PATH·임시 경로 별칭 문제도 환경을 맞춘 뒤 전체 검사를 다시 통과했다.

최종 33회 모두에서 실제 recall·위임 설정과 하위 에이전트 수(위임 2명, 읽기 전용 helper 1명, 나머지 0명)를 원본 기록으로 추가 대조했다. 같은 조건의 3회는 동일한 정책 revision을 사용했다.

평가기에는 빈 정책 응답, 원문 누락, 원문 확인 전 검증, 출력만 하는 가짜 검증, 약한 부분 문자열 검사, 바뀐 execution ID, 복구 전 편집, 겹친 순차 작업 등을 거부하는 검사도 있다. 평가기 단위 검사는 74개다. 명령 해석은 fixture에 한정되며 일반적인 shell 효과 분석기로 간주하지 않는다.

[OpenAI의 Programmatic Tool Calling 문서](https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling)는 예측 가능한 단계와 새 판단이 필요한 단계의 경계를 구분하는 근거로 참고했다. 실제 프롬프트 채택·철회 판단은 위 대화 측정으로 결정했다.

재현·정리·적용

macOS 전체 검사:

```sh
PATH="$PWD/tapl/.venv/bin:$PATH" TMPDIR=/private/tmp \
  tapl/.venv/bin/python -m pytest tapl/tests -q
```

실제 대화는 새 Morae/libkrun Box에서 설치된 최종 소스를 대상으로 다음 명령을 실행했다. 실제 대화의 호스트 실행은 harness가 거부한다.

```sh
python /src/.github/scripts/tapl_codex_regression.py \
  --isolated --condition <condition> --model gpt-6-astra
```

보관된 증거는 호스트에서 읽기 전용으로 재검사할 수 있다.

```sh
tapl/.venv/bin/python .github/scripts/tapl_codex_regression.py \
  --condition <condition> --audit-directory <saved-evidence-directory>
```

Codex CLI 0.153.4, gpt-6-astra/high, Linux Python 3.11.2, MCP 2.0.0을 사용했다. Windows 전용 11개 검사는 실행하지 않았고, Linux의 추가 macOS 전용 skip은 호스트 검사로 보완했다. 검증된 범위에서 회귀를 발견하지 않았다는 결과이며 모든 모델·운영체제·입력에 대한 수학적 100% 보증은 아니다.

사용자가 테스트 Box의 인증 정보 복사·사용·삭제를 명시적으로 승인한 뒤 실제 검증을 재개했다. 인증 파일은 각 대화 종료 후 제거했으며, 이번 승인 후 생성한 테스트용 Box 62개도 삭제했다. 기존 Box 6개는 모두 보존했다. 준비 실패·제외 표본·원본 trace·DB·소스 해시는 [측정 JSON](context-roundtrip-2026-09-28.json)에 기록했다.

로컬 원본 증거 묶음은 `.tapl/validation/context-roundtrip-2026-09-28-761746ec.tar.gz`에 보관했다. 인증 정보는 포함하지 않았으며 Git에서는 제외된다. 묶음의 SHA-256과 파일별 증거 해시는 측정 JSON에 있다.

현재 연결된 MCP는 기존 Homebrew 설치본이다. 저장소 변경을 사용자 전역 설치나 실행 중인 서버에 자동 반영하지 않았다. 사용 환경 반영에는 새 소스의 설치·설정 적용과 서버 재시작이 필요하다.

TAPL 실행은 최종 검증·보고서·커밋·정리를 마친 뒤 완료 및 아카이브했다.
