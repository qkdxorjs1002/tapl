/* Synthetic data only. No transport, network, workflow writes or host API. */
"use strict";

const concepts = [
  {
    id: "01",
    name: "Signal Desk",
    ko: "작업 중심",
    tag: "RECOMMENDED / EVERYDAY WORK",
    accent: "green",
    description: "목록과 상세를 나란히. 현재 작업과 막힘을 한눈에 확인합니다.",
    strength:
      "일상적인 RUN 확인과 작업 상세 탐색의 균형이 좋습니다. 제품의 기본 화면으로 추천합니다.",
    tradeoff:
      "넓은 화면의 상세 패널은 좁은 확장에서 대화상자로 전환해야 합니다.",
    components: ["menu", "table", "badge", "status", "progress", "modal"],
  },
  {
    id: "02",
    name: "Flow Board",
    ko: "상태 중심",
    tag: "STATE FIRST / KANBAN",
    accent: "blue",
    description: "대기·진행·막힘·완료를 레인으로 나누어 흐름을 읽습니다.",
    strength:
      "병렬 작업과 정체된 항목을 빠르게 비교합니다. 상태별 탐색이 많은 경우에 적합합니다.",
    tradeoff:
      "작업 수가 많으면 세로 길이가 늘어납니다. 확장에서는 상태를 고르고 한 레인씩 읽습니다.",
    components: ["card", "badge", "join", "status", "modal"],
  },
  {
    id: "03",
    name: "Focus Now",
    ko: "현재에 집중",
    tag: "RECOMMENDED / EXTENSION",
    accent: "green",
    description: "지금 진행 중인 작업 하나와 다음 판단에 화면을 할당합니다.",
    strength:
      "코딩 중 짧게 확인하는 확장 화면에 추천합니다. 작업의 목적과 검증 조건을 먼저 보여줍니다.",
    tradeoff:
      "여러 작업을 한 번에 비교할 때는 목록이나 보드로 이동해야 합니다.",
    components: ["steps", "card", "alert", "list", "progress"],
  },
  {
    id: "04",
    name: "Evidence Stream",
    ko: "시간의 흐름",
    tag: "CHRONOLOGICAL / ACTIVITY",
    accent: "violet",
    description: "어떤 판단 뒤에 어떤 작업이 시작됐는지 시간순으로 추적합니다.",
    strength:
      "재개·디버깅·회고에서 맥락을 복구하기 좋습니다. 이벤트와 근거 기록을 연결합니다.",
    tradeoff:
      "이벤트 순서는 작업 의존성을 대신하지 않습니다. 실제 기록에 존재하는 시각만 표시해야 합니다.",
    components: ["timeline", "status", "badge", "alert", "modal"],
  },
  {
    id: "05",
    name: "Record Library",
    ko: "기록 찾기",
    tag: "SEARCH FIRST / ARCHIVES",
    accent: "amber",
    description: "검색 결과와 원문을 함께 두어 기록을 오가며 읽습니다.",
    strength: "PLAN·TASK·FINDING과 아카이브에서 근거를 찾는 작업에 적합합니다.",
    tradeoff:
      "실시간 실행 상태의 주목도는 낮습니다. 현재 RUN 화면으로 돌아가는 경로가 필요합니다.",
    components: ["input", "join", "menu", "badge", "card"],
  },
  {
    id: "06",
    name: "Memory Garden",
    ko: "기억과 근거",
    tag: "KNOWLEDGE / ASSOCIATIVE MEMORY",
    accent: "green",
    description: "교훈·검색 단서·원문 출처를 하나의 읽기 단위로 묶습니다.",
    strength:
      "연상 기억의 재사용성과 출처 확인을 강화합니다. 기억 페이지의 전용 레이아웃으로 적합합니다.",
    tradeoff:
      "카드 제목과 단서가 길면 밀도가 떨어집니다. 원문은 필요할 때만 펼쳐야 합니다.",
    components: ["card", "badge", "input", "fieldset", "modal"],
  },
  {
    id: "07",
    name: "Run Atlas",
    ko: "여러 RUN",
    tag: "MULTI RUN / WORKSPACE",
    accent: "blue",
    description: "동시 작업의 소유자와 출처를 드러내고 RUN 단위로 이동합니다.",
    strength:
      "여러 세션이나 공유 이력의 상태를 비교하기 좋습니다. 로컬과 다른 소유자의 경계를 분명히 합니다.",
    tradeoff:
      "한 RUN만 사용할 때는 탐색 비용이 늘어납니다. 기본 화면보다 작업 공간 선택에 적합합니다.",
    components: ["card", "progress", "badge", "status", "join"],
  },
  {
    id: "08",
    name: "Spec Explorer",
    ko: "계획과 문서",
    tag: "STRUCTURE FIRST / RECORDS",
    accent: "violet",
    description:
      "PLAN 아래 TASK와 FINDING을 배치해 계획과 실행의 연결을 읽습니다.",
    strength:
      "요구사항·결과·검증 기록을 문서처럼 검토합니다. 긴 기록과 사용자 필드에 적합합니다.",
    tradeoff:
      "깊은 트리는 좁은 화면에서 복잡해집니다. 확장에서는 탐색 영역을 접어야 합니다.",
    components: ["menu", "collapse", "join", "breadcrumbs", "badge"],
  },
  {
    id: "09",
    name: "Dependency Lens",
    ko: "막힘과 의존성",
    tag: "CAUSAL / DEPENDENCIES",
    accent: "amber",
    description: "다음 작업이 무엇을 기다리는지 선행 조건으로 설명합니다.",
    strength:
      "TASK 의존성과 막힘의 전파를 이해하기 좋습니다. 보드의 보조 보기로 추천합니다.",
    tradeoff:
      "큰 그래프는 복잡해집니다. DAG 배치는 별도 책임이며 DaisyUI는 노드와 상세 UI에 사용합니다.",
    components: ["card", "status", "alert", "badge", "modal"],
  },
  {
    id: "10",
    name: "Quiet Outline",
    ko: "차분한 개요",
    tag: "MINIMAL / PROGRESSIVE DISCLOSURE",
    accent: "green",
    description: "숫자 카드와 장식을 줄이고 필요한 문서만 순서대로 펼칩니다.",
    strength:
      "읽기와 키보드 탐색에 집중합니다. 화면이 좁거나 자주 열어 보는 경우에 편안합니다.",
    tradeoff: "병렬 실행과 여러 RUN의 비교는 다른 보기에 맡겨야 합니다.",
    components: ["collapse", "list", "status", "progress", "badge"],
  },
];

