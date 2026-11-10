# Viewer·확장 UX 설계와 업그레이드 계획

[English](viewer-ux-design.md) · **한국어**

**설계 제안입니다. 제품의 현재 동작은 [Viewer](../guides/viewer.ko.md)와 [VS Code 확장](../guides/vscode.ko.md)이 기준입니다.**

## 통합 시안

[통합 Viewer 시안](../design/viewer-workbench/index.html)은 03의 현재 작업 집중 화면, 02의 Flow 칸반과 01의 TASK 현황을 하나의 고정 셸로 결합합니다. [현재 RUN](../design/viewer-workbench/current-ko.png) · [Explore 상세](../design/viewer-workbench/explore-ko.png) · [통합 검색](../design/viewer-workbench/search-ko.png) · [영문·어두운 테마](../design/viewer-workbench/current-en-dark.png) 이미지에서도 확인할 수 있습니다.

| 영역 | 구성과 동작 |
| --- | --- |
| 상단 고정 바 | `tapl` 브랜드 영역 오른쪽에 언어·라이트/다크 아이콘을 나란히 정렬합니다. 언어 아이콘을 열어 한국어·English를 선택합니다. 여유 공간에 아카이브되지 않은 RUN의 제목·상태·ID로 구성한 네비게이션 탭을 배치하고 세션 문구는 표시하지 않습니다. 전환 시 선택한 RUN의 현황·Explore·관리 범위로 바뀝니다. 방향키·Home·End를 지원하고 탭이 많으면 탭 영역만 가로 스크롤합니다. |
| 좌측 상단 Workspace | 현재 RUN은 03의 집중 화면이며 메뉴 우측에 완료 TASK / 전체 TASK 비율을 반올림한 정수 %를 표시합니다(TASK가 없으면 0%). TASK 현황은 01을 바탕으로 한 전체 폭의 목록으로 구성합니다. TASK를 선택하면 Explore의 TASK 상세 페이지로 바로 이동하며 해당 폴드와 선택 항목도 맞춥니다. 현재 RUN·TASK 현황의 페이지 전환은 좌측 메뉴에서 제공하며 해당 본문 탭과 페이지 뎁스는 표시하지 않습니다. |
| 좌측 상단 Explore | PLAN·TASK·FINDING은 각각 계획 흐름·체크리스트·발견 근거를 나타내는 아이콘으로 구분하며 폴드 중 최대 하나만 펼칩니다. 펼친 목록은 별도로 스크롤하며 RUN·유형별 위치를 유지합니다. 항목 선택 시 팝업 대신 본문에 목적·요구사항·검증·결과·연결 레코드·추가 필드를 표시합니다. |
| 좌측 하단 Memory | 기록 검색과 연상 기억 페이지로 이동합니다. 기록 검색은 PLAN·TASK·FINDING을 통합하고 `현재 RUN / 전체 기록` 범위와 `RUN별 보기 / 레코드별 보기`를 독립적으로 선택합니다. 연상 기억은 기존처럼 작업 공간의 교훈·단서·출처를 읽기 전용으로 탐색합니다. |
| 좌측 하단 Management | 관리 제목 아래 `RUN 삭제`를 배치하며 기존 폐기 의미를 유지합니다. 기록이 있는 RUN은 이력으로 보관하고 빈 RUN은 삭제하는 절차를 안내하며, 정확한 RUN ID 확인 대화상자를 보여줍니다. 서버의 폐기 지원 여부와 RUN의 `writable`을 따르며 다른 로컬 세션도 쓰기 가능하면 선택할 수 있습니다. 읽기 전용 공유 이력에서는 비활성화합니다. 폐기는 외부 Agent·프로세스를 중지하지 않습니다. **시안의 확인 버튼은 실제 RUN이나 가상 데이터를 삭제하지 않습니다.** |

