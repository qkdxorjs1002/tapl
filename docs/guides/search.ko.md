# 검색

[문서 홈](../README.ko.md) · [English](search.md)

이전 결정, 구현 패턴, 실패나 tradeoff가 필요할 때 활성·보관된 워크플로 원본을 검색합니다. 먼저 제공된 [기억](memory.ko.md) 단서를 탐색에 사용하고 원본 기록을 확인한 뒤 적용하세요.

## 에이전트와 Viewer에서 검색

예를 들어 “이전 SQLite rollback 결정을 찾아 원본 PLAN이나 FINDING을 보여 줘”라고 요청할 수 있습니다. 에이전트는 작업에 맞는 짧은 질의로 `tapl_search_history`를 호출하고, 결과를 `tapl_get_item`이나 `tapl_get_archive`로 읽습니다. 웹·VS Code [Viewer](viewer.ko.md)도 기록 검색을 제공합니다.

현재 hook의 세션 식별자를 사용한 `tapl_search_history` 인자 예제입니다.

```json
{"session_id":"<current-hook-session-id>","query":"SQLite rollback","limit":12}
```

`query`는 1–500자입니다. MCP에 명시하는 `limit`는 1–50이며 생략하면 `search.max_results`를 사용합니다. 검색 요약은 탐색 단서이므로 원본 item/archive에서 근거와 맥락을 확인합니다. 워크플로 검색은 MCP를 사용하며 `taplctl`에는 workflow `search` 명령이 없습니다.

## 검색 모드 선택

SQLite 전문 검색은 모든 설치에서 사용할 수 있습니다. 선택적 시맨틱 검색은 임베딩과 벡터 색인을 추가합니다.

| `search.mode` | 동작 |
| --- | --- |
| `bm25` | SQLite FTS의 텍스트 일치 순위입니다. |
| `word` | 제목, 본문, raw text, custom JSON과 stable ID의 텍스트를 검색합니다. |
| `semantic` | 사용 가능하면 벡터 유사도로 검색하고, 아니면 사유와 함께 BM25로 대체합니다. |
| `hybrid`(기본) | 시맨틱·BM25 결과 순위를 합칩니다. 시맨틱 검색이 불가능하면 BM25만 사용하고 대체 사유를 표시합니다. |

```sh
taplctl config get search --json
taplctl config set search.mode hybrid
taplctl config set search.max_results 12
taplctl config set search.hybrid_semantic_ratio 0.65
```

Hybrid 가중치는 시맨틱 `0.65`, BM25 `0.35`가 기본입니다. BM25 가중치는 `1 - hybrid_semantic_ratio`로 계산합니다. 벡터 거리와 BM25 점수를 그대로 더하지 않고 가중 역순위를 합칩니다. 가중치 `0`인 출처는 점수에 기여하지 않습니다. `configured_mode`, 반환된 `mode`, 제공되는 경우 `fallback_reason`, 결과의 `search_source`로 설정과 실제 사용 결과를 구분할 수 있습니다. Semantic 대체 시 `mode="bm25"`, hybrid 대체 시에는 `mode="hybrid"`를 유지하고 BM25 결과를 사용합니다.

## 시맨틱 의존성과 색인

[설치](../getting-started/installation.ko.md)의 semantic extra나 `taplctl-semantic` formula를 사용하면 `numpy`, `sentence-transformers`, `sqlite-vec`를 설치합니다. 현재 임베딩 모델은 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`이며 차원은 384입니다. 모델은 구현에서 고정하며 공개 `search.model` 설정은 없습니다. SubAgent 모델 선호는 위임용이며 임베딩 모델을 선택하지 않습니다.

```sh
taplctl reindex --dry-run --json
taplctl reindex --json
```

Dry-run은 item 수, 선택 의존성 설치 여부, 모델과 차원을 표시합니다. 실제 reindex는 검색 가능한 custom field를 포함해 기존 item의 벡터 색인을 재구축합니다. 선택 의존성이 필요하며 모델 가중치가 캐시에 없으면 로드·다운로드할 수 있습니다. 벡터 색인이 비었거나 없거나 시맨틱 의존성을 사용할 수 없으면 텍스트 검색으로 대체합니다. 기존 공간의 시맨틱 색인을 갱신할 때 재구축하며, 전문 검색에는 벡터 재구축이 필요하지 않습니다.

## 임베딩 provider와 searchd

`search.semantic_provider`는 원격 모델 사업자가 아니라 질의 임베딩 생성 경로를 선택합니다.

| Provider | 동작 |
| --- | --- |
| `local` | 호출 프로세스에서 임베딩 모델을 로드합니다. |
| `auto`(기본) | 실행 중인 searchd를 먼저 시도하고, 없거나 daemon 오류가 나면 로컬 임베딩을 시도합니다. |
| `daemon` | searchd를 시도합니다. 사용 가능한 daemon이 없으면 로컬 임베딩을 시도하지만 다른 daemon 오류에서는 시맨틱 검색을 사용할 수 없어 텍스트 대체가 가능합니다. |

```sh
taplctl config set search.semantic_provider auto
taplctl searchd start
taplctl searchd status --json
taplctl searchd stop
```

검색이 daemon을 자동 시작하지는 않습니다. Semantic Homebrew formula도 미리 로드한 검색 프로세스를 자동 시작하지 않습니다. `searchd`는 질의 사이에 모델을 유지하고 기본 1,800초 유휴 후 모델을 해제합니다. `search.searchd_model_idle_timeout_seconds = 0`은 유휴 해제를 끕니다. 모델 해제는 daemon 종료와 다릅니다. `searchd start --idle-timeout SECONDS`로 해당 프로세스 값을 덮어쓸 수 있습니다.

기본 socket은 `~/.tapl/searchd.sock`이며 `TAPL_SEARCHD_SOCKET`으로 다른 경로를 선택합니다. 관리 명령은 `--socket PATH`도 받습니다. 별도 관리 socket은 검색 호출자 환경과 경로를 맞춰야 합니다. Daemon은 Unix domain socket을 사용하므로 Windows에서 지원하지 않습니다. Windows는 의존성이 있으면 로컬 시맨틱 검색을, 없으면 BM25를 사용합니다. 이 로컬 임베딩 모델에 provider API 자격 증명은 필요하지 않습니다.

## 검증과 한계

`taplctl config get search --json`, `taplctl reindex --dry-run --json`, searchd 사용 시 `taplctl searchd status --json`을 확인합니다. 이후 실제 검색 응답의 대체 사유를 확인하고 원본 기록을 여세요. `semantic`·`hybrid` 설정만으로 벡터 검색 사용을 입증하지는 않습니다.

별도 연상 기억 저장소는 SQLite FTS와 자체 단서 규칙을 사용합니다. Semantic provider 설정은 기억 일치 방식을 바꾸거나 recall에 자동 모델 호출을 추가하지 않습니다. 검색 적합도가 과거 결정의 정확성이나 현재 유효성을 입증하지는 않으므로, 원본과 현재 코드를 확인한 뒤 적용하세요.

## 관련 페이지

[설정](configuration.ko.md) · [기억](memory.ko.md) · [Viewer](viewer.ko.md) · [CLI 참조](../reference/cli.ko.md) · [MCP 도구](../reference/mcp.ko.md)