const tasks = [
  {
    id: "TASK-001",
    title: "현재 화면과 동작 조사",
    status: "done",
    owner: "Main",
    goal: "기존 동작과 회귀 경계를 확인한다.",
    depends: [],
    result: "공유 React UI와 테마·CSP 경계를 확인했습니다.",
  },
  {
    id: "TASK-002",
    title: "DaisyUI 5 빌드 전환",
    status: "done",
    owner: "Main",
    goal: "Tailwind 4와 DaisyUI 5의 로컬 빌드 경로를 마련한다.",
    depends: ["TASK-001"],
    result: "예시 프로젝트의 로컬 스타일 생성이 완료되었습니다.",
  },
  {
    id: "TASK-003",
    title: "공통 컴포넌트 정리",
    status: "running",
    owner: "Agent A",
    goal: "RUN·TASK·상태 표현을 공통 컴포넌트로 정리한다.",
    depends: ["TASK-002"],
    result: "목록과 상세 패널의 책임을 나누고 있습니다.",
  },
  {
    id: "TASK-004",
    title: "VS Code 테마 연결",
    status: "blocked",
    owner: "Agent B",
    goal: "편집기 색상과 DaisyUI 의미 토큰을 연결한다.",
    depends: ["TASK-002"],
    result: "고대비 테마에서 포커스 경계 확인을 기다립니다.",
  },
  {
    id: "TASK-005",
    title: "반응형·접근성 검증",
    status: "pending",
    owner: "Main",
    goal: "좁은 확장과 브라우저에서 읽기·탐색을 확인한다.",
    depends: ["TASK-003", "TASK-004"],
    result: "두 선행 작업이 완료되면 검증합니다.",
  },
  {
    id: "TASK-006",
    title: "사용 가이드 정리",
    status: "pending",
    owner: "Main",
    goal: "실제 구현된 화면과 문서의 설명을 일치시킨다.",
    depends: ["TASK-005"],
    result: "검증 결과를 확인한 뒤 문서를 정리합니다.",
  },
];
const statusInfo = {
  pending: { text: "대기", en: "Pending", color: "status-neutral", glyph: "○" },
  running: {
    text: "진행 중",
    en: "In Progress",
    color: "status-primary",
    glyph: "◐",
  },
  blocked: { text: "막힘", en: "Blocked", color: "status-warning", glyph: "!" },
  done: { text: "완료", en: "Completed", color: "status-success", glyph: "✓" },
};
const records = [
  {
    id: "PLAN-001",
    type: "PLAN",
    title: "Viewer 경험 개선",
    summary: "현재 작업과 막힘이 먼저 보이는 읽기 전용 화면을 설계합니다.",
    detail:
      "DaisyUI 5의 의미 토큰을 기반으로 공통 표현을 정리하고, 브라우저와 VS Code 확장에서 같은 데이터가 자연스럽게 배치되도록 합니다.",
    date: "2026.11.10",
    source: "local / design-study",
  },
  {
    id: "FINDING-001",
    type: "FINDING",
    title: "테마와 컴포넌트 경계",
    summary: "테마 값과 컴포넌트의 구조를 분리합니다.",
    detail:
      "색상은 VS Code 의미 변수와 브라우저 테마에서 공급합니다. 개별 버튼·배지의 전역 CSS 덮어쓰기는 최소화합니다.",
    date: "2026.11.10",
    source: "local / design-study",
  },
  {
    id: "TASK-003",
    type: "TASK",
    title: "공통 컴포넌트 정리",
    summary: "목록·상태·상세 표현을 공통화합니다.",
    detail:
      "StatusBadge, TaskList, TaskDetail과 같은 읽기 단위를 분리합니다. 현재 화면의 명령 프로토콜은 어댑터에 유지합니다.",
    date: "2026.11.10",
    source: "local / design-study",
  },
  {
    id: "PLAN-014",
    type: "PLAN",
    title: "검색 흐름 정리",
    summary: "결과와 원문을 함께 읽는 검색 화면입니다.",
    detail:
      "이 기록은 아카이브 탐색을 보여주는 가상 예시입니다. 출처와 안정 ID를 제목 옆에서 확인할 수 있습니다.",
    date: "2026.11.09",
    source: "archive / sample-history",
  },
];
const memories = [
  {
    id: "MEM-001",
    title: "화면과 데이터 경계를 분리하기",
    text: "갱신 방식이 달라도 같은 읽기 모델을 사용하면 화면을 일관되게 유지할 수 있습니다.",
    cues: ["shared-ui", "transport", "refresh"],
    source: "PLAN-001",
    topic: "구조",
  },
  {
    id: "MEM-002",
    title: "테마는 의미 토큰에서 시작하기",
    text: "색상 값보다 역할을 먼저 정의하고, VS Code 변수와 브라우저 테마를 연결합니다.",
    cues: ["vscode-theme", "tokens", "contrast"],
    source: "FINDING-001",
    topic: "디자인",
  },
  {
    id: "MEM-003",
    title: "읽기 전용 경계를 드러내기",
    text: "탐색·필터와 실행 명령을 구분해 Viewer에서 할 수 있는 일을 분명하게 안내합니다.",
    cues: ["read-only", "capability", "run-owner"],
    source: "PLAN-001",
    topic: "동작",
  },
  {
    id: "MEM-004",
    title: "좁은 폭에서는 순서 바꾸기",
    text: "레이아웃을 축소하는 대신 현재 작업·막힘·상세의 우선순위로 다시 배치합니다.",
    cues: ["extension", "container", "focus"],
    source: "TASK-003",
    topic: "디자인",
  },
];
const events = [
  {
    time: "14:32",
    title: "테마 확인에서 막힘 발견",
    text: "TASK-004 · 고대비 포커스 경계 확인 대기",
    kind: "blocked",
    task: "TASK-004",
  },
  {
    time: "14:28",
    title: "공통 컴포넌트 정리 시작",
    text: "TASK-003 · Agent A가 상태와 상세 표현 분리",
    kind: "running",
    task: "TASK-003",
  },
  {
    time: "14:23",
    title: "빌드 전환 검증 완료",
    text: "TASK-002 · 로컬 CSS 생성 확인",
    kind: "done",
    task: "TASK-002",
  },
  {
    time: "14:18",
    title: "계획에 따라 실행 시작",
    text: "PLAN-001 · 실행 승인 기록 있음 (가상 예시)",
    kind: "done",
    task: "TASK-001",
  },
  {
    time: "14:10",
    title: "Viewer 경험 개선 계획 작성",
    text: "현재 작업과 막힘을 우선하는 공유 UI",
    kind: "done",
    task: "TASK-001",
  },
];
const iconPaths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  book: '<path d="M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4zM12 5v15"/>',
  archive: '<path d="M4 8h16v12H4zM3 3h18v5H3zM9 12h6"/>',
  refresh: '<path d="M20 10a8 8 0 1 0-2 8M20 3v7h-7"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
  alert: '<path d="m12 3 10 18H2zM12 9v5M12 17h.01"/>',
  arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
  folder: '<path d="M3 7V5h7l2 3h9v12H3z"/>',
  file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6"/>',
  branch:
    '<circle cx="6" cy="5" r="2"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="5" r="2"/><path d="M6 7v10M18 7v3a4 4 0 0 1-4 4H6"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  inbox: '<path d="m5 4-3 11v5h20v-5L19 4zM2 15h6l2 3h4l2-3h6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  code: '<path d="m8 6-6 6 6 6M16 6l6 6-6 6M14 3l-4 18"/>',
};
function icon(name) {
  return `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24">${iconPaths[name] || iconPaths.file}</svg>`;
}
function esc(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
const state = {
  concept: "01",
  surface: "pair",
  color: "light",
  screen: "ready",
  overview: false,
  filter: "all",
  query: "",
  selected: "TASK-003",
  record: 0,
  section: "current",
  documentTab: "goal",
  documentEntity: "task",
  memoryQuery: "",
};
const $ = (selector, parent = document) => parent.querySelector(selector);
function currentConcept() {
  return concepts.find((c) => c.id === state.concept) || concepts[0];
}
function selectedTask() {
  return tasks.find((t) => t.id === state.selected) || tasks[2];
}
function mark(status, withLabel = true) {
  const s = statusInfo[status];
  return `<span class="status-mark"><span class="status ${s.color}" aria-hidden="true"></span>${withLabel ? s.text : `<span class="sr-only">${s.text}</span>`}</span>`;
}
function badge(text, color = "") {
  return `<span class="badge badge-sm ${color}">${esc(text)}</span>`;
}
function taskButton(task, extra = "") {
  return `<button type="button" class="task-open ${extra}" data-task="${task.id}"><strong>${esc(task.title)}</strong><span class="task-id">${task.id}</span></button>`;
}
function filteredTasks() {
  const q = state.query.trim().toLocaleLowerCase();
  return tasks.filter(
    (t) =>
      (state.filter === "all" || t.status === state.filter) &&
      (!q || `${t.id} ${t.title} ${t.owner}`.toLocaleLowerCase().includes(q)),
  );
}
function sectionHeading(title, meta = "") {
  return `<div class="section-heading"><h4>${title}</h4>${meta ? `<span class="muted micro">${meta}</span>` : ""}</div>`;
}
function runHeading(
  title = "Viewer 경험 개선",
  subtitle = "PLAN-001 · 화면 구조와 공통 컴포넌트 정리",
  withFacts = true,
) {
  return `<div class="run-caption"><span class="mono">LOCAL / RUN-024</span><span>·</span><span>이 세션</span><span>·</span><span>가상 예시</span></div><div class="run-heading"><div><h3>${title}</h3><p>${subtitle}</p></div>${badge("진행 중", "badge-soft badge-primary")}</div>${withFacts ? '<div class="run-facts"><span>완료 <strong>2 / 6</strong></span><progress class="progress progress-primary" value="2" max="6" aria-label="예시 작업 완료 2/6"></progress><span>진행 1 · 막힘 1 · 대기 2</span></div>' : ""}`;
}
function alertBlock() {
  return `<div class="quiet-alert">${icon("alert")}<div><strong>테마 확인이 후속 검증을 막고 있습니다</strong><p>TASK-004 · 고대비 포커스 경계 확인 대기</p><button class="btn btn-link btn-xs" type="button" data-task="TASK-004">막힘 근거 보기 ${icon("arrow")}</button></div></div>`;
}
function filters(withSearch = false) {
  return `<div class="p-filter"><div class="join" role="group" aria-label="작업 상태 필터">${[
    ["all", "전체"],
    ["running", "진행"],
    ["blocked", "막힘"],
    ["pending", "대기"],
    ["done", "완료"],
  ]
    .map(
      ([key, text]) =>
        `<button type="button" data-filter="${key}" class="btn btn-xs join-item ${state.filter === key ? "btn-primary" : "btn-ghost"}" aria-pressed="${state.filter === key}">${text}</button>`,
    )
    .join(
      "",
    )}</div>${withSearch ? `<form class="task-search" data-search-form="tasks"><label><span class="sr-only">작업 검색</span><input class="input input-sm" name="query" placeholder="작업 검색 후 Enter" value="${esc(state.query)}" aria-label="작업 검색"></label></form>` : ""}</div>`;
}
function noMatches() {
  return '<div class="quiet-alert"><div><strong>일치하는 작업이 없습니다</strong><p>검색어나 상태 필터를 바꿔 보세요.</p><button type="button" class="btn btn-xs" data-reset-filters>필터 초기화</button></div></div>';
}
function taskList(items = filteredTasks()) {
  if (!items.length) return noMatches();
  return `<ul class="task-list list">${items.map((t) => `<li><button type="button" class="task-list-button ${state.selected === t.id ? "is-selected" : ""}" data-task="${t.id}"><span class="status ${statusInfo[t.status].color}" aria-hidden="true"></span><span class="task-copy"><span class="task-id">${t.id}</span><strong>${esc(t.title)}</strong><span class="micro muted">${esc(t.owner)} · ${statusInfo[t.status].text}</span></span><span class="muted" aria-hidden="true">↗</span></button></li>`).join("")}</ul>`;
}
function taskTable(items = filteredTasks()) {
  if (!items.length) return noMatches();
  return `<table class="table task-table"><caption class="sr-only">가상 예시 작업 목록</caption><thead><tr><th scope="col"><span class="sr-only">상태 표시</span></th><th scope="col">작업</th><th scope="col">담당</th><th scope="col">상태</th></tr></thead><tbody>${items.map((t) => `<tr class="task-row ${state.selected === t.id ? "is-selected" : ""}"><td><span aria-hidden="true">${statusInfo[t.status].glyph}</span></td><td>${taskButton(t)}</td><td>${t.owner}</td><td>${mark(t.status)}</td></tr>`).join("")}</tbody></table>`;
}
function inspector() {
  const t = selectedTask();
  return `<aside class="inspector"><p class="section-eyebrow">SELECTED TASK</p><span class="mono micro muted">${t.id}</span><h4>${t.title}</h4>${mark(t.status)}<dl><div><dt>목적</dt><dd>${t.goal}</dd></div><div><dt>담당</dt><dd>${t.owner}</dd></div><div><dt>선행 조건</dt><dd>${t.depends.join(", ") || "없음"}</dd></div></dl><p>${t.result}</p><button type="button" class="btn btn-sm" data-task="${t.id}">상세 읽기 ${icon("arrow")}</button></aside>`;
}

function signalDesk(ext) {
  return `${runHeading()}${alertBlock()}${filters()}${sectionHeading("작업 목록", "안정 ID 순서")}<div class="split-inspector"><div>${ext ? taskList() : taskTable()}</div>${ext ? "" : inspector()}</div>`;
}
function flowBoard(ext) {
  const items = filteredTasks();
  const lanes = ["pending", "running", "blocked", "done"].filter((key) =>
    !ext || state.filter === "all" ? true : key === state.filter,
  );
  return `${runHeading("작업의 흐름", "RUN-024 · 상태별 읽기 전용 보드")}${filters()}${
    !items.length
      ? noMatches()
      : `<div class="kanban">${lanes
          .map(
            (key) =>
              `<section class="kanban-lane"><h4 class="lane-title">${mark(key)}${badge(items.filter((t) => t.status === key).length)}</h4>${
                items
                  .filter((t) => t.status === key)
                  .map(
                    (t) =>
                      `<article class="card task-card"><div class="mono micro muted">${t.id}</div>${taskButton(t)}<div class="task-card-foot"><span>${t.owner}</span><span>${t.depends.length ? `선행 ${t.depends.length}` : "시작점"}</span></div></article>`,
                  )
                  .join("") || '<p class="micro muted">이 상태의 작업 없음</p>'
              }</section>`,
          )
          .join("")}</div>`
  }<p class="micro muted" style="margin-top:14px">상태는 Agent 실행 기록을 따릅니다. 카드는 상세 탐색만 제공합니다.</p>`;
}
function focusNow(ext) {
  const t = tasks[2];
  return `${runHeading("지금, 이 작업", "RUN-024 · 현재 실행의 목적과 다음 판단", false)}<ul class="steps phase-steps" aria-label="예시 실행 단계"><li class="step step-primary">계획</li><li class="step step-primary">승인</li><li class="step step-primary">실행</li><li class="step">검증</li></ul><div class="focus-layout"><div><article class="focus-card"><div class="focus-label">IN FOCUS / ${t.id}</div><h3>공통 컴포넌트를<br>정리하고 있습니다.</h3><p>상태와 작업 상세를 공통 표현으로 나누어<br>Viewer와 확장의 경험을 연결합니다.</p><div class="run-facts"><span>${mark("running")}</span><span>Agent A</span></div><button class="btn btn-primary btn-sm" type="button" data-task="TASK-003">목적과 검증 조건 ${icon("arrow")}</button></article>${alertBlock()}</div><aside><div class="section-eyebrow">UP NEXT</div>${sectionHeading("이어지는 작업", "선행 조건 대기")}${taskList(tasks.slice(4))}<div class="queue-block">${sectionHeading("완료한 일", "2개")}${taskList(tasks.slice(0, 2))}</div></aside></div>`;
}
function evidenceStream(ext) {
  return `${runHeading("판단과 실행의 기록", "RUN-024 · 2026.11.10 · 모든 시각은 가상 예시", false)}<div class="event-layout"><div>${sectionHeading("최근 활동", "최신순")}<ol class="event-feed timeline timeline-vertical">${events.map((e, index) => `<li class="event-item"><time class="event-time timeline-start">${e.time}</time><span class="event-axis timeline-middle"><span class="status ${statusInfo[e.kind].color}" aria-hidden="true"></span></span><div class="event-copy timeline-end ${index === 0 ? "event-current" : ""}"><h4>${e.title}</h4><p>${e.text}</p><button class="btn btn-ghost btn-xs" type="button" data-task="${e.task}">근거 열기 ${icon("arrow")}</button></div></li>`).join("")}</ol></div><aside class="event-aside">${inspector()}${ext ? "" : '<p class="micro muted" style="margin-top:12px">이벤트는 실행 기록의 순서입니다. 작업 의존성은 개별 TASK에서 확인합니다.</p>'}</aside></div>`;
}
function recordDocument(record, ext = false) {
  return `<article class="document-paper">${badge(record.type, "badge-outline")}<span class="mono micro muted">${record.id}</span><h3>${record.title}</h3><p>${record.detail}</p><hr><h4>검토할 내용</h4><ul><li>현재 작업과 막힘이 첫 화면에 나타나는가?</li><li>좁은 확장에서도 안정 ID와 상태를 읽을 수 있는가?</li><li>자동 갱신 뒤 선택과 포커스를 유지하는가?</li></ul><h4>기록 출처</h4><p><code>${record.source}</code><br>${record.date} · 가상 기록</p><button type="button" class="btn btn-sm" style="margin-top:15px" data-record-detail="${records.indexOf(record)}">${ext ? "전체 기록 읽기" : "원문과 관련 기록"} ${icon("arrow")}</button></article>`;
}
function recordLibrary(ext) {
  const q = state.query.trim().toLocaleLowerCase();
  const found = records.filter(
    (r) =>
      !q ||
      `${r.id} ${r.title} ${r.type} ${r.detail}`
        .toLocaleLowerCase()
        .includes(q),
  );
  const selected =
    found.find((r) => records.indexOf(r) === state.record) || found[0];
  return `${runHeading("기록 라이브러리", "PLAN · TASK · FINDING · 아카이브", false)}<form data-search-form="records"><label class="input input-sm">${icon("search")}<input name="query" placeholder="기록 검색 후 Enter" aria-label="기록 검색" value="${esc(state.query)}"></label></form>${sectionHeading("검색 결과", `${found.length}개 · 예시 기록`)}${!found.length ? noMatches() : `<div class="record-layout"><ul class="record-results">${found.map((r) => `<li><button type="button" class="record-result ${selected === r ? "is-selected" : ""}" aria-pressed="${selected === r}" data-record="${records.indexOf(r)}"><span class="mono micro muted">${r.type} / ${r.id}</span><strong>${r.title}</strong><p>${r.summary}</p><p style="margin-top:8px">${r.date}</p></button></li>`).join("")}</ul>${selected ? recordDocument(selected, ext) : ""}</div>`}`;
}
function memoryGarden() {
  const q = state.memoryQuery.trim().toLocaleLowerCase();
  const found = memories.filter(
    (m) =>
      !q ||
      `${m.title} ${m.cues.join(" ")} ${m.text}`
        .toLocaleLowerCase()
        .includes(q),
  );
  return `${runHeading("다음 작업에 남는 기억", "재사용할 교훈과 확인 가능한 출처", false)}<form data-search-form="memories"><fieldset class="fieldset"><legend class="fieldset-legend">교훈 또는 검색 단서</legend><label class="input input-sm">${icon("search")}<input name="query" placeholder="예: theme, extension" aria-label="기억 검색" value="${esc(state.memoryQuery)}"></label></fieldset></form>${sectionHeading("연상 기억", `${found.length}개 · 가상 예시`)}${found.length ? `<div class="memory-grid">${found.map((m) => `<article class="card memory-card"><div class="run-card-head">${badge(m.topic, "badge-outline")}<span class="mono micro muted">${m.id}</span></div><h4>${m.title}</h4><p>${m.text}</p><div class="cue-list">${m.cues.map((cue) => `<span>${cue}</span>`).join("")}</div><div class="memory-card-foot"><span>${m.source}</span><button type="button" class="btn btn-ghost btn-xs" data-memory="${m.id}">출처 읽기 ${icon("arrow")}</button></div></article>`).join("")}</div>` : '<div class="quiet-alert"><div><strong>일치하는 기억이 없습니다</strong><button class="btn btn-xs" type="button" data-reset-filters>검색 초기화</button></div></div>'}<p class="micro muted" style="margin-top:15px">기억과 원문은 읽기 전용으로 탐색합니다.</p>`;
}
function runAtlas() {
  const runs = [
    {
      id: "RUN-024",
      title: "Viewer 경험 개선",
      summary: "화면 구조와 공통 컴포넌트",
      own: "이 세션",
      source: "local",
      completed: 2,
      total: 6,
      kind: "running",
    },
    {
      id: "RUN-023",
      title: "Claude 연결 확인",
      summary: "통합 동작과 문서 점검",
      own: "다른 세션",
      source: "local",
      completed: 3,
      total: 5,
      kind: "running",
    },
    {
      id: "RUN-019",
      title: "검색 경험 정리",
      summary: "검색 결과와 기록 상세 연결",
      own: "공유 이력",
      source: "peer-history",
      completed: 4,
      total: 4,
      kind: "done",
    },
    {
      id: "RUN-018",
      title: "설치 가이드 검토",
      summary: "플랫폼별 빠른 시작",
      own: "아카이브",
      source: "archive",
      completed: 3,
      total: 3,
      kind: "done",
    },
  ];
  return `${runHeading("작업 공간의 흐름", "personal / tapl · 현재와 공유 이력의 경계", false)}<div class="quiet-alert">${icon("lock")}<div><strong>소유자와 출처를 먼저 확인합니다</strong><p>다른 세션과 공유 이력은 읽기 전용입니다.</p></div></div>${sectionHeading("RUN 탐색", "4개 · 가상 예시")}<div class="run-grid">${runs.map((r, i) => `<article class="card run-card ${i === 0 ? "current-run" : ""}"><div class="run-card-head"><span class="mono micro muted">${r.id}</span>${mark(r.kind)}</div><h4>${r.title}</h4><p>${r.summary}</p><div class="run-facts" style="margin:12px 0 0">${badge(r.own, "badge-outline")}<span class="source-label">${r.source}</span></div><progress class="progress progress-primary" value="${r.completed}" max="${r.total}" aria-label="${r.title} 완료 ${r.completed}/${r.total}"></progress><div class="run-card-meta"><span>완료 ${r.completed} / ${r.total}</span><button class="btn btn-ghost btn-xs" type="button" data-run="${i}">RUN 읽기 ${icon("arrow")}</button></div></article>`).join("")}</div>`;
}
function specExplorer() {
  const t = selectedTask();
  const isPlan = state.documentEntity === "plan";
  return `${runHeading("계획과 실행을 함께", "RUN-024 · 기록의 연결을 따라 읽기", false)}<div class="breadcrumbs micro muted"><ul><li>RUN-024</li><li>PLAN-001</li><li>${isPlan ? "계획" : t.id}</li></ul></div><div class="explorer-layout"><nav class="explorer-tree" aria-label="계획 기록 탐색"><div class="tree-group">${icon("folder")} PLAN-001</div><ul class="menu"><li><button type="button" data-entity="plan" class="${isPlan ? "menu-active" : ""}">${icon("file")} 경험 개선 계획</button></li>${tasks.map((task) => `<li><button type="button" class="tree-child ${!isPlan && state.selected === task.id ? "menu-active" : ""}" data-tree-task="${task.id}">${mark(task.status, false)}<span>${task.id}</span></button></li>`).join("")}<li><button type="button" data-record-detail="1">${icon("book")} FINDING-001</button></li></ul></nav><article class="tree-document"><div class="mono micro muted">${isPlan ? "PLAN-001" : t.id}</div><h3 style="margin:8px 0">${isPlan ? "Viewer 경험 개선" : t.title}</h3>${isPlan ? badge("설계 예시", "badge-outline") : mark(t.status)}<div class="join" role="group" aria-label="기록 내용 선택" style="margin:18px 0">${[
    ["goal", "목적"],
    ["result", "결과"],
    ["verification", "검증"],
  ]
    .map(
      ([key, text]) =>
        `<button class="btn btn-xs join-item ${state.documentTab === key ? "btn-primary" : "btn-ghost"}" type="button" data-document="${key}" aria-pressed="${state.documentTab === key}">${text}</button>`,
    )
    .join(
      "",
    )}</div><h4>${state.documentTab === "result" ? "현재 결과" : state.documentTab === "verification" ? "검증 조건" : "달성할 목표"}</h4><p class="small muted" style="margin-top:10px;line-height:1.9">${state.documentTab === "verification" ? "밝음·어두움·고대비 테마, 320px 확장, 키보드 탐색, 자동 갱신 시 선택 보존을 확인합니다." : state.documentTab === "result" ? (isPlan ? "시안과 계획을 검토하는 가상 예시입니다. 실제 제품 구현 결과가 아닙니다." : t.result) : isPlan ? records[0].detail : t.goal}</p><div class="quiet-rule"></div>${sectionHeading("연결된 기록")}<p class="micro muted">${t.depends.join(" → ") || "선행 조건 없음"}</p><details class="collapse collapse-arrow" style="margin-top:20px;background:var(--color-base-200)"><summary class="collapse-title small">추가 필드</summary><div class="collapse-content micro"><p>담당: ${t.owner}</p><p>출처: local / design-study</p><p>이 데이터는 시안 비교를 위한 예시입니다.</p></div></details></article></div>`;
}
function depNode(t) {
  return `<button type="button" class="dep-node ${t.status === "blocked" ? "blocked-node" : t.status === "running" ? "active-node" : ""}" data-task="${t.id}"><span class="mono micro muted">${t.id}</span><strong>${t.title}</strong>${mark(t.status)}</button>`;
}
function dependencyLens() {
  return `${runHeading("무엇을 기다리고 있나요?", "RUN-024 · TASK-005의 선행 작업 추적", false)}${alertBlock()}<div class="dependency-map" role="group" aria-label="TASK-002 완료 후 TASK-003과 TASK-004가 갈라지고, 둘의 완료 후 TASK-005, 이어 TASK-006 진행 가능"><div class="dep-row">${depNode(tasks[1])}</div><span class="dep-arrow" aria-hidden="true">↓</span><div class="dep-row">${depNode(tasks[2])}${depNode(tasks[3])}</div><span class="dep-arrow" aria-hidden="true">↓</span><p class="dep-caption">두 작업이 모두 완료되면</p><div class="dep-row">${depNode(tasks[4])}</div><span class="dep-arrow" aria-hidden="true">↓</span><div class="dep-row">${depNode(tasks[5])}</div></div><p class="micro muted">선행 ID에 근거한 예시입니다. 색상과 상태 레이블을 함께 읽을 수 있습니다.</p>`;
}
function quietOutline() {
  return `<div class="quiet-layout"><div class="run-caption"><span class="mono">RUN-024</span><span>·</span><span>이 세션 / 가상 예시</span></div><div class="quiet-title"><div class="focus-label">KEEP THE WORK IN VIEW</div><h3>Viewer 경험 개선</h3><p>지금 진행하는 일과 다음에 확인할 기록.</p></div><div class="run-facts"><span>완료 2 / 6</span><progress class="progress progress-primary" value="2" max="6" aria-label="예시 작업 완료 2/6"></progress><span>진행 중</span></div><div class="quiet-rule"></div>${sectionHeading("지금 진행 중")}${taskList([tasks[2]])}${alertBlock()}${sectionHeading("이어지는 작업")}${taskList(tasks.slice(4))}<div class="quiet-rule"></div><details class="collapse collapse-arrow"><summary class="collapse-title">계획과 완료 기록</summary><div class="collapse-content"><p>${records[0].summary}</p>${taskList(tasks.slice(0, 2))}</div></details><details class="collapse collapse-arrow"><summary class="collapse-title">실행 정보와 출처</summary><div class="collapse-content"><p>소유자: 이 세션 · 출처: local / design-study</p><p>RUN-024 · PLAN-001 · 읽기 전용 예시</p></div></details></div>`;
}

const renderers = {
  "01": signalDesk,
  "02": flowBoard,
  "03": focusNow,
  "04": evidenceStream,
  "05": recordLibrary,
  "06": memoryGarden,
  "07": runAtlas,
  "08": specExplorer,
  "09": dependencyLens,
  10: quietOutline,
};
function specialState() {
  if (state.screen === "loading")
    return '<div class="loading-state" aria-label="예시 데이터 로딩 중" aria-busy="true"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><p class="small muted">RUN을 불러오는 중입니다…</p></div>';
  if (state.screen === "empty")
    return `<div class="empty-state">${icon("inbox")}<h3>아직 시작한 RUN이 없습니다</h3><p>Agent 대화에서 작업을 시작하면 계획과 TASK가 여기에 표시됩니다.</p><button type="button" class="btn btn-sm" data-normal-state>정상 예시 보기</button></div>`;
  return `<div class="empty-state state-error">${icon("alert")}<h3>작업 공간에 연결하지 못했습니다</h3><p>마지막 화면은 실행 상태를 보장하지 않습니다. 연결 상태를 확인한 뒤 다시 불러오세요.</p><div class="alert alert-soft alert-error"><span>연결 오류 · 표시 데이터 없음<br><small>로컬 연결 실패를 보여주는 가상 상태입니다.</small></span></div><button type="button" class="btn btn-primary btn-sm" data-normal-state>다시 불러오기 (데모)</button></div>`;
}
function productBody(concept, ext, mini) {
  if (!mini && state.screen !== "ready") return specialState();
  if (!mini && state.section === "memories") return memoryGarden(ext);
  if (!mini && state.section === "records") return recordLibrary(ext);
  return renderers[concept.id](ext);
}
function renderProduct(concept, surface, mini = false) {
  const ext = surface === "extension";
  return `<div class="product product-${surface}" data-theme="${state.color}" data-accent="${concept.accent}" ${mini ? "inert" : ""}><header class="p-top"><div class="p-top-left"><span class="p-logo">t<b>apl</b></span><span class="workspace-label">personal / tapl</span></div><div class="p-toolbar"><span class="readonly">${icon("lock")} 읽기 전용</span><button class="btn btn-ghost btn-xs" type="button" data-refresh aria-label="예시 화면 초기화">${icon("refresh")}</button></div></header><nav class="extension-nav" aria-label="확장 탐색">${[
    ["current", "현재"],
    ["records", "기록"],
    ["memories", "기억"],
  ]
    .map(
      ([key, label]) =>
        `<button class="btn btn-xs" type="button" data-section="${key}" aria-pressed="${state.section === key}">${label}</button>`,
    )
    .join(
      "",
    )}</nav><div class="p-layout"><aside class="p-nav"><div><div class="nav-section">WORKSPACE</div><ul class="menu">${[
    ["current", "grid", "현재 RUN"],
    ["records", "search", "기록 검색"],
    ["memories", "book", "연상 기억"],
  ]
    .map(
      ([key, ico, label]) =>
        `<li><button type="button" data-section="${key}" class="${state.section === key ? "menu-active" : ""}">${icon(ico)}${label}</button></li>`,
    )
    .join(
      "",
    )}</ul></div><div><div class="nav-section">PINNED RECORD</div><ul class="menu"><li><button type="button" data-record-detail="0">${icon("file")} PLAN-001</button></li><li><button type="button" data-task="TASK-003">${icon("branch")} TASK-003</button></li></ul></div><div class="nav-bottom">${icon("lock")} 로컬 예시<br>RUN-024 / 이 세션<br>실제 데이터와 연결 안 됨</div></aside><div class="p-content">${productBody(concept, ext, mini)}</div></div></div>`;
}
function frame(concept, surface) {
  const ext = surface === "extension";
  return `<section class="screen-frame ${ext ? "extension-frame" : "viewer-frame"}" aria-label="${ext ? "VS Code 확장" : "브라우저 Viewer"} 미리보기"><div class="frame-bar"><span aria-hidden="true"><i class="window-dot"></i><i class="window-dot"></i><i class="window-dot"></i></span><span class="frame-label">${ext ? "VS CODE / TAPL" : "BROWSER / TAPL VIEWER"}</span><span class="frame-extra">${ext ? "COMPACT" : "RESPONSIVE"}</span></div>${renderProduct(concept, surface)}</section>`;
}
function updateControls() {
  document.querySelectorAll("[data-surface]").forEach((b) => {
    if (b.tagName === "BUTTON")
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.surface === state.surface),
      );
  });
  document
    .querySelectorAll("[data-color]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.color === state.color)),
    );
  $("#screen-state").value = state.screen;
}
function renderScreens() {
  const screens = $("#screens");
  const active = document.activeElement;
  const surface = active?.closest(".product-extension")
    ? "extension"
    : "viewer";
  const keys = [
    "data-filter",
    "data-section",
    "data-record",
    "data-document",
    "data-entity",
    "data-reset-filters",
    "data-normal-state",
    "data-tree-task",
    "data-refresh",
    "data-task",
    "aria-label",
  ];
  const focusKey = screens.contains(active)
    ? keys.find((key) => active.hasAttribute(key))
    : null;
  const focusValue = focusKey ? active.getAttribute(focusKey) : null;
  screens.dataset.surface = state.surface;
  screens.innerHTML = (
    state.surface === "pair" ? ["viewer", "extension"] : [state.surface]
  )
    .map((name) => frame(currentConcept(), name))
    .join("");
  $("#detail-dialog").dataset.theme = state.color;
  updateControls();
  if (focusKey) {
    const product = $(`.product-${surface}`, screens);
    const next =
      product &&
      [...product.querySelectorAll(`[${focusKey}]`)].find(
        (el) => el.getAttribute(focusKey) === focusValue,
      );
    if (next) next.focus({ preventScroll: true });
    else {
      const fallback =
        product?.querySelector("input") || product?.querySelector("h3");
      if (fallback) {
        if (fallback.tagName !== "INPUT")
          fallback.setAttribute("tabindex", "-1");
        fallback.focus({ preventScroll: true });
      }
    }
  }
}
function renderOverview() {
  const saved = { ...state };
  Object.assign(state, {
    filter: "all",
    query: "",
    memoryQuery: "",
    selected: "TASK-003",
    record: 0,
    documentTab: "goal",
    documentEntity: "task",
  });
  const grid = $("#overview-grid");
  grid.innerHTML = concepts
    .map(
      (c) =>
        `<article class="overview-tile"><div class="overview-tile-head"><strong>${c.id} / ${c.name}</strong><span>${c.id === "01" || c.id === "03" ? "RECOMMENDED" : c.ko}</span></div><div class="overview-mini" aria-hidden="true">${renderProduct(c, "viewer", true)}</div><p>${c.description}</p><button type="button" class="overview-button" data-open-concept="${c.id}" style="padding:10px 15px;margin:0">${c.ko} 시안 살펴보기 <span aria-hidden="true">↗</span></button></article>`,
    )
    .join("");
  Object.assign(state, saved);
  resizeMinis();
}
function resizeMinis() {
  document.querySelectorAll(".overview-mini").forEach((el) => {
    const scale = el.clientWidth / 950;
    el.style.setProperty("--mini-scale", String(scale));
    el.style.height = `${760 * scale}px`;
  });
}
function render() {
  const c = currentConcept();
  $("#concept-nav").innerHTML = concepts
    .map(
      (item) =>
        `<a href="#${item.id}" class="concept-link" ${item.id === c.id && !state.overview ? 'aria-current="true"' : ""}><span class="number">${item.id}</span><span><span class="concept-label">${item.name}</span><span class="concept-sublabel">${item.ko}</span></span>${item.id === "01" || item.id === "03" ? '<span class="recommended-dot" aria-label="추천 시안"></span>' : ""}</a>`,
    )
    .join("");
  $("#concept-kicker").textContent = state.overview
    ? "TEN WAYS TO SEE THE WORK"
    : c.tag;
  $("#concept-title").textContent = state.overview
    ? "10가지 방향, 한눈에"
    : c.name;
  $("#concept-description").textContent = state.overview
    ? "같은 예시 데이터로 정보 구조와 시각적 우선순위를 비교합니다."
    : c.description;
  $("#concept-position").textContent = `${c.id} / 10`;
  $("#overview-button").setAttribute("aria-pressed", String(state.overview));
  $(".lab-main").classList.toggle("overview-mode", state.overview);
  $("#overview-grid").hidden = !state.overview;
  $("#rationale").innerHTML =
    `<div><h3 class="rationale-label">WHY THIS WORKS</h3><p class="rationale-text">${c.strength}</p></div><div><h3 class="rationale-label">TRADE-OFF</h3><p class="rationale-text">${c.tradeoff}</p></div><div><h3 class="rationale-label">DAISYUI 5 / COMPONENTS</h3><div class="component-list">${c.components.map((name) => `<code>${name}</code>`).join("")}</div></div>`;
  if (state.overview) renderOverview();
  else renderScreens();
}
function announce(message) {
  $("#announcement").textContent = message;
}
function pickConcept(id) {
  if (!concepts.some((c) => c.id === id)) return;
  const restoreConceptFocus = document.activeElement?.closest(
    ".concept-link, [data-open-concept], [data-run]",
  );
  state.concept = id;
  state.overview = false;
  state.filter = "all";
  state.query = "";
  state.memoryQuery = "";
  state.section = "current";
  state.documentTab = "goal";
  state.documentEntity = "task";
  state.screen = "ready";
  history.replaceState(null, "", `#${id}`);
  render();
  if (restoreConceptFocus)
    $(`#concept-nav a[href="#${id}"]`)?.focus({ preventScroll: true });
  announce(`${currentConcept().name} 시안을 선택했습니다.`);
}
function showDialog(content) {
  $("#dialog-content").innerHTML = content;
  $("#detail-dialog").dataset.theme = state.color;
  $("#detail-dialog").showModal();
}
function showTask(id) {
  const t = tasks.find((item) => item.id === id);
  if (!t) return;
  state.selected = id;
  renderScreens();
  showDialog(
    `<div class="dialog-meta">${t.id} · PLAN-001 · local / design-study</div><h2 id="dialog-title">${t.title}</h2>${mark(t.status)}<h3>목적</h3><p>${t.goal}</p><h3>현재 결과</h3><p>${t.result}</p><h3>선행 조건</h3><p>${t.depends.join(", ") || "없음"}</p><h3>검증 조건</h3><ul><li>Viewer와 확장에서 동일한 상태와 안정 ID 표시</li><li>밝음·어두움·고대비 및 좁은 화면 확인</li><li>자동 갱신 뒤 선택과 키보드 포커스 보존</li></ul><div class="alert alert-soft"><span>가상 예시 · 이 화면에서 실행·승인·상태 변경은 하지 않습니다.</span></div>`,
  );
}
function showRecord(index) {
  const r = records[index];
  if (!r) return;
  showDialog(
    `<div class="dialog-meta">${r.id} · ${r.source} · ${r.date}</div><h2 id="dialog-title">${r.title}</h2>${badge(r.type, "badge-outline")}<h3>요약</h3><p>${r.summary}</p><h3>원문 발췌 (가상 기록)</h3><p>${r.detail}</p><div class="alert alert-soft" style="margin-top:20px"><span>시안용 기록입니다. 실제 검색 결과나 과거 실행 기록이 아닙니다.</span></div>`,
  );
}
function setSection(section) {
  state.section = section;
  state.query = "";
  renderScreens();
  announce(
    `${section === "current" ? "현재 RUN" : section === "records" ? "기록 검색" : "연상 기억"} 보기`,
  );
}
document.addEventListener("click", (event) => {
  const target = event.target.closest("button,a");
  if (!target) return;
  if (target.matches(".concept-link,.lab-brand")) {
    event.preventDefault();
    pickConcept(target.getAttribute("href").slice(1));
  } else if (target.dataset.openConcept)
    pickConcept(target.dataset.openConcept);
  else if (target.id === "previous-concept" || target.id === "next-concept") {
    const index = concepts.findIndex((c) => c.id === state.concept);
    pickConcept(
      concepts[(index + (target.id === "next-concept" ? 1 : 9)) % 10].id,
    );
  } else if (target.id === "overview-button") {
    state.overview = !state.overview;
    history.replaceState(
      null,
      "",
      state.overview ? "#overview" : `#${state.concept}`,
    );
    render();
  } else if (target.dataset.surface) {
    state.surface = target.dataset.surface;
    renderScreens();
  } else if (target.dataset.color) {
    state.color = target.dataset.color;
    renderScreens();
  } else if (target.dataset.task) showTask(target.dataset.task);
  else if (target.dataset.filter) {
    state.filter = target.dataset.filter;
    renderScreens();
    announce(`${target.textContent} 상태 ${filteredTasks().length}개`);
  } else if (target.dataset.section) setSection(target.dataset.section);
  else if (target.hasAttribute("data-reset-filters")) {
    state.filter = "all";
    state.query = "";
    state.memoryQuery = "";
    renderScreens();
  } else if (target.hasAttribute("data-record")) {
    state.record = Number(target.dataset.record);
    renderScreens();
  } else if (target.hasAttribute("data-record-detail"))
    showRecord(Number(target.dataset.recordDetail));
  else if (target.dataset.memory) {
    const m = memories.find((item) => item.id === target.dataset.memory);
    const r = records.find((item) => item.id === m.source);
    showDialog(
      `<div class="dialog-meta">${m.id} · 가상 연상 기억</div><h2 id="dialog-title">${m.title}</h2><p>${m.text}</p><h3>검색 단서</h3><p>${m.cues.join(" · ")}</p><h3>원문 출처 / ${m.source}</h3><p>${r ? r.detail : "공통 컴포넌트의 상태·목적·검증 조건을 한곳에서 읽도록 정리합니다."}</p><p class="muted" style="margin-top:18px">local / design-study · 출처도 가상 예시입니다.</p>`,
    );
  } else if (target.hasAttribute("data-run")) {
    const i = Number(target.dataset.run);
    if (i === 0) {
      pickConcept("01");
    } else {
      const label = [
        "Viewer 경험 개선",
        "Claude 연결 확인",
        "검색 경험 정리",
        "설치 가이드 검토",
      ][i];
      showDialog(
        `<div class="dialog-meta">가상 RUN · ${i === 1 ? "다른 세션" : "공유·아카이브 기록"}</div><h2 id="dialog-title">${label}</h2><p>이 RUN은 다중 작업 탐색을 설명하는 가상 예시입니다.</p><h3>출처와 권한</h3><p>${i === 1 ? "같은 저장소의 다른 세션" : "공유 이력 또는 아카이브"} · 읽기 전용</p><div class="alert alert-soft"><span>소유자가 다른 RUN에는 실행·폐기 동작을 제공하지 않습니다.</span></div>`,
      );
    }
  } else if (target.dataset.treeTask) {
    state.selected = target.dataset.treeTask;
    state.documentEntity = "task";
    state.documentTab = "goal";
    renderScreens();
  } else if (target.dataset.entity) {
    state.documentEntity = target.dataset.entity;
    state.documentTab = "goal";
    renderScreens();
  } else if (target.dataset.document) {
    state.documentTab = target.dataset.document;
    renderScreens();
  } else if (target.hasAttribute("data-normal-state")) {
    state.screen = "ready";
    renderScreens();
  } else if (target.hasAttribute("data-refresh")) {
    state.filter = "all";
    state.query = "";
    state.memoryQuery = "";
    state.screen = "ready";
    renderScreens();
    announce("가상 예시 화면을 초기화했습니다.");
  }
});
document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-search-form]");
  if (!form) return;
  event.preventDefault();
  const value = new FormData(form).get("query") || "";
  if (form.dataset.searchForm === "memories") state.memoryQuery = String(value);
  else state.query = String(value);
  renderScreens();
  announce("검색 결과를 갱신했습니다.");
});
$("#screen-state").addEventListener("change", (event) => {
  state.screen = event.target.value;
  renderScreens();
  announce(`${event.target.selectedOptions[0].text} 예시 화면`);
});
window.addEventListener("hashchange", () => {
  if (location.hash === "#overview") {
    state.overview = true;
    render();
  } else pickConcept(location.hash.slice(1));
});
window.addEventListener("resize", resizeMinis);
const initialId = location.hash.slice(1);
if (concepts.some((c) => c.id === initialId)) state.concept = initialId;
if (initialId === "overview") state.overview = true;
render();