PC에서는 상단 바와 왼쪽 패널이 고정되고 오른쪽 본문만 스크롤합니다. Explore의 펼친 목록은 별도의 스크롤 예외입니다. 좁은 화면에서는 좌측 탐색을 메뉴로 열며 닫힌 패널은 키보드 탐색에서 제외합니다. RUN마다 페이지·검색 설정·선택 레코드가 분리되고, 다른 RUN의 검색 결과나 기억 출처를 선택하면 원문 RUN 탭으로 이동합니다. 아카이브 RUN은 기록 검색이나 연상 기억의 출처에서 열면 상단 맨 오른쪽에 임시 탭 하나로 표시합니다. 다른 RUN 탭을 선택하면 임시 탭은 사라지며, 이미 기본 탭에 있는 RUN은 중복하지 않습니다. 동일 RUN 내 페이지·언어·테마 전환에서는 유지하고, 돌아가기와 직접 링크에서는 선택한 RUN에 맞춰 표시합니다. 완료 여부와 아카이브 여부는 별개입니다. 같은 표시 ID라도 출처가 다른 RUN을 구분하는 예시가 포함됩니다.

TASK 현황과 PLAN·TASK·FINDING 탭의 개수는 한국어 `12개`, 영어 `12 items`(단수 `1 item`)처럼 단위를 함께 표시합니다.

현재 RUN의 기존 단계 바에서 계획·승인·실행·검증을 선택해 아래 내용을 미리 봅니다. 기본 단계는 RUN별 가상 데이터에 정하며, 선택한 단계는 RUN·언어·테마 전환과 원문에서 돌아가기에 유지됩니다. 링크의 `phase=plan|approval|execution|verification`로 직접 열 수도 있습니다. 연결선·원의 진행 색과 현재 단계 표시는 RUN 진행 단계에 고정하고, 보고 있는 단계는 라벨 밑줄·강조로 따로 표시합니다. 단계 선택은 실제 RUN 상태, 승인 결정이나 검증 결과를 변경하지 않습니다.

