# 연상 기억

[문서 홈](../README.ko.md) · [English](memory.md)

검증한 재사용 가능한 교훈을 다음 작업에서 찾아 원본을 확인하는 기능입니다. 작업 기록 전체를 기억에 복제하지 않고, 탐색에 도움이 되는 짧은 단서를 저장합니다.

## 회상 기준과 한계

`[recall] enabled = true`가 기본값입니다. `tapl_summarize_run`은 선택적으로
`recall_query`를 받고 run당 한 번 최대 3개의 짧은 기억 단서를 제공합니다.
Hook, status, next-action 조회에서는 기억을 검색하지 않습니다. 먼저 단서로 탐색하고
원본 item/archive를 확인하며, 부족하면 `tapl_search_history`를 사용합니다.
기억 내용은 검토할 자료이며 실행 지시가 아닙니다.
자동 주입은 전체 1,200 UTF-8 바이트 이내로 제한합니다. 같은 SQLite의 FTS를
사용하므로 임베딩, 추가 모델 호출, 상주 프로세스가 필요하지 않습니다.

한국어 단서는 `연상 기억`과 `연상기억`처럼 공백만 다른 표현도 검색할 수 있습니다.
합친 길이가 4글자 이상인 한글 단어 구간을 검색용 별칭으로 색인하며 원문 cue와 note는
보존합니다. 질의는 기존처럼 앞의 8단어까지만 사용합니다. 별칭은 개별 cue 안에서만
만들며 영어·숫자·코드 식별자·문장부호 경계를 합치지 않습니다. 자동 회상은 전체 단서의
공백 동치 또는 기존의 의미 있는 단어 2개 일치 기준을 사용하므로, `기억`이나
`프로젝트` 같은 단어 하나가 더 긴 단서 전체의 일치로 인정되지는 않습니다.

## 완료 시 기억 검토

`tapl_finish_run`의 선택 필드 `memory_candidates`, `memory_uses`,
`memory_review={"decision":"capture"|"skip","reason":"..."}`로 기억 저장과
검토 결정을 기록합니다. 후보는 slot 1 또는 2, cue 3–5개, 240자 이하 note,
`source_run_id`와 선택적 `source_item_id`를 가집니다. 짧은 1–2문장은 권장사항이며
검증 조건이 아닙니다. 약어·버전·소수·문장부호도 사용할 수 있습니다.
검증한 함정이나 재사용할 결정처럼 원본 근거가 있는 교훈만 저장하고, 일반 완료 요약,
비밀값, 원문 덤프, 추측은 제외합니다. 사용 기록에는 memory ID와 revision,
`source_checked=true`, 구체적인 `usage`가 필요합니다. 단순 노출은 사용이 아닙니다.
기억 인자를 하나라도 전달할 때 `expected_run_id`를 반드시 지정합니다.

회상이 활성화된 run은 완료할 때 기억을 검토합니다. 후보를 전달하면 `capture` 결정으로
간주합니다. 남길 교훈이 없다면 `memory_review={"decision":"skip",
"reason":"완료 기록 외에 재사용할 교훈이 없음"}`을 전달합니다. skip에는 비어 있지 않은
240자 이하 사유가 필요합니다. 후보와 결정을 모두 생략하면 `review_required`가 남습니다.
작업 완료가 기억 저장 성공을 의미하지는 않습니다.

사용자에게 보여 줄 최종 결과는 기억 처리보다 먼저 저장되므로 기억 오류가 완료 기록을
되돌리지 않습니다. 간결한 응답도 `active_run`만 추출하지 말고 `recall`, `memory`를
포함한 전체 내용을 확인합니다. `tapl_finish_run` → 응답의 기억 처리 결과·다음 행동 확인
→ `tapl_finish_archive` 순서로 실행합니다. 반환된 권고를 재사용하며, 필요한 상세 정보가
없거나 응답 오류·잘림, 컨텍스트 유실, 외부 상태 변경 가능성이 있을 때만 status/next를
추가 조회합니다.
status와 next-action의 `memory_review`에는 `status`, `decision`, `capture_count`,
`pending_errors`가 담깁니다. 결정과 미해결 오류는 기존 run 이벤트에 남아 재시도와
프로세스 재시작 후에도 유지됩니다. 실패한 후보를 수정해 같은 run/slot으로 한 번
재시도하거나 사유와 함께 명시적으로 skip합니다. 성공한 slot을 다시 보내거나 잘못된
입력을 그대로 반복하지 않습니다. 새 검토 기록이 생긴 run은 미해결 검토를 해소한 뒤
보관합니다. 기억 검토 이벤트가 없는 이전 run은 계속 보관할 수 있고 회상이 비활성화된
run은 검토 대상에서 제외됩니다. 보관된 run의 재시도가 다음 run을 수정하지 못하도록
검사합니다.

내용 수정은 신선도를 초기화하며, 검증된 재사용은 내용 수정 시각을 바꾸지 않고
반감기를 7일에서 최대 90일까지 늘릴 수 있습니다. 같은 run에서는 한 번만 강화하며,
직전 내용 수정·강화 후 24시간이 지나야 합니다. 오래된 기억도 관련성이 높으면 회상할 수
있고, 시간이 지났다는 이유로 삭제하지 않습니다.

## 조회·수정·삭제

웹·VS Code가 공유하는 Viewer는 기억 목록/검색, 상세, 원본을 읽기 전용으로 제공합니다.
전체 저장 수와 현재 검색 일치 수를 구분하고 최근 기억 저장 실패가 있으면 표시합니다.
실패는 명시적 skip 이후에도 남는 과거 진단 기록이므로, 미해결 여부는 해당 run의 현재
검토 상태로 확인합니다. 진단 정보를 제공하지 않는 이전 host도 기존 기억 조회를 유지합니다.
기억 수정/삭제는 사용자에게서 명시적 요청을 받은 Agent가 MCP `tapl_update_memory`,
`tapl_delete_memory`와 현재 `expected_revision`으로 수행합니다. 충돌 시 최신 revision을
확인합니다. 삭제한 기억은 tombstone으로 남으며 회상에서 제외됩니다. `tapl_recall`은
수동 읽기 도구입니다. 추론 그래프, 추가 LLM 호출, 백그라운드 프로세스는 추가하지 않습니다.

## 설정과 업그레이드

```sh
taplctl config set recall.enabled false
taplctl config unset recall.enabled  # 기본값 true 복원
```

비활성화하면 자동 저장·회상·강화가 중단되지만 수동 조회·수정·삭제는 가능합니다.
기억 workflow는 MCP를 사용하며 관리 CLI에 별도 workflow 명령을 추가하지 않습니다.
schema 11 DB를 schema 12로 전환할 때 `.tapl/tapl.db.pre-v12.bak`에 한 번 백업한 뒤
기존 기억의 검색 색인을 재구축합니다. 원문, revision, 강화 상태와 작업 기록은 유지하며,
색인 갱신에 실패하면 버전과 색인 변경을 함께 되돌려 재시도할 수 있습니다.
schema 11보다 오래된 DB는 기존 `.tapl/tapl.db.pre-v11.bak` 백업 절차를 사용합니다.
업그레이드할 때는 실행 중인 TAPL 서버를 모두 종료한 뒤 새 버전으로 다시 시작합니다.
이전 버전으로 되돌릴 때도 서버를 종료한 뒤 해당 백업을 복원하며, 백업 이후의 작업은
별도로 보존해야 합니다.

## MCP 조회 예제

에이전트가 현재 hook의 `session_id`를 넣어 `tapl_recall`에 다음 인자를 전달합니다. 반환된 기억 ID로 `tapl_get_memory`를 호출하고 원본 item/archive를 확인한 뒤 적용합니다.

```json
{"session_id":"<current-hook-session-id>","query":"SQLite rollback","limit":3,"offset":0}
```

수정·삭제는 사용자의 명시적 요청이 있을 때만 수행합니다. 먼저 현재 revision을 읽고 `expected_revision`으로 전달합니다.

## 관련 페이지

[검색](search.ko.md) · [Viewer](viewer.ko.md) · [MCP 도구](../reference/mcp.ko.md) · [설정](configuration.ko.md)