| 단계 | 표시 내용 | 예시 이미지 |
| --- | --- | --- |
| [계획](../design/viewer-workbench/index.html#run=local24&page=current&phase=plan&lang=ko&theme=light) | PLAN 목표·요구사항과 작업 구성(최대 6개 미리보기), PLAN 원문·TASK 현황 연결 | [계획 화면](../design/viewer-workbench/planning-ko.png) |
| [승인](../design/viewer-workbench/index.html#run=local24&page=current&phase=approval&lang=ko&theme=light) | 대상 PLAN별 승인 완료·대기, 검토 범위·요구사항과 PLAN 원문 | [승인 화면](../design/viewer-workbench/approval-ko.png) |
| [실행](../design/viewer-workbench/index.html#run=local24&page=current&phase=execution&lang=ko&theme=light) | 진행 중인 작업·막힘 안내와 수평 Flow 칸반 | [실행 화면](../design/viewer-workbench/current-ko.png) |
| [검증](../design/viewer-workbench/index.html#run=local24&page=current&phase=verification&lang=ko&theme=light) | 가상 통과·실패·대기 결과, TASK 근거와 관련 FINDING | [검증 화면](../design/viewer-workbench/verification-ko.png) |

방향키·Home·End와 Enter·Space로 단계를 탐색합니다. 승인 결정 버튼은 제공하지 않으며 검증 통과를 TASK 완료에서 추론하지 않습니다. PLAN이 없거나 검증 결과가 없는 경우 각 단계의 빈 상태를 표시합니다.

실행 화면의 본문 상단 집계와 하단 계획 요약은 표시하지 않습니다. `진행 중인 작업` 아래에 02 Flow Board의 상태별 칸반을 배치합니다. 대기·진행 중·막힘·완료 열에는 단위를 붙인 개수와 TASK ID 순서의 제목·담당·선행 조건을 표시하며, 건너뜀 작업이 있으면 별도 열로 표시합니다. 카드는 읽기 전용이며 선택하면 Explore 상세로 열고 돌아갈 때 본문 스크롤과 원래 카드 포커스를 복원합니다. 모든 화면 폭에서 상태 열을 한 줄로 유지하며 칸반 안에서 좌우로 스크롤해 분류를 읽습니다. 내용이 남은 쪽의 경계는 투명도 그라디언트로 부드럽게 처리하며 시작·끝에서는 해당 쪽 페이드를 없앱니다. 세로 이동은 본문 스크롤을 사용합니다. 스크롤 영역은 키보드로 접근할 수 있고, RUN·언어·테마 전환과 돌아가기에서 가로 위치를 복원합니다. 캐러셀과 이어지는 작업·완료한 일 목록은 표시하지 않습니다.

상단 브랜드는 `tapl` 텍스트로 표시합니다. 내부 링크로 이동한 페이지에는 오른쪽 상단에 `돌아가기`가 나타납니다. TASK·검색 결과·연결 레코드·기억 출처에서 이동한 뒤 이전 RUN, 페이지, 검색·필터, 펼친 그룹, 선택 레코드와 스크롤 위치로 돌아갑니다. 언어·테마는 현재 설정을 유지합니다. 좌측 메뉴나 상단 RUN을 직접 선택하면 새 탐색을 시작하며 복귀 경로를 비웁니다. 직접 진입하거나 새로고침한 화면에는 복귀 버튼을 표시하지 않습니다.

기록 검색의 기본 범위는 전체 기록이며 현재 RUN으로 좁힐 수 있습니다. 검색 범위 선택에는 아래 화살표를 표시하고, RUN별·레코드별 보기 전환은 상태 필터와 같은 옅은 외곽선의 알약 형태로 구성합니다. 전체 기록의 RUN별 검색 결과는 RUN 제목·출처·일치 건수를 먼저 표시하고 그룹을 펼쳐 개별 기록을 읽습니다. 언어·테마 전환 시 그룹의 펼침 상태를 유지합니다. 레코드별 보기는 개별 기록을 바로 나열합니다.

한국어·영어 UI, 상태·안내·접근성 레이블과 예시 내용을 전환할 수 있으며 밝음·어두움도 지원합니다. 언어 전환은 실제 저장된 레코드의 자동 번역을 뜻하지 않습니다. 실제 제품의 locale 전달·기존 번역 키·사용자 작성 내용과 분리해 구현해야 합니다. 링크의 `#run=local24&page=tasks&lang=en&theme=dark`처럼 화면 문맥을 지정해 열 수도 있습니다.

화면에는 제목·상태·기록 내용·필요한 출처를 남기고 공통 소개, 데모 배지, 반복 푸터와 중복 문맥을 표시하지 않습니다. 선택한 RUN은 상단 탭에서 확인하며 현재 RUN·TASK 현황·Explore 상세의 본문 상단에는 RUN ID·세션·출처 행을 반복하지 않습니다. RUN별 검색은 그룹 헤더에 출처를 모으고 레코드별 보기에서는 각 결과에 표시합니다. 빈 상태 안내와 폐기 확인·영향 설명은 필요한 위치에 유지합니다.

밝은 테마는 차가운 회색·흰색 표면과 짙은 청록색 강조를, 어두운 테마는 남색 표면과 옅은 청록색 강조를 사용합니다. 본문·보조 글자와 행간을 키우고 얇은 구분선·절제된 그림자로 계층을 구분합니다. RUN 선택선과 본문은 260ms, 폴드와 검색 그룹은 180–240ms로 전환하며 빠른 연속 조작은 진행 중 모션을 정리합니다. `prefers-reduced-motion`에서는 모션을 생략하고, 테마 색상은 즉시 교체합니다.

통합안은 제품 연결 전의 독립적인 가상 시안입니다. 기존 CLI·MCP·설정·VS Code 호스트·RUN 폐기는 변경하지 않습니다. 아래의 10종은 개별 정보 구조를 비교하는 대안으로 유지합니다.

통합안은 임시 프로필의 헤드리스 Chrome에서 한국어·영어, 밝음·어두움, 폭 320·390·1024·1600px의 단계별 화면과 주요 페이지를 확인했습니다. 단계 선택·직접 링크·PLAN/TASK/FINDING 원문 복귀·포커스·스크롤·RUN별 상태·읽기 전용·빈 상태와 일반/동작 줄이기를 검증했습니다. 수평 칸반의 휠·키보드·페이드 경계와 폭 변경 복원도 확인했습니다. 기본 팔레트의 본문·보조 글자와 주요 버튼 22개 색상 조합은 최소 대비 4.64:1이었습니다. 대표 화면을 육안 검토했습니다. 실제 VS Code 호스트·고대비·스크린리더 검증을 대신하지 않습니다.

## 시안 살펴보기

[시안 10종 갤러리](../design/viewer-concepts/index.html)를 브라우저에서 여세요. 설치 없이 동작하며 스타일과 스크립트는 모두 로컬 파일입니다. GitHub의 HTML 원문에서는 미리보기가 실행되지 않으므로 저장소를 내려받아 열어야 합니다.

[전체 비교 이미지](../design/viewer-concepts/overview.png)도 볼 수 있습니다. 갤러리의 `#overview`는 전체 비교 화면으로 바로 연결됩니다.

- 왼쪽 목록 또는 이전·다음 버튼으로 시안을 바꿉니다. `#01`부터 `#10`까지 직접 접근할 수 있습니다.
- `함께 보기`, `Viewer`, `확장`과 밝음·어두움 테마를 비교합니다.
- `화면 상태`에서 정상·로딩·비어 있음·연결 오류를 확인합니다.
- 작업 상세, 상태 필터, 기록 검색, 기억 출처와 문서 탐색은 시안 안에서만 동작합니다. 검색 입력은 Enter로 제출합니다.
- `전체 시안 비교`에서 열 가지 정보 구조를 한눈에 비교합니다.

RUN·작업·담당·기록·시각은 모두 가상 예시입니다. 진행률 2/6도 비교용 데이터이며 실제 업그레이드 완료를 뜻하지 않습니다. 이 갤러리는 **DaisyUI 5.7.50 / Tailwind CSS 4.3.5**를 별도로 빌드합니다. 제품의 패키지 버전·설정·CLI·MCP 인자와 실행·승인·폐기 동작은 바꾸지 않습니다. 확장 미리보기는 좁은 webview 콘텐츠이며 VS Code의 네이티브 Tree View·호스트·CSP 실행을 재현하지 않습니다.

## 현재 구현에서 확인한 개선 지점

| 관찰 근거 | UX·유지보수 영향 | 개선 방향 |
| --- | --- | --- |
| `OverviewView`는 큰 헤더, 상태 pill, 6개 지표 카드를 작업 목록 앞에 배치합니다. | 현재 작업과 막힘보다 요약 지표를 먼저 훑어야 합니다. | RUN 제목·현재 작업·막힘을 먼저 배치하고 나머지 지표를 접습니다. |
| `App.tsx`에 화면 전환·RUN 탭·보드·기록·상세 렌더러가 함께 있습니다. | 정보 구조를 변경할 때 검토 범위가 큽니다. | 화면, 읽기 모델, 컴포넌트, host 어댑터를 분리합니다. |
| DaisyUI를 쓰지만 CSS에서 버튼·입력·탭·카드와 `tapl-*` 구조를 폭넓게 덮어씁니다. | 기본 컴포넌트와 커스텀 표현을 함께 관리해야 합니다. | 의미 토큰과 variant 조합을 우선하고 배치에만 전용 CSS를 둡니다. |
| `styles.css`는 이미 VS Code의 의미 색상·폰트·포커스 변수를 사용합니다. | 이 기반을 잃으면 편집기 테마와 화면이 어긋납니다. | 기존 변수 연결을 DaisyUI 5 토큰 어댑터로 보존합니다. |
| 브라우저와 확장은 공유 React UI를 사용하지만 갱신 방식은 다릅니다. | 화면 분리만으로 transport 책임이 분리되지는 않습니다. | 브라우저 polling과 확장 push를 어댑터에 남깁니다. |

근거: [`App.tsx`](../../vscode-extension/src/webview/App.tsx), [`styles.css`](../../vscode-extension/src/webview/styles.css), [`MemoryView.tsx`](../../vscode-extension/src/webview/MemoryView.tsx), [`extension.ts`](../../vscode-extension/src/extension.ts), [`viewer.py`](../../tapl/taplctl/viewer.py). 관찰에 기반한 설계 판단이며 사용자 테스트나 성능 개선 측정 결과는 아닙니다.

## 열 가지 방향

| 시안 | 핵심 정보 구조 | 확장 적용 | 적합한 용도·한계 |
| --- | --- | --- | --- |
| **01 Signal Desk** | 작업 목록 + 선택한 작업 상세 | 간결한 목록 + 상세 대화상자 | **통합안의 TASK 현황 기반.** 목록과 근거의 균형이 좋습니다. |
| **02 Flow Board** | 대기·진행·막힘·완료 레인 | 상태 필터 + 세로 레인 | **통합안의 현재 RUN 하단 작업 흐름 기반.** 작업이 많으면 본문이 길어집니다. |
| **03 Focus Now** | 현재 작업 + 목적·검증 + 다음 대기열 | 현재 작업을 첫 화면에 집중 | **통합안의 현재 RUN 기반.** 전체 비교에는 별도 목록이 필요합니다. |
| 04 Evidence Stream | 시간순 이벤트 + 근거 기록 | 세로 타임라인 | 재개·회고. 시각·순서를 의존성과 혼동하지 않아야 합니다. |
| 05 Record Library | 검색 결과 + 원문 | 결과 다음에 원문 배치 | 기록·아카이브 검색. 실시간 상태에는 덜 적합합니다. |
| 06 Memory Garden | 교훈 + 검색 단서 + 출처 | 한 열의 기억 카드 | 기억 전용 화면. 긴 내용은 점진적으로 펼칩니다. |
| 07 Run Atlas | 소유자·출처가 드러나는 RUN 카드 | RUN 카드 세로 목록 | 다중 세션·공유 이력. 단일 RUN에는 과할 수 있습니다. |
| 08 Spec Explorer | PLAN 아래 TASK·FINDING 탐색 | 탐색 뒤에 문서 배치 | 긴 계획·검증 기록. 깊은 계층은 접어야 합니다. |
| 09 Dependency Lens | 선행 TASK와 후속 TASK의 연결 | 위에서 아래로 조건 읽기 | 막힘 원인 분석. 그래프 배치는 별도 구현이 필요합니다. |
| 10 Quiet Outline | 짧은 개요 + 작업 목록 + 접힌 기록 | 단일 열의 점진적 공개 | 읽기·키보드 중심. 병렬 비교에는 보조 보기가 필요합니다. |

통합안은 **01 + 03을 Workspace의 두 페이지로 묶고**, 검색에는 05, 기억에는 06, 레코드 탐색에는 08의 정보 구조를 적용합니다. 열 가지 화면 전체를 제품의 보기 옵션으로 추가하지 않습니다. 09의 의존성 보기는 후속 선택 사항입니다.

## DaisyUI 컴포넌트 활용

| 책임 | 컴포넌트 | 조합 원칙 |
| --- | --- | --- |
| 작업 공간·RUN 탐색 | `menu`, `dropdown`, `tabs` | 위치·출처를 항상 식별하고 탭 선택·방향키 동작을 보존합니다. |
| TASK 요약·목록 | `table`, v5 `list` / `list-row`, `card` | 넓은 화면은 표, 좁은 화면은 목록을 사용합니다. 모든 행을 카드로 만들지 않습니다. |
| 상태·진척 | `badge`, v5 `status`, `progress`, `steps` | 색과 텍스트를 함께 사용합니다. Skipped 등 실제 상태를 표시하고 TASK 완료 비율을 성공 판정으로 해석하지 않습니다. |
| 검색·필터 | `input`, `select`, `join`, v5 `fieldset` | 입력 레이블과 선택 상태를 명시합니다. 핵심 기능을 tooltip에만 두지 않습니다. |
| 상세·긴 기록 | `collapse`, `modal`, `tabs` | 원문·추가 필드를 필요할 때 펼치고 포커스 복귀·Escape를 지원합니다. |
| 이벤트·피드백 | `timeline`, `alert`, `skeleton`, `loading` | 새 데이터, 로딩, 빈 상태, 오류와 오래된 데이터를 구분합니다. |

기본 컴포넌트를 더 많이 넣는 것이 목표는 아닙니다. [공식 컴포넌트](https://daisyui.com/components/)의 구조·상태·크기를 사용하고, 제품 고유 CSS는 배치·밀도·토큰 연결에 집중합니다. 의존성 그래프는 DaisyUI 기본 기능으로 제공되지 않으므로 별도 배치·키보드 탐색 책임을 둡니다.

## 단계별 리팩토링 계획

### 1. 회귀 기준과 버전 전환

현재 제품은 DaisyUI 4.12.24 / Tailwind CSS 3.4.17 / React 18.3.1 / Vite 5.4.20입니다. 먼저 현재 화면과 host 프로토콜의 fixture를 기준으로 남기고, **DaisyUI 5 + Tailwind CSS 4 전환**을 정보 구조 변경과 분리해 검증합니다. 실제 적용 시 선택한 패치 버전을 lockfile에 고정합니다. 갤러리의 빌드가 제품 마이그레이션을 검증한 것은 아닙니다.

1. 기존 DaisyUI plugin 설정을 분리하고 Tailwind 4의 CSS 진입점·`@plugin "daisyui"`로 이동합니다. v4의 JS 설정을 그대로 복사하지 않습니다.
2. Vite·Node·Tailwind plugin의 호환 범위를 확인합니다. `@tailwindcss/vite`를 우선 검토하고, 호환성 때문에 PostCSS 경로를 유지하면 `@tailwindcss/postcss`를 사용합니다. 두 경로를 동시에 적용하지 않습니다. Vite major 변경이 필요하면 별도 diff로 검증합니다.
3. `@tailwind` 진입점을 `@import "tailwindcss"`로 변경합니다. JS 설정·테마·`@apply`·동적 상태 클래스의 생성 결과를 확인합니다.
4. `tabs-boxed` → `tabs-box`, `card-bordered` → `card-border`, `card-compact` → `card-sm`, menu `active` → `menu-active`, 제거된 `input-bordered`·form label 클래스를 현재 사용처에 맞게 바꿉니다.
5. v4 테마 값을 v5 의미 색상·radius·size 토큰으로 옮깁니다. `--vscode-*`는 유효한 CSS 색상으로 직접 연결하고, 이전 색상 형식의 변환을 그대로 재사용하지 않습니다.
6. `github-markdown-css`, Tailwind preflight, VS Code 고대비와 focus 스타일의 충돌을 확인합니다. 외부 CDN·폰트·스크립트 없이 로컬 자산을 패키징하고 브라우저 자산 동기화를 유지합니다.

[DaisyUI 업그레이드 가이드](https://daisyui.com/docs/upgrade/)와 [Tailwind 업그레이드 가이드](https://tailwindcss.com/docs/upgrade-guide)를 기준으로 합니다. Tailwind 자동 업그레이드 도구는 Node.js 20 이상이 필요합니다. 공식 v4 기준 브라우저 범위는 Safari 16.4+, Chrome 111+, Firefox 128+이며, 선택한 패치 버전의 추가 CSS 사용과 지원 최저 VS Code의 실제 Chromium에서 함께 확인해야 합니다. 확인 없이 확장의 최소 버전을 높이지 않습니다.

### 2. 공유 UI의 책임 분리

다음은 새로 만들 모듈의 제안이며 현재 존재하는 API가 아닙니다.

| 경계 | 책임 |
| --- | --- |
| `model/` | RUN·TASK·의존성·출처·권한의 읽기 모델과 정렬·필터 |
| `transport/` | 브라우저 polling / VS Code message 어댑터, 취소·오류·최신성 |
| `components/` | `RunIdentity`, `StatusBadge`, `TaskList`, `TaskDetail`, `RecordContent`, `EmptyState` |
| `views/` | Overview, Records, Memory, Workspace, Debug 화면 조합 |
| `theme/` | 브라우저와 VS Code 토큰 어댑터·밀도·대비 |

하나의 작업 정보를 두 표면에서 중복 구현하지 않습니다. 먼저 기존 화면 그대로 경계를 나눈 뒤 선택한 시안의 배치를 적용합니다. `auto/small/medium/large`, 한국어·영어, 사용자 필드·Markdown·실행 시간·batch/execution 정보도 유지합니다.

### 3. 선택한 UX 적용

- RUN 식별·작업 목적·현재 TASK·막힘을 상단에 배치합니다. 지표는 핵심 두세 개 이내로 선택하고 Debug·원문·추가 필드는 상세로 이동합니다.
- 목록에서 선택한 TASK의 목적·담당·선행 조건·검증·결과를 일관된 상세 컴포넌트로 읽습니다.
- 폭을 기준으로 재배치합니다. 좁은 확장은 현재 작업 우선, 중간 폭은 단일 목록, 넓은 화면은 목록과 상세의 병렬 배치를 검토합니다. 고정 viewport 폭 대신 webview 컨테이너 폭을 사용합니다.
- 여러 RUN의 `(source_db, id)` 식별, 세션 소유권과 capability를 유지합니다. 기록 조회와 실행 권한을 혼합하지 않습니다.
- 새로고침 시 선택·펼침·입력·스크롤·포커스를 보존합니다. 빈 RUN·로딩·연결 오류·오래된 데이터 상태를 설계합니다.
- RUN 폐기는 기존 capability와 정확한 ID 확인을 보존합니다. 이번 갤러리는 폐기를 구현하지 않습니다.

### 4. 검증 후 적용

후속 제품 구현의 완료 기준입니다.

- 브라우저와 VS Code 실제 webview에서 밝음·어두움·고대비, 좁은 컨테이너, 긴 한국어·영어·Markdown을 확인합니다.
- RUN 없음·다중 RUN·peer 이력·다수 TASK·모든 TASK 상태·병렬 batch·오류·갱신 중 상세 열기에서 정보가 유실되지 않아야 합니다.
- RUN 탭 키보드 조작, 선택한 TASK, 대화상자 focus·Escape, 자동 갱신 후 스크롤과 focus를 검증합니다. 색만으로 상태를 전달하지 않고 본문 대비 4.5:1을 목표로 합니다.
- 기존 CLI·MCP 인자·설정 기본값·읽기 전용 동작은 유지합니다. 추가·변경이 필요하면 별도 사용자 동작으로 검토하고 양언어 사용 가이드를 함께 바꿉니다.
- 기본 화면에서 현재 작업·막힘·출처를 쉽게 찾는지 짧은 사용성 확인을 합니다. 개선 수치는 실제 측정 후에만 보고합니다.

```sh
npm --prefix vscode-extension run compile
npm --prefix vscode-extension run test:host
uv --directory tapl run --extra test python -m pytest -q tests/test_viewer.py tests/test_viewer_native.py tests/test_viewer_discard.py tests/test_viewer_readonly.py tests/test_viewer_sources.py tests/test_run_discard.py
git diff --check
```

명령은 후속 제품 리팩토링용입니다. 관련 session·readonly·recall 테스트와 실제 webview 확인도 변경 경계에 따라 실행합니다. 검증 실패 시 이전 빌드·lockfile·공유 자산으로 되돌릴 수 있도록 버전 전환과 UI 변경을 분리해 커밋합니다.

## 갤러리 유지보수

저장소 루트에서 실행합니다. 생성된 `components.css`가 포함되어 있어 열람 시 설치가 필요 없습니다. 통합안도 이 로컬 CSS를 공유하며 `build`와 `check`가 두 시안을 함께 다룹니다.

```sh
npm --prefix docs/design/viewer-concepts ci
npm --prefix docs/design/viewer-concepts run build
npm --prefix docs/design/viewer-concepts run check
python3 -m http.server 8767 --bind 127.0.0.1 --directory .
```

서버를 사용하면 `http://127.0.0.1:8767/docs/design/viewer-concepts/`에서 엽니다. `index.html`을 직접 여는 방법도 지원합니다. `components.source.css`·`concepts.js`·`lab.css`가 편집 원본입니다. 화면 내용은 한국어이며 영문·국문 가이드는 같은 갤러리를 가리킵니다.

통합안은 `http://127.0.0.1:8767/docs/design/viewer-workbench/`에서 열며 `viewer-workbench/index.html`·`workbench.js`·`workbench.css`가 편집 원본입니다. 한국어·영어는 시안 상단에서 전환합니다.

현재 고정 버전의 minify 빌드는 DaisyUI `join`의 `@scope` 내부 선택자에 대해 최적화 경고 2건을 출력합니다. 생성은 성공하며 갤러리에는 별도의 명시적 focus 경계가 있습니다. 제품 업그레이드에서는 이 경고와 지원 최저 webview의 선택자·포커스 렌더링을 다시 확인해야 합니다.

갤러리는 임시 프로필의 헤드리스 Chrome에서 320·390·640·1024·1600px × 10종 × 밝음·어두움 × 3개 표면 조합 300개, 추가 상태 30개를 확인했습니다. 이 범위에서 페이지·제품 영역의 가로 넘침, 스크립트 오류와 외부 요청은 없었고 필터·검색·상세·문서 선택·포커스 복귀를 확인했습니다. 대표 화면은 육안으로도 검토했습니다. 실제 VS Code webview·고대비·스크린리더·사용성 검증을 대신하지 않습니다.

관련 문서: [구조](architecture.ko.md) · [기여와 검증](contributing.ko.md) · [Viewer](../guides/viewer.ko.md) · [확장](../guides/vscode.ko.md) · [문서 홈](../README.ko.md)
