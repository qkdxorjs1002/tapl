/* Integrated UX study. Synthetic records only; no backend, host API or network. */
"use strict";
const copy = {
  skip: ["본문으로 건너뛰기", "Skip to page content"],
  navigation: ["탐색", "Navigation"],
  language: ["언어", "Language"],
  theme: ["테마 전환", "Change theme"],
  workspace: ["작업 공간", "Workspace"],
  explore: ["탐색", "Explore"],
  memory: ["메모리", "Memory"],
  management: ["관리", "Management"],
  current: ["현재 RUN", "Current RUN"],
  tasks: ["TASK 현황", "TASK status"],
  records: ["기록 검색", "Record search"],
  memories: ["연상 기억", "Associative memory"],
  discard: ["RUN 삭제", "Discard RUN"],
  permissionOwn: [
    "선택한 RUN의 기존 폐기 절차를 미리 봅니다.",
    "Preview the existing discard flow for this RUN.",
  ],
  permissionOther: [
    "읽기 전용 RUN이거나 서버에서 폐기를 지원하지 않습니다.",
    "This RUN is read-only or the server does not support discard.",
  ],
  thisSession: ["이 세션", "This session"],
  otherSession: ["다른 세션", "Other session"],
  peerHistory: ["공유 이력", "Peer history"],
  readOnly: ["읽기 전용 탐색", "Read-only browsing"],
  running: ["진행 중", "In progress"],
  blocked: ["막힘", "Blocked"],
  pending: ["대기", "Pending"],
  done: ["완료", "Completed"],
  skipped: ["건너뜀", "Skipped"],
  complete: ["완료", "Completed"],
  progress: ["작업 완료 비율", "Task completion"],
  currentFocus: ["지금 집중하는 작업", "IN FOCUS"],
  taskDetail: ["목적과 검증 조건", "Purpose and verification"],
  upNext: ["이어지는 작업", "Up next"],
  waitsFor: ["선행 조건 대기", "Awaiting prerequisites"],
  recentDone: ["완료한 일", "Completed work"],
  blockerTitle: [
    "후속 검증을 기다리게 하는 항목이 있습니다",
    "A blocker is holding up downstream verification",
  ],
  blockerLink: ["막힘 근거 읽기", "Read blocker evidence"],
  planSummary: ["이 RUN의 계획", "Plan for this RUN"],
  objective: ["목적", "Objective"],
  owner: ["담당", "Owner"],
  source: ["출처", "Source"],
  depends: ["선행 조건", "Prerequisites"],
  verification: ["검증 조건", "Verification"],
  result: ["현재 결과", "Current result"],
  requirements: ["요구사항", "Requirements"],
  related: ["연결된 레코드", "Related records"],
  properties: ["기록 속성", "Record properties"],
  kind: ["유형", "Kind"],
  parentPlan: ["연결 PLAN", "Parent PLAN"],
  fields: ["추가 필드", "Additional fields"],
  noDependencies: ["선행 조건 없음", "No prerequisites"],
  noRecords: ["이 유형의 기록이 없습니다", "No records of this kind"],
  noTasks: ["아직 등록된 TASK가 없습니다", "No TASKs yet"],
  noTasksHelp: [
    "Agent 대화에서 계획과 작업을 만들면 이 RUN에 표시됩니다.",
    "Plans and tasks created in the agent conversation will appear in this RUN.",
  ],
  allDone: ["이 RUN의 작업을 마쳤습니다", "All tasks in this RUN are complete"],
  allDoneHelp: [
    "완료 결과와 검증 기록을 TASK 현황에서 확인할 수 있습니다.",
    "Read the results and verification records in TASK status.",
  ],
  noActive: ["진행 중인 TASK가 없습니다", "No TASK is currently in progress"],
  noActiveHelp: [
    "대기 중인 작업의 선행 조건과 계획을 확인해 보세요.",
    "Review prerequisites and the plan for pending work.",
  ],
  showTasks: ["TASK 현황 보기", "View TASK status"],
  all: ["전체", "All"],
  taskSearch: ["작업 검색", "Search tasks"],
  search: ["검색", "Search"],
  taskColumn: ["작업", "Task"],
  status: ["상태", "Status"],
  noMatches: ["일치하는 기록이 없습니다", "No matching records"],
  noMatchesHelp: [
    "검색어나 범위를 바꿔 보세요.",
    "Try a different query or scope.",
  ],
  reset: ["검색 초기화", "Clear search"],
  searchPlaceholder: [
    "제목, 내용, 안정 ID로 검색",
    "Search title, content or stable ID",
  ],
  scope: ["검색 범위", "Search scope"],
  selectedRun: ["현재 RUN", "Selected RUN"],
  allRecords: ["전체 기록", "All records"],
  grouped: ["RUN별 보기", "Group by RUN"],
  flat: ["레코드별 보기", "Record list"],
  resultCount: ["검색 결과", "Results"],
  sourceRun: ["원문 RUN", "Source RUN"],
  recordCount: ["개 레코드", "records"],
  itemCount: ["{count}개", "{count} items"],
  singleItemCount: ["{count}개", "{count} item"],
  memorySearch: ["기억 검색", "Search memories"],
  memoryPlaceholder: ["교훈 또는 검색 단서", "Lesson or recall cue"],
  memoryScope: ["작업 공간 전체", "Entire workspace"],
  memorySource: ["출처 읽기", "Read source"],
  sourcePreview: ["기억의 원문 출처", "Memory source"],
  relatedRun: ["원문 RUN으로 이동", "Open source RUN"],
  discardTitle: ["이 RUN을 폐기할까요?", "Discard this RUN?"],
  confirmId: [
    "RUN ID를 입력해 확인하세요",
    "Enter the exact RUN ID to confirm",
  ],
  discardRecords: [
    "기록이 있는 RUN은 이력으로 보관됩니다. 이 버튼은 기존 RUN 폐기 절차를 따릅니다.",
    "RUNs with records are archived. This follows the existing RUN discard flow.",
  ],
  discardProcess: [
    "폐기 절차는 외부 Agent와 실행 중인 프로세스를 중지하지 않습니다.",
    "Discard does not stop external agents or running processes.",
  ],
  discardEmpty: [
    "기록이 없는 빈 RUN은 삭제 대상입니다. 이 시안에서는 실제로 삭제하지 않습니다.",
    "An empty RUN can be deleted. This concept does not delete it.",
  ],
  discardDemo: [
    "미리보기 · 실제 데이터는 변경되지 않습니다.",
    "Preview only. Real data remains unchanged.",
  ],
  previewDiscard: ["폐기 확인 미리보기", "Preview discard confirmation"],
  cancel: ["취소", "Cancel"],
  close: ["닫기", "Close"],
  back: ["뒤로 가기", "Back"],
  returned: ["이전 화면으로 돌아왔습니다", "Returned to the previous page"],
  discardToast: [
    "확인 절차를 미리 보았습니다. 실제 RUN과 시안 데이터는 유지됩니다.",
    "Confirmation previewed. Real RUNs and demo data remain unchanged.",
  ],
  planStep: ["계획", "Plan"],
  approvalStep: ["승인", "Approval"],
  executionStep: ["실행", "Execution"],
  verificationStep: ["검증", "Verification"],
  navigationChanged: ["RUN과 페이지를 전환했습니다", "RUN and page updated"],
  searchUpdated: ["검색 결과를 갱신했습니다", "Search results updated"],
};
const bi = (ko, en) => [ko, en];
const icons = {
  menu: '<path d="M4 6h16M4 12h16M4 18h16"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5"/>',
  moon: '<path d="M20.5 14.5A9 9 0 0 1 9.5 3.5a9 9 0 1 0 11 11z"/>',
  focus:
    '<path d="M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5"/><circle cx="12" cy="12" r="4"/>',
  table:
    '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 9v11"/>',
  file: '<path d="M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6"/>',
  folder: '<path d="M3 7V5h7l2 3h9v12H3z"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  book: '<path d="M4 4h6a3 3 0 0 1 2 1 3 3 0 0 1 2-1h6v15h-6a3 3 0 0 0-2 1 3 3 0 0 0-2-1H4zM12 5v15"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
  arrow: '<path d="M5 12h14M14 7l5 5-5 5"/>',
  back: '<path d="M19 12H5M10 7l-5 5 5 5"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  alert: '<path d="m12 3 10 18H2zM12 9v5M12 17h.01"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  inbox: '<path d="m5 4-3 11v5h20v-5L19 4zM2 15h6l2 3h4l2-3h6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3"/>',
};
const icon = (name) =>
  `<svg class="icon" aria-hidden="true" viewBox="0 0 24 24">${icons[name] || icons.file}</svg>`;
const esc = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const state = { run: "local24", locale: "ko", theme: "light", menuOpen: false };
const $ = (s, p = document) => p.querySelector(s);
const tr = (value) =>
  Array.isArray(value) ? value[state.locale === "ko" ? 0 : 1] : String(value);
function t(key) {
  if (!copy[key]) throw new Error(`Missing translation: ${key}`);
  return tr(copy[key]);
}
const runs = [
  {
    key: "local24",
    id: "RUN-024",
    source: "local / design-study",
    title: bi("Viewer 경험 개선", "Viewer experience"),
    description: bi(
      "현재 작업과 막힘이 먼저 보이는 Viewer·확장의 공통 경험을 정리합니다.",
      "Shape a shared Viewer and extension experience around current work and blockers.",
    ),
    owner: "thisSession",
    writable: true,
    status: "running",
    planTitle: bi("공유 Viewer UX 리팩토링", "Shared Viewer UX refactor"),
  },
  {
    key: "local25",
    id: "RUN-025",
    source: "local / other-session",
    title: bi("통합 검색 개선", "Unified search"),
    description: bi(
      "흩어진 PLAN·TASK·FINDING을 검색하고 원문까지 이어 읽습니다.",
      "Find related PLAN, TASK and FINDING records and follow them to the source.",
    ),
    owner: "otherSession",
    writable: true,
    status: "running",
    planTitle: bi(
      "기록 검색과 원문 탐색",
      "Record search and source navigation",
    ),
  },
  {
    key: "local26",
    id: "RUN-026",
    source: "local / other-session",
    title: bi("문서 구조 정리", "Documentation structure"),
    description: bi(
      "영문·국문 가이드의 탐색과 설명을 일치시킵니다.",
      "Align navigation and behavior descriptions across English and Korean guides.",
    ),
    owner: "otherSession",
    writable: true,
    status: "done",
    planTitle: bi("문서 탐색 개편", "Documentation navigation"),
  },
  {
    key: "local27",
    id: "RUN-027",
    source: "local / design-study",
    title: bi("새로운 작업", "New work"),
    description: bi(
      "아직 계획과 TASK가 없는 RUN의 예시입니다.",
      "An example RUN without plans or tasks yet.",
    ),
    owner: "thisSession",
    writable: true,
    status: "pending",
    planTitle: bi("새 계획", "New plan"),
  },
  {
    key: "peer24",
    id: "RUN-024",
    source: "peer / sample-history",
    title: bi("공유 기록 검토", "Shared history"),
    description: bi(
      "다른 출처의 같은 표시 ID를 구분해 읽습니다.",
      "Distinguish identical display IDs from different sources.",
    ),
    owner: "peerHistory",
    writable: false,
    status: "blocked",
    planTitle: bi("공유 이력 읽기 검토", "Peer history review"),
  },
];
const taskSeeds = [
  [
    bi("현재 화면과 동작 조사", "Audit existing UI and behavior"),
    "done",
    bi(
      "기존 화면과 데이터 경계를 확인합니다.",
      "Identify current screens and data boundaries.",
    ),
  ],
  [
    bi("DaisyUI 5 빌드 전환", "Migrate the DaisyUI 5 build"),
    "done",
    bi(
      "Tailwind 4와 DaisyUI 5의 로컬 자산 경로를 검증합니다.",
      "Verify local assets with Tailwind 4 and DaisyUI 5.",
    ),
  ],
  [
    bi("공통 컴포넌트 정리", "Compose shared UI components"),
    "running",
    bi(
      "RUN·TASK·레코드 상세를 공통 읽기 단위로 나눕니다.",
      "Separate RUN, TASK and record details into shared reading components.",
    ),
  ],
  [
    bi("VS Code 테마 연결", "Connect VS Code theme tokens"),
    "blocked",
    bi(
      "편집기 테마와 의미 색상·포커스 경계를 연결합니다.",
      "Connect editor themes to semantic colors and focus boundaries.",
    ),
  ],
  [
    bi("반응형·접근성 검증", "Verify layout and accessibility"),
    "pending",
    bi(
      "좁은 컨테이너와 키보드 탐색을 확인합니다.",
      "Verify narrow containers and keyboard navigation.",
    ),
  ],
  [
    bi("사용 가이드 정리", "Align user guides"),
    "pending",
    bi(
      "실제 동작과 영문·국문 설명을 일치시킵니다.",
      "Align actual behavior with English and Korean guides.",
    ),
  ],
  [
    bi("RUN 전환 상태 검토", "Review RUN switching state"),
    "pending",
    bi(
      "다른 RUN의 상세와 선택이 섞이지 않는지 확인합니다.",
      "Keep selection and details isolated across RUNs.",
    ),
  ],
  [
    bi("검색 결과 문맥 표시", "Show search-result context"),
    "pending",
    bi(
      "원문 RUN과 출처를 검색 결과에 표시합니다.",
      "Show the source RUN and provenance in search results.",
    ),
  ],
  [
    bi("Explore 목록 스크롤 검증", "Verify Explore list scrolling"),
    "pending",
    bi(
      "고정 패널 안에서 목록이 독립적으로 스크롤되는지 확인합니다.",
      "Verify independent list scrolling inside the fixed navigation.",
    ),
  ],
  [
    bi("긴 본문 렌더링 확인", "Verify long record rendering"),
    "pending",
    bi(
      "기록 본문만 스크롤되고 탐색 문맥은 유지되는지 확인합니다.",
      "Scroll long records while keeping navigation context fixed.",
    ),
  ],
  [
    bi("다국어 레이블 확인", "Check multilingual labels"),
    "pending",
    bi(
      "한국어·영어 전환 시 버튼과 안내를 확인합니다.",
      "Check controls and guidance in Korean and English.",
    ),
  ],
  [
    bi("최종 회귀 검토", "Review regression coverage"),
    "pending",
    bi(
      "RUN·TASK·출처·기존 폐기 절차를 함께 검토합니다.",
      "Review RUNs, TASKs, provenance and the existing discard flow.",
    ),
  ],
];
const records = [];
function addRecord(run, kind, id, title, goal, status = "done", extra = {}) {
  const item = {
    uid: `${run.key}/${kind}/${id}`,
    runKey: run.key,
    kind,
    id,
    title,
    goal,
    status,
    owner: bi("Main", "Main"),
    depends: [],
    ...extra,
  };
  records.push(item);
  return item;
}
for (const run of runs) {
  if (run.key === "local27") continue;
  addRecord(run, "PLAN", "PLAN-001", run.planTitle, run.description, "running");
  if (run.key === "local24")
    addRecord(
      run,
      "PLAN",
      "PLAN-002",
      bi("테마와 배치 검증", "Theme and layout verification"),
      bi(
        "밝음·어두움·좁은 폭에서 읽기와 선택을 확인합니다.",
        "Verify reading and selection across themes and container widths.",
      ),
      "pending",
    );
  const count = run.key === "local24" ? 12 : run.key === "local25" ? 5 : 3;
  for (let i = 0; i < count; i++) {
    let [title, status, goal] = taskSeeds[i];
    if (run.key === "local25") {
      title = [
        bi("검색 범위와 필터 정리", "Define search scopes and filters"),
        bi("RUN별 결과 묶기", "Group results by RUN"),
        bi("원문 상세 연결", "Connect result details"),
        bi("기억 출처 표시", "Expose memory sources"),
        bi("검색 회귀 검증", "Verify search regressions"),
      ][i];
      goal = bi(
        "검색 결과의 안정 ID와 원문 RUN을 일관되게 연결합니다.",
        "Consistently connect stable IDs to the source RUN.",
      );
      status = ["done", "running", "pending", "pending", "pending"][i];
    }
    if (run.key === "local26") {
      title = [
        bi("문서 홈 연결", "Connect documentation homes"),
        bi("양언어 예제 정리", "Align bilingual examples"),
        bi("상대 링크 검증", "Validate relative links"),
      ][i];
      status = "done";
    }
    if (run.key === "peer24") {
      title = [
        bi("공유 기록 출처 확인", "Verify shared-record provenance"),
        bi("동일 ID 구분", "Disambiguate identical IDs"),
        bi("원문 연결 확인", "Verify source links"),
      ][i];
      status = ["done", "blocked", "pending"][i];
    }
    const id = `TASK-${String(i + 1).padStart(3, "0")}`;
    const depends =
      i === 0
        ? []
        : i === 4 && run.key === "local24"
          ? ["TASK-003", "TASK-004"]
          : [`TASK-${String(i).padStart(3, "0")}`];
    addRecord(run, "TASK", id, title, goal, status, {
      owner:
        i === 2
          ? bi("Agent A", "Agent A")
          : i === 3
            ? bi("Agent B", "Agent B")
            : bi("Main", "Main"),
      depends,
    });
  }
  addRecord(
    run,
    "FINDING",
    "FINDING-001",
    bi("테마와 컴포넌트 경계", "Theme and component boundaries"),
    bi(
      "구조와 의미 토큰을 나누고 VS Code의 색상·포커스 연결을 보존합니다.",
      "Separate structure from semantic tokens and preserve VS Code color and focus mappings.",
    ),
  );
  addRecord(
    run,
    "FINDING",
    "FINDING-002",
    bi("RUN의 소유자와 출처", "RUN ownership and provenance"),
    bi(
      "표시 ID가 같아도 출처가 다르면 서로 다른 RUN으로 탐색합니다.",
      "Treat identical display IDs from different sources as separate RUNs.",
    ),
  );
  if (run.key === "local24")
    addRecord(
      run,
      "FINDING",
      "FINDING-003",
      bi("페이지와 패널의 스크롤 경계", "Page and panel scroll boundaries"),
      bi(
        "상단·좌측은 고정하고 본문과 펼친 폴드 목록만 스크롤합니다.",
        "Fix the header and sidebar; scroll only page content and the open record list.",
      ),
    );
}
const memories = [
  {
    id: "MEM-001",
    title: bi("화면과 데이터 경계 분리", "Separate UI and data boundaries"),
    body: bi(
      "갱신 방식이 달라도 같은 읽기 모델을 사용하면 일관된 화면을 유지할 수 있습니다.",
      "A shared read model keeps screens consistent across different update transports.",
    ),
    cues: ["shared-ui", "transport", "refresh"],
    source: "local24/PLAN/PLAN-001",
    topic: bi("구조", "Architecture"),
  },
  {
    id: "MEM-002",
    title: bi(
      "테마는 의미 토큰에서 시작하기",
      "Start themes with semantic tokens",
    ),
    body: bi(
      "색상 값보다 역할을 먼저 정의하고 편집기와 브라우저의 토큰을 연결합니다.",
      "Define semantic roles before colors, then connect editor and browser tokens.",
    ),
    cues: ["theme", "tokens", "contrast"],
    source: "local24/FINDING/FINDING-001",
    topic: bi("디자인", "Design"),
  },
  {
    id: "MEM-003",
    title: bi("기록의 출처를 함께 읽기", "Read records with their provenance"),
    body: bi(
      "같은 안정 ID를 구분하려면 RUN과 출처를 함께 확인해야 합니다.",
      "Check RUN identity and provenance together to distinguish identical stable IDs.",
    ),
    cues: ["source-db", "stable-id", "run-owner"],
    source: "peer24/FINDING/FINDING-002",
    topic: bi("동작", "Behavior"),
  },
  {
    id: "MEM-004",
    title: bi(
      "검색 범위와 표현을 구분하기",
      "Separate scope from presentation",
    ),
    body: bi(
      "검색할 기록의 범위와 결과를 묶는 방식을 독립적으로 선택합니다.",
      "Choose the search scope independently of how results are grouped.",
    ),
    cues: ["search", "scope", "grouping"],
    source: "local25/TASK/TASK-002",
    topic: bi("탐색", "Navigation"),
  },
];
const capabilities = { discardRun: true };
function canDiscard(run = currentRun()) {
  return Boolean(run) && capabilities.discardRun && run.writable !== false;
}
const views = new Map();
const navigationTrail = [];
function currentRun() {
  return runs.find((r) => r.key === state.run);
}
function view() {
  if (!views.has(state.run))
    views.set(state.run, {
      page: "current",
      openKind: "PLAN",
      record: null,
      filter: "all",
      taskQuery: "",
      query: "",
      scope: "current",
      group: "run",
      searchOpen: [state.run],
      memoryQuery: "",
      memory: null,
      scrolls: {},
      foldScrolls: {},
    });
  return views.get(state.run);
}
function runRecords(run = currentRun(), kind) {
  return records.filter(
    (r) => r.runKey === run.key && (!kind || r.kind === kind),
  );
}
function taskRecords(run = currentRun()) {
  return runRecords(run, "TASK");
}
function runFor(record) {
  return runs.find((run) => run.key === record.runKey);
}
function getRecord(uid) {
  return records.find((r) => r.uid === uid);
}
const statusColors = {
  running: "status-primary",
  blocked: "status-warning",
  pending: "status-pending",
  done: "status-success",
  skipped: "status-neutral",
};
function statusMark(status, label = true) {
  return `<span class="status-label"><span class="status ${statusColors[status]}" aria-hidden="true"></span>${label ? t(status) : `<span class="sr-only">${t(status)}</span>`}</span>`;
}
const chip = (label, extra = "") =>
  `<span class="badge badge-sm ${extra}">${esc(label)}</span>`;
const recButton = (record, label, cls = "record-link") =>
  `<button class="${cls}" type="button" data-record="${record.uid}">${label || esc(tr(record.title))}</button>`;
function titleForPage() {
  const v = view();
  return v.page === "record"
    ? getRecord(v.record)?.kind || t("explore")
    : t(v.page);
}
function counts() {
  const all = taskRecords();
  return {
    total: all.length,
    done: all.filter((x) => x.status === "done").length,
    running: all.filter((x) => x.status === "running").length,
    blocked: all.filter((x) => x.status === "blocked").length,
    pending: all.filter((x) => x.status === "pending").length,
  };
}
function backButton() {
  return navigationTrail.length
    ? `<button class="btn btn-sm page-back" id="page-back" type="button">${icon("back")}<span>${t("back")}</span></button>`
    : "";
}
function pageHeader(heading = "", summary = "") {
  return `<div class="page-title-row"><div><h1>${esc(heading || titleForPage())}</h1>${summary ? `<p class="page-description">${esc(summary)}</p>` : ""}</div>${backButton()}</div>`;
}
function meter() {
  const c = counts();
  return `<div class="run-meter"><span>${t("complete")} <strong>${c.done} / ${c.total}</strong></span><progress class="progress progress-primary" value="${c.done}" max="${c.total || 1}" aria-label="${t("progress")} ${c.done}/${c.total}"></progress><span>${t("running")} ${c.running} · ${t("blocked")} ${c.blocked} · ${t("pending")} ${c.pending}</span></div>`;
}
function sectionTitle(title, meta = "") {
  return `<div class="section-title"><h2>${title}</h2>${meta ? `<span>${meta}</span>` : ""}</div>`;
}
function taskQueue(items) {
  return `<ul class="task-queue list">${items.map((item) => `<li class="queue-item"><button type="button" class="queue-button" data-record="${item.uid}"><span class="status ${statusColors[item.status]}" aria-hidden="true"></span><span class="queue-copy"><span class="queue-code">${item.id}</span><span class="queue-title">${esc(tr(item.title))}</span><span class="queue-meta">${esc(tr(item.owner))} · ${t(item.status)}</span></span>${icon("arrow")}</button></li>`).join("")}</ul>`;
}
function blocker() {
  const item = taskRecords().find((x) => x.status === "blocked");
  return item
    ? `<div class="blocker-notice">${icon("alert")}<div><h3>${t("blockerTitle")}</h3><p>${item.id} · ${esc(tr(item.title))}</p><button class="btn btn-link btn-xs" type="button" data-record="${item.uid}">${t("blockerLink")} ${icon("arrow")}</button></div></div>`
    : "";
}
function empty(title, help, ico = "inbox", action = "") {
  return `<div class="empty-page">${icon(ico)}<h2>${t(title)}</h2><p>${t(help)}</p>${action}</div>`;
}
function currentPage() {
  const run = currentRun(),
    items = taskRecords(),
    active = items.find((x) => x.status === "running"),
    plan = runRecords(run, "PLAN")[0];
  let body;
  if (!items.length) body = empty("noTasks", "noTasksHelp");
  else if (!active && items.every((x) => x.status === "done"))
    body = empty(
      "allDone",
      "allDoneHelp",
      "check",
      `<button class="btn btn-primary btn-sm" type="button" data-page="tasks">${t("showTasks")}</button>`,
    );
  else if (!active)
    body = `${blocker()}${empty("noActive", "noActiveHelp", "info", `<button class="btn btn-sm" type="button" data-page="tasks">${t("showTasks")}</button>`)}`;
  else
    body = `<div class="run-overview"><section><ul class="steps phase-steps" aria-label="${t("progress")}">${["planStep", "approvalStep", "executionStep", "verificationStep"].map((key, i) => `<li class="step ${i < 3 ? "step-primary" : ""}">${t(key)}</li>`).join("")}</ul><article class="card focus-surface"><div class="eyebrow"><span>${t("currentFocus")}</span><span>${active.id}</span></div><h2>${esc(tr(active.title))}</h2><p>${esc(tr(active.goal))}</p><div class="focus-footer"><span class="focus-owner"><span class="owner-mark">A</span>${esc(tr(active.owner))} · ${t(active.status)}</span><button class="btn btn-primary btn-sm" type="button" data-record="${active.uid}">${t("taskDetail")} ${icon("arrow")}</button></div></article>${blocker()}<div class="details-grid">${sectionTitle(t("planSummary"))}${plan ? recButton(plan, `${plan.id} · ${esc(tr(plan.title))}`) : ""}</div></section><aside class="run-aside"><section class="run-aside-section">${sectionTitle(t("upNext"), t("waitsFor"))}${taskQueue(items.filter((x) => x.status === "pending").slice(0, 4))}</section><section class="run-aside-section">${sectionTitle(t("recentDone"), `${counts().done}`)}${taskQueue(items.filter((x) => x.status === "done").slice(0, 3))}</section></aside></div>`;
  return `${pageHeader(tr(run.title), tr(run.description))}${items.length ? meter() : ""}${body}`;
}
function filteredTasks() {
  const v = view();
  const q = v.taskQuery.trim().toLocaleLowerCase();
  return taskRecords().filter(
    (r) =>
      (v.filter === "all" || r.status === v.filter) &&
      (!q ||
        `${r.id} ${tr(r.title)} ${tr(r.goal)}`.toLocaleLowerCase().includes(q)),
  );
}
function tasksPage() {
  const v = view(),
    items = filteredTasks();
  return `${pageHeader()}${meter()}<div class="filter-toolbar"><div class="status-filter join" role="group" aria-label="${t("status")}">${["all", "running", "blocked", "pending", "done"].map((key) => `<button class="btn btn-xs join-item ${v.filter === key ? "btn-primary" : "btn-ghost"}" type="button" data-filter="${key}" aria-pressed="${v.filter === key}">${t(key)}</button>`).join("")}</div><form class="task-search" data-form="tasks"><label><span class="sr-only">${t("taskSearch")}</span><input class="input input-sm" name="query" aria-label="${t("taskSearch")}" value="${esc(v.taskQuery)}" placeholder="${t("taskSearch")}"></label><button class="btn btn-sm" type="submit" data-focus="search-submit">${t("search")}</button></form></div>${items.length ? `<div class="tasks-layout"><section><table class="table tasks-table"><caption class="sr-only">${t("tasks")} · ${currentRun().id}</caption><thead><tr><th scope="col"><span class="sr-only">${t("status")}</span></th><th scope="col">${t("taskColumn")}</th><th scope="col">${t("owner")}</th><th scope="col">${t("status")}</th></tr></thead><tbody>${items.map((r) => `<tr><td>${statusMark(r.status, false)}</td><td><button class="task-title-button" type="button" data-record="${r.uid}"><strong>${esc(tr(r.title))}</strong><span class="queue-code">${r.id}</span></button></td><td>${esc(tr(r.owner))}</td><td>${statusMark(r.status)}</td></tr>`).join("")}</tbody></table></section></div>` : empty(taskRecords().length ? "noMatches" : "noTasks", taskRecords().length ? "noMatchesHelp" : "noTasksHelp", "inbox", taskRecords().length ? `<button class="btn btn-sm" type="button" data-reset="tasks">${t("reset")}</button>` : "")}`;
}
function resultText(r) {
  return r.status === "done"
    ? tr(
        bi(
          "예시 기록의 검증과 정리를 완료했습니다.",
          "Verification and documentation are complete in this synthetic record.",
        ),
      )
    : r.status === "blocked"
      ? tr(
          bi(
            "선행 확인과 근거 검토를 기다리고 있습니다.",
            "Waiting for prerequisite checks and evidence review.",
          ),
        )
      : r.status === "running"
        ? tr(
            bi(
              "목적과 검증 조건에 따라 작업을 진행하고 있습니다.",
              "Work is progressing against its objective and verification criteria.",
            ),
          )
        : tr(
            bi(
              "선행 작업이 완료되면 검토합니다.",
              "Review begins after prerequisite work is complete.",
            ),
          );
}
function relatedFor(r) {
  const all = runRecords(runFor(r));
  if (r.kind === "PLAN")
    return all.filter((x) => x.kind !== "PLAN").slice(0, 6);
  if (r.kind === "TASK")
    return [
      ...all.filter((x) => x.kind === "PLAN").slice(0, 1),
      ...all.filter((x) => r.depends.includes(x.id)),
      ...all.filter((x) => x.kind === "FINDING").slice(0, 1),
    ];
  return all
    .filter((x) => x.kind === "PLAN" || x.id === "TASK-003")
    .slice(0, 3);
}
function relatedButton(r) {
  return `<button class="related-button" type="button" data-record="${r.uid}">${chip(r.kind, "badge-outline")}<span class="queue-copy"><span class="queue-code">${r.id}</span><strong class="queue-title">${esc(tr(r.title))}</strong></span>${icon("arrow")}</button>`;
}
function recordPage() {
  const r = getRecord(view().record);
  if (!r || r.runKey !== state.run) {
    view().page = "current";
    return currentPage();
  }
  const run = currentRun();
  const checks = [
    bi(
      "선택한 RUN의 안정 ID와 출처를 함께 표시합니다.",
      "Display the selected RUN's stable ID and provenance together.",
    ),
    bi(
      "한국어·영어와 밝음·어두움에서 상태와 본문을 읽을 수 있어야 합니다.",
      "Keep status and content readable in Korean, English, light and dark themes.",
    ),
    bi(
      "RUN 전환과 자동 갱신 후에도 상세 문맥과 키보드 포커스를 검증합니다.",
      "Verify record context and keyboard focus across RUN changes and refreshes.",
    ),
  ];
  return `<article class="record-page"><header class="record-hero"><div class="record-heading-row"><div class="record-heading-copy"><div class="record-context">${chip(r.kind, "badge-outline")}<span class="eyebrow">${r.id}</span>${statusMark(r.status)}</div><h1>${esc(tr(r.title))}</h1><div class="record-meta"><span>${t("owner")}: ${esc(tr(r.owner))}</span><span>·</span><span>2026-11-10</span></div></div>${backButton()}</div></header><div class="reading-grid"><div class="reading-body"><section class="reading-section"><h2>${t("objective")}</h2><p>${esc(tr(r.goal))}</p></section><section class="reading-section"><h2>${r.kind === "PLAN" ? t("requirements") : t("result")}</h2><p>${r.kind === "PLAN" ? esc(tr(run.description)) : resultText(r)}</p></section><section class="reading-section"><h2>${t("verification")}</h2><ul>${checks.map((c) => `<li class="checkline">${icon("check")}<span>${esc(tr(c))}</span></li>`).join("")}</ul></section><section class="reading-section"><h2>${t("depends")}</h2><p>${
    r.depends.length
      ? r.depends
          .map((id) => {
            const related = runRecords(run, "TASK").find((x) => x.id === id);
            return related ? recButton(related, id) : id;
          })
          .join(" · ")
      : t("noDependencies")
  }</p></section><section class="related-records">${sectionTitle(t("related"))}${relatedFor(r).map(relatedButton).join("")}</section><details class="collapse collapse-arrow record-fields"><summary class="collapse-title">${t("fields")}</summary><div class="collapse-content"><p><code>source: ${esc(run.source)}</code></p><p><code>run_key: ${run.key}</code></p></div></details></div><aside class="record-properties"><h2>${t("properties")}</h2><dl class="property"><dt>RUN</dt><dd>${run.id}<br>${esc(tr(run.title))}</dd></dl><dl class="property"><dt>${t("source")}</dt><dd class="mono">${esc(run.source)}</dd></dl><dl class="property"><dt>${t("owner")}</dt><dd>${esc(tr(r.owner))}</dd></dl><dl class="property"><dt>${t("kind")}</dt><dd>${r.kind}</dd></dl><dl class="property"><dt>${t("parentPlan")}</dt><dd>${runRecords(run, "PLAN")[0] ? recButton(runRecords(run, "PLAN")[0], "PLAN-001") : "—"}</dd></dl></aside></div></article>`;
}
function searchResults() {
  const v = view(),
    q = v.query.trim().toLocaleLowerCase();
  return records.filter(
    (r) =>
      (v.scope === "all" || r.runKey === state.run) &&
      (!q ||
        `${r.id} ${r.kind} ${tr(r.title)} ${tr(r.goal)} ${runFor(r).id} ${tr(runFor(r).title)} ${runFor(r).source}`
          .toLocaleLowerCase()
          .includes(q)),
  );
}
function resultRow(r, showSource = true) {
  const run = runFor(r);
  return `<button class="search-result" type="button" data-record="${r.uid}"><span class="result-meta">${chip(r.kind, "badge-outline")}<span class="mono">${r.id}</span>${statusMark(r.status)}</span><h3>${esc(tr(r.title))}</h3><p>${esc(tr(r.goal))}</p>${showSource ? `<span class="result-tail"><span>${run.id} · ${esc(tr(run.title))}</span><span class="mono">${esc(run.source)}</span></span>` : ""}</button>`;
}
function recordsPage() {
  const v = view(),
    found = searchResults();
  const grouped = runs
    .map((run) => ({ run, items: found.filter((r) => r.runKey === run.key) }))
    .filter((g) => g.items.length);
  return `${pageHeader()}<form class="search-box" data-form="records"><label class="input input-sm">${icon("search")}<input name="query" aria-label="${t("records")}" value="${esc(v.query)}" placeholder="${t("searchPlaceholder")}"></label><button class="btn btn-primary btn-sm" type="submit" data-focus="search-submit">${t("search")}</button></form><div class="search-controls"><label class="scope-controls"><span>${t("scope")}</span><select class="select select-sm" id="search-scope"><option value="current" ${v.scope === "current" ? "selected" : ""}>${t("selectedRun")} · ${currentRun().id}</option><option value="all" ${v.scope === "all" ? "selected" : ""}>${t("allRecords")}</option></select></label><div class="view-controls join" role="group" aria-label="${t("resultCount")}">${["run", "record"].map((key) => `<button class="btn btn-sm join-item ${v.group === key ? "btn-primary" : "btn-ghost"}" type="button" data-group="${key}" aria-pressed="${v.group === key}">${icon(key === "run" ? "folder" : "file")}${t(key === "run" ? "grouped" : "flat")}</button>`).join("")}</div></div><p class="search-context">${t("resultCount")} <strong>${found.length}</strong></p>${!found.length ? empty("noMatches", "noMatchesHelp", "search", `<button class="btn btn-sm" type="button" data-reset="records">${t("reset")}</button>`) : v.group === "run" ? grouped.map((g) => `<details class="search-group" data-search-run="${g.run.key}" ${v.searchOpen.includes(g.run.key) ? "open" : ""}><summary class="search-group-header"><div><h2>${g.run.id} · ${esc(tr(g.run.title))}</h2><p>${esc(g.run.source)} · ${t(g.run.owner)}</p></div><span class="search-group-meta">${chip(`${g.items.length} ${t("recordCount")}`, "badge-outline")}${icon("chevron").replace('class="icon"', 'class="icon group-chevron"')}</span></summary><div class="search-group-body">${g.items.map((r) => resultRow(r, false)).join("")}</div></details>`).join("") : `<section class="flat-results">${found.map((r) => resultRow(r)).join("")}</section>`}`;
}
function memoriesPage() {
  const v = view(),
    q = v.memoryQuery.trim().toLocaleLowerCase();
  const found = memories.filter(
    (m) =>
      !q ||
      `${tr(m.title)} ${tr(m.body)} ${m.cues.join(" ")}`
        .toLocaleLowerCase()
        .includes(q),
  );
  const selected = memories.find((m) => m.id === v.memory);
  const source = selected && getRecord(selected.source);
  return `${pageHeader()}<div class="memory-intro"><div><p class="small muted">${t("memoryScope")}</p></div><form class="search-box" data-form="memories"><label class="input input-sm">${icon("search")}<input name="query" aria-label="${t("memorySearch")}" value="${esc(v.memoryQuery)}" placeholder="${t("memoryPlaceholder")}"></label><button class="btn btn-sm" type="submit" data-focus="search-submit">${t("search")}</button></form></div>${selected ? `<section class="memory-detail" id="memory-source" tabindex="-1"><p class="eyebrow">${t("sourcePreview")} / ${selected.id}</p><h2>${esc(tr(selected.title))}</h2><p>${esc(tr(selected.body))}</p><p style="margin-top:13px">${source.id} · ${runFor(source).id} · ${esc(runFor(source).source)}</p>${relatedButton(source)}</section>` : ""}<div class="memory-grid" style="margin-top:${selected ? "22px" : "0"}">${found
    .map((m) => {
      const src = getRecord(m.source);
      return `<article class="card memory-card"><div class="memory-top">${chip(tr(m.topic), "badge-outline")}<span class="mono micro muted">${m.id}</span></div><h2>${esc(tr(m.title))}</h2><p>${esc(tr(m.body))}</p><div class="memory-cues">${m.cues.map((cue) => chip(cue)).join("")}</div><div class="memory-footer"><span>${src.id} · ${runFor(src).id}</span><button class="btn btn-ghost btn-xs" type="button" data-memory="${m.id}">${t("memorySource")} ${icon("arrow")}</button></div></article>`;
    })
    .join(
      "",
    )}</div>${found.length ? "" : empty("noMatches", "noMatchesHelp", "search", `<button class="btn btn-sm" type="button" data-reset="memories">${t("reset")}</button>`)}`;
}
// Motion is presentation-only; data, focus and disclosure state settle synchronously.
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const activeMotions = new Set();
const disclosureMotions = new Set();
const disclosureState = new WeakMap();
let pageMotions = [];
let foldMotion = null;
function tween(element, frames, duration = 240, complete) {
  if (!element || motionPreference.matches || !element.animate) {
    complete?.();
    return null;
  }
  const animation = element.animate(frames, {
    duration,
    easing: "cubic-bezier(0.22, 1, 0.36, 1)",
  });
  let settled = false;
  const handle = {
    finish() {
      if (settled) return;
      settled = true;
      activeMotions.delete(handle);
      animation.cancel();
      complete?.();
    },
    cancel() {
      if (settled) return;
      settled = true;
      activeMotions.delete(handle);
      animation.cancel();
    },
  };
  animation.onfinish = handle.finish;
  activeMotions.add(handle);
  return handle;
}
function finishFoldMotion() {
  const previous = foldMotion;
  foldMotion = null;
  previous?.finish();
}
function finishDisclosures() {
  [...disclosureMotions].forEach((handle) => handle.finish());
}
function animatePage(kind) {
  pageMotions.forEach((handle) => handle?.cancel());
  pageMotions = [];
  if (!kind || motionPreference.matches) return;
  const elements =
    kind === "list"
      ? [...document.querySelectorAll(".tasks-layout, .flat-results, .search-group, .memory-grid")]
      : [$("#page-content")];
  elements.forEach((element, index) => {
    const handle = tween(
      element,
      [
        { opacity: 0, transform: `translateY(${kind === "page" ? 7 : 4}px)` },
        { opacity: 1, transform: "translateY(0)" },
      ],
      kind === "page" ? 260 : 200 + Math.min(index * 10, 40),
    );
    if (handle) pageMotions.push(handle);
  });
}
function updateRunIndicator() {
  const tabs = $("#run-tabs"),
    active = $("[aria-selected=true]", tabs);
  if (!active) return;
  tabs.style.setProperty("--run-line-x", `${active.offsetLeft}px`);
  tabs.style.setProperty("--run-line-width", `${active.offsetWidth}px`);
  if (!tabs.hasAttribute("data-indicator-ready"))
    requestAnimationFrame(() => tabs.setAttribute("data-indicator-ready", ""));
}
function toggleExplore(kind) {
  finishFoldMotion();
  const owner = view(),
    scroll = $("#page-scroll").scrollTop;
  const closing = owner.openKind === kind;
  if (closing && !motionPreference.matches) {
    const list = $(`#list-${kind}`),
      trigger = $(`#fold-${kind}`);
    owner.foldScrolls[list.id] = list.scrollTop;
    owner.openKind = null;
    trigger.setAttribute("aria-expanded", "false");
    list.setAttribute("aria-hidden", "true");
    list.inert = true;
    list.classList.add("is-revealing");
    foldMotion = tween(
      list,
      [
        { height: `${list.clientHeight}px`, opacity: 1 },
        { height: "0px", opacity: 0 },
      ],
      180,
      () => {
        if (!list.isConnected || view() !== owner) return;
        const focus = focusToken();
        list.hidden = true;
        renderSidebar();
        restoreFocus(focus);
      },
    );
  } else {
    owner.openKind = closing ? null : kind;
    renderSidebar();
    $(`#fold-${kind}`).focus({ preventScroll: true });
    const list = $(`#list-${kind}`);
    if (!closing) {
      list.classList.add("is-revealing");
      foldMotion = tween(
        list,
        [
          { height: "0px", opacity: 0 },
          { height: `${list.clientHeight}px`, opacity: 1 },
        ],
        240,
        () => list.classList.remove("is-revealing"),
      );
    }
  }
  $("#page-scroll").scrollTop = scroll;
}
function toggleSearchGroup(details) {
  const panel = $(".search-group-body", details);
  const previous = disclosureState.get(details);
  const opening = previous ? !previous.opening : !details.open;
  const from = previous
    ? panel.getBoundingClientRect().height
    : opening
      ? 0
      : panel.getBoundingClientRect().height;
  previous?.handle?.finish();
  const owner = view();
  owner.searchOpen = opening
    ? [...new Set([...owner.searchOpen, details.dataset.searchRun])]
    : owner.searchOpen.filter((key) => key !== details.dataset.searchRun);
  if (motionPreference.matches) {
    details.open = opening;
    return;
  }
  details.open = true;
  const target = panel.scrollHeight;
  panel.classList.add("is-revealing");
  panel.inert = !opening;
  let handle;
  const entry = { opening, handle: null };
  handle = tween(
    panel,
    [
      { height: `${from}px`, opacity: opening && !previous ? 0 : 1 },
      { height: `${opening ? target : 0}px`, opacity: opening ? 1 : 0 },
    ],
    opening ? 240 : 180,
    () => {
      panel.classList.remove("is-revealing");
      panel.inert = false;
      details.open = opening;
      disclosureMotions.delete(handle);
      if (disclosureState.get(details) === entry)
        disclosureState.delete(details);
    },
  );
  entry.handle = handle;
  if (handle) {
    disclosureState.set(details, entry);
    disclosureMotions.add(handle);
  }
}
motionPreference.addEventListener("change", (event) => {
  if (event.matches) [...activeMotions].forEach((handle) => handle.finish());
});
document.addEventListener("click", (event) => {
  const summary = event.target.closest(".search-group > summary");
  if (!summary) return;
  event.preventDefault();
  toggleSearchGroup(summary.parentElement);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Tab") {
    finishFoldMotion();
    finishDisclosures();
  }
});
window.addEventListener("resize", updateRunIndicator);

function renderTabs() {
  const selected = currentRun();
  $("#run-tabs").innerHTML = runs
    .map(
      (run) =>
        `<button id="tab-${run.key}" class="tab run-tab" role="tab" type="button" data-run="${run.key}" aria-controls="page-content" aria-selected="${run.key === state.run}" tabindex="${run.key === state.run ? 0 : -1}" title="${esc(tr(run.title))} · ${run.id} · ${esc(run.source)}"><span class="run-tab-title"><span class="status ${statusColors[run.status]}" aria-hidden="true"></span><span>${esc(tr(run.title))}</span></span><span class="run-tab-meta">${run.id}</span></button>`,
    )
    .join("");
  $("#page-content").setAttribute("aria-labelledby", `tab-${selected.key}`);
  updateRunIndicator();
}
function formatItemCount(count) {
  return t(count === 1 ? "singleItemCount" : "itemCount").replace("{count}", String(count));
}
function navItem(page, ico, count = "") {
  return `<button type="button" class="nav-button" data-page="${page}" ${view().page === page ? 'aria-current="page"' : ""}>${icon(ico)}<span>${t(page)}</span>${count !== "" ? `<span class="nav-counter">${count}</span>` : ""}</button>`;
}
function renderSidebar(captureScroll = true) {
  const v = view(),
    run = currentRun(),
    c = counts();
  $("#workspace-nav").innerHTML =
    navItem("current", "focus", `${c.total ? Math.round((c.done / c.total) * 100) : 0}%`) +
    navItem("tasks", "table", formatItemCount(taskRecords().length));
  $("#memory-nav").innerHTML =
    navItem("records", "search") + navItem("memories", "book");
  const folds = $("#record-folds");
  const previous = views.get(folds.dataset.run);
  if (previous && captureScroll)
    folds.querySelectorAll(".fold-list:not([hidden])").forEach((list) => {
      previous.foldScrolls[list.id] = list.scrollTop;
    });
  folds.dataset.run = state.run;
  folds.innerHTML = ["PLAN", "TASK", "FINDING"]
    .map((kind) => {
      const items = runRecords(run, kind),
        open = v.openKind === kind;
      return `<section class="record-fold ${open ? "is-open" : ""}"><button id="fold-${kind}" class="fold-trigger" type="button" data-fold="${kind}" aria-expanded="${open}" aria-controls="list-${kind}">${icon("chevron").replace('class="icon"', 'class="icon fold-chevron"')}${icon(kind === "PLAN" ? "folder" : "file")}<span>${kind}</span><span class="fold-count">${formatItemCount(items.length)}</span></button><div class="fold-list" id="list-${kind}" role="region" aria-labelledby="fold-${kind}" ${open ? "" : "hidden"}>${items.map((r) => `<button type="button" data-record="${r.uid}" ${v.page === "record" && v.record === r.uid ? 'aria-current="true"' : ""}><span class="record-code"><span class="status ${statusColors[r.status]}" aria-hidden="true"></span>${r.id}</span><span class="record-label">${esc(tr(r.title))}</span></button>`).join("") || `<p class="fold-empty">${t("noRecords")}</p>`}</div></section>`;
    })
    .join("");
  folds.querySelectorAll(".fold-list:not([hidden])").forEach((list) => {
    list.scrollTop = v.foldScrolls[list.id] || 0;
  });
  $("#discard-open").disabled = !canDiscard(run);
  $("#discard-open").title = t(
    canDiscard(run) ? "permissionOwn" : "permissionOther",
  );
  $("#permission-note").hidden = canDiscard(run);
  $("#permission-note").textContent = t("readOnly");
  $("#sidebar").setAttribute("aria-label", t("navigation"));
}
function applyCopy() {
  document.documentElement.lang = state.locale;
  document.documentElement.dataset.theme = state.theme;
  document
    .querySelectorAll("[data-i18n]")
    .forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document
    .querySelectorAll("[data-icon]")
    .forEach((el) => (el.innerHTML = icon(el.dataset.icon)));
  $("#locale").value = state.locale;
  $("#theme-toggle").innerHTML =
    icon(state.theme === "light" ? "moon" : "sun") +
    `<span class="sr-only">${t("theme")}</span>`;
  $("#discard-x").setAttribute("aria-label", t("close"));
  $("#discard-backdrop").setAttribute("aria-label", t("close"));
}
function renderPage() {
  const page = view().page;
  $("#page-content").innerHTML =
    page === "tasks"
      ? tasksPage()
      : page === "record"
        ? recordPage()
        : page === "records"
          ? recordsPage()
          : page === "memories"
            ? memoriesPage()
            : currentPage();
  $("#page-content").dataset.run = state.run;
  $("#page-content").dataset.page = view().page;
}
function syncUrl() {
  const params = new URLSearchParams({
    run: state.run,
    page: view().page,
    lang: state.locale,
    theme: state.theme,
  });
  if (view().page === "record" && view().record)
    params.set("record", view().record);
  history.replaceState(null, "", `#${params}`);
}
function focusToken() {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const keys = [
    "id",
    "data-run",
    "data-page",
    "data-fold",
    "data-record",
    "data-filter",
    "data-group",
    "data-memory",
    "data-focus",
    "name",
  ];
  const key = keys.find((x) => el.hasAttribute(x));
  return key
    ? {
        key,
        value: el.getAttribute(key),
        zone: el.closest("#sidebar")
          ? "#sidebar"
          : el.closest("#page-content")
            ? "#page-content"
            : "#topbar",
        position: el.selectionStart,
      }
    : null;
}
function restoreFocus(token) {
  if (!token) return;
  const zone = $(token.zone);
  const next = [...zone.querySelectorAll(`[${token.key}]`)].find(
    (el) => el.getAttribute(token.key) === token.value,
  );
  if (next) {
    next.focus({ preventScroll: true });
    if (next.tagName === "INPUT" && typeof token.position === "number")
      next.setSelectionRange(token.position, token.position);
  }
}
function render(options = {}) {
  finishFoldMotion();
  finishDisclosures();
  pageMotions.forEach((handle) => handle?.cancel());
  pageMotions = [];
  const token = focusToken();
  const scroll = $("#page-scroll").scrollTop;
  if (options.captureSearch !== false) {
    const content = $("#page-content");
    const previous = views.get(content.dataset.run);
    const groups = content.querySelectorAll("details[data-search-run]");
    if (previous && content.dataset.page === "records" && groups.length) {
      previous.searchOpen = [...groups]
        .filter((group) => group.open)
        .map((group) => group.dataset.searchRun);
    }
  }
  applyCopy();
  renderTabs();
  renderSidebar(options.captureSidebar !== false);
  renderPage();
  syncResponsiveMenu();
  $("#page-scroll").scrollTop = options.resetScroll ? 0 : scroll;
  syncUrl();
  if (options.focusPage) $("#page-content").focus({ preventScroll: true });
  else restoreFocus(token);
  animatePage(options.motion);
}
function syncResponsiveMenu() {
  const compact = window.matchMedia("(max-width: 800px)").matches;
  $("#sidebar").inert = compact && !state.menuOpen;
  $("#sidebar-scrim").hidden = !compact || !state.menuOpen;
}
function closeMenu() {
  state.menuOpen = false;
  $("#workbench").classList.remove("menu-open");
  $("#sidebar-scrim").hidden = true;
  $("#menu-toggle").setAttribute("aria-expanded", "false");
  syncResponsiveMenu();
}
function rememberPage() {
  finishFoldMotion();
  finishDisclosures();
  const saved = structuredClone(view());
  $("#record-folds")
    .querySelectorAll(".fold-list:not([hidden])")
    .forEach((list) => (saved.foldScrolls[list.id] = list.scrollTop));
  if (saved.page === "records")
    saved.searchOpen = [...document.querySelectorAll("details[data-search-run][open]")]
      .map((group) => group.dataset.searchRun);
  navigationTrail.push({
    run: state.run,
    view: saved,
    scroll: $("#page-scroll").scrollTop,
    focus: focusToken(),
  });
}
function goBack() {
  if (!navigationTrail.length) return;
  finishFoldMotion();
  finishDisclosures();
  const previous = navigationTrail.pop();
  state.run = previous.run;
  views.set(state.run, previous.view);
  closeMenu();
  render({
    resetScroll: true,
    focusPage: true,
    captureSearch: false,
    captureSidebar: false,
    motion: "page",
  });
  $("#page-scroll").scrollTop = previous.scroll;
  restoreFocus(previous.focus);
  $(`#tab-${state.run}`).scrollIntoView({ block: "nearest", inline: "nearest" });
  announce(t("returned"));
}
function navigate(page, remember = false) {
  if (remember && view().page !== page) rememberPage();
  else if (!remember) navigationTrail.length = 0;
  view().page = page;
  closeMenu();
  render({ resetScroll: true, focusPage: true, motion: "page" });
  announce(t("navigationChanged"));
}
function switchRun(key, focusTab = false) {
  if (!runs.some((r) => r.key === key)) return;
  navigationTrail.length = 0;
  view().scrolls[view().page] = $("#page-scroll").scrollTop;
  state.run = key;
  closeMenu();
  render({ resetScroll: true, motion: "page" });
  $("#page-scroll").scrollTop = view().scrolls[view().page] || 0;
  if (focusTab) $(`#tab-${key}`).focus({ preventScroll: true });
  $(`#tab-${key}`).scrollIntoView({ block: "nearest", inline: "nearest" });
  announce(`${currentRun().id} · ${tr(currentRun().title)}`);
}
function openRecord(uid) {
  const record = getRecord(uid);
  if (!record || (view().page === "record" && view().record === uid)) return;
  rememberPage();
  state.run = record.runKey;
  view().page = "record";
  view().record = uid;
  view().openKind = record.kind;
  closeMenu();
  render({ resetScroll: true, focusPage: true, motion: "page" });
  const list = $(`#list-${record.kind}`);
  const selected = [...list.querySelectorAll("[data-record]")].find(
    (element) => element.dataset.record === uid,
  );
  if (selected) {
    const itemBounds = selected.getBoundingClientRect();
    const listBounds = list.getBoundingClientRect();
    if (itemBounds.top < listBounds.top)
      list.scrollTop += itemBounds.top - listBounds.top;
    else if (itemBounds.bottom > listBounds.bottom)
      list.scrollTop += itemBounds.bottom - listBounds.bottom;
  }
  $(`#tab-${state.run}`).scrollIntoView({
    block: "nearest",
    inline: "nearest",
  });
}
function announce(text) {
  $("#live-region").textContent = text;
}
let discardRun = null,
  toastTimer;
function openDiscard() {
  const run = currentRun();
  if (!canDiscard(run)) return;
  discardRun = run;
  $("#discard-context").innerHTML =
    `<p>${t(runRecords().length ? "discardRecords" : "discardEmpty")}</p><p style="margin-top:8px">${t("discardProcess")}</p><div class="discard-summary"><span class="mono micro muted">${run.id} · ${esc(run.source)}</span><strong>${esc(tr(run.title))}</strong><p>${runRecords().length} ${t("recordCount")} · ${t(run.owner)}</p></div>`;
  $("#discard-id").value = "";
  $("#discard-id").placeholder = run.id;
  $("#discard-confirm").disabled = true;
  $("#discard-dialog").showModal();
  $("#discard-id").focus();
}
document.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  if (button.dataset.run) switchRun(button.dataset.run, true);
  else if (button.dataset.page)
    navigate(button.dataset.page, Boolean(button.closest("#page-content")));
  else if (button.dataset.fold) toggleExplore(button.dataset.fold);
  else if (button.dataset.record) openRecord(button.dataset.record);
  else if (button.dataset.filter) {
    view().filter = button.dataset.filter;
    render({ motion: "list" });
    announce(`${t("resultCount")} ${filteredTasks().length}`);
  } else if (button.dataset.group) {
    view().group = button.dataset.group;
    render({ motion: "list" });
    announce(t(button.dataset.group === "run" ? "grouped" : "flat"));
  } else if (button.dataset.memory) {
    view().memory = button.dataset.memory;
    render();
    tween(
      $("#memory-source"),
      [
        { opacity: 0, transform: "translateY(4px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      220,
    );
    $("#memory-source").focus({ preventScroll: true });
    $("#memory-source").scrollIntoView({ block: "start" });
  } else if (button.dataset.reset) {
    const key = button.dataset.reset;
    view()[
      key === "tasks"
        ? "taskQuery"
        : key === "memories"
          ? "memoryQuery"
          : "query"
    ] = "";
    if (key === "tasks") view().filter = "all";
    render();
    $("#page-content input")?.focus({ preventScroll: true });
  } else if (button.id === "page-back") goBack();
  else if (button.id === "theme-toggle") {
    document.documentElement.classList.add("theme-swapping");
    state.theme = state.theme === "light" ? "dark" : "light";
    render();
    tween(
      $("#theme-toggle .icon"),
      [
        { opacity: 0, transform: "rotate(-35deg)" },
        { opacity: 1, transform: "rotate(0deg)" },
      ],
      220,
    );
    requestAnimationFrame(() =>
      requestAnimationFrame(() =>
        document.documentElement.classList.remove("theme-swapping"),
      ),
    );
  } else if (button.id === "menu-toggle") {
    state.menuOpen = !state.menuOpen;
    $("#workbench").classList.toggle("menu-open", state.menuOpen);
    $("#sidebar-scrim").hidden = !state.menuOpen;
    button.setAttribute("aria-expanded", String(state.menuOpen));
    syncResponsiveMenu();
    if (state.menuOpen) $("#sidebar .nav-button").focus();
  } else if (button.id === "discard-open") openDiscard();
  else if (button.id === "discard-cancel") $("#discard-dialog").close();
  else if (
    button.id === "discard-confirm" &&
    canDiscard(discardRun) &&
    $("#discard-id").value === discardRun.id
  ) {
    $("#discard-dialog").close();
    $("#toast-text").textContent = t("discardToast");
    $("#toast").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => ($("#toast").hidden = true), 5500);
  }
});
document.addEventListener("submit", (event) => {
  const form = event.target.closest("[data-form]");
  if (!form) return;
  event.preventDefault();
  const query = String(new FormData(form).get("query") || "");
  view()[
    form.dataset.form === "tasks"
      ? "taskQuery"
      : form.dataset.form === "memories"
        ? "memoryQuery"
        : "query"
  ] = query;
  render();
  announce(t("searchUpdated"));
});
$("#locale").addEventListener("change", (event) => {
  state.locale = event.target.value;
  render();
  announce(state.locale === "ko" ? "한국어 화면" : "English interface");
});
document.addEventListener("change", (event) => {
  if (event.target.id === "search-scope") {
    view().scope = event.target.value;
    view().searchOpen = event.target.value === "current" ? [state.run] : [];
    render({ captureSearch: false });
    announce(t("searchUpdated"));
  }
});
$("#discard-id").addEventListener(
  "input",
  (event) =>
    ($("#discard-confirm").disabled =
      !canDiscard(discardRun) || event.target.value !== discardRun.id),
);
$("#sidebar-scrim").addEventListener("click", () => {
  closeMenu();
  $("#menu-toggle").focus();
});
$("#run-tabs").addEventListener("keydown", (event) => {
  if (!event.target.matches("[data-run]")) return;
  let index = runs.findIndex((r) => r.key === state.run);
  if (event.key === "ArrowRight") index = (index + 1) % runs.length;
  else if (event.key === "ArrowLeft")
    index = (index + runs.length - 1) % runs.length;
  else if (event.key === "Home") index = 0;
  else if (event.key === "End") index = runs.length - 1;
  else return;
  event.preventDefault();
  switchRun(runs[index].key, true);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.menuOpen) {
    closeMenu();
    $("#menu-toggle").focus();
  }
});
$("#discard-dialog").addEventListener("close", () =>
  $("#discard-open").focus({ preventScroll: true }),
);
document.addEventListener(
  "toggle",
  (event) => {
    const details = event.target;
    if (!details.matches?.("details[data-search-run]") || !details.isConnected)
      return;
    if (disclosureState.has(details)) return;
    const key = details.dataset.searchRun;
    view().searchOpen = details.open
      ? [...new Set([...view().searchOpen, key])]
      : view().searchOpen.filter((item) => item !== key);
  },
  true,
);
window.addEventListener("resize", syncResponsiveMenu);
const initial = new URLSearchParams(location.hash.slice(1));
if (runs.some((r) => r.key === initial.get("run")))
  state.run = initial.get("run");
if (["ko", "en"].includes(initial.get("lang")))
  state.locale = initial.get("lang");
if (["light", "dark"].includes(initial.get("theme")))
  state.theme = initial.get("theme");
if (["current", "tasks", "records", "memories"].includes(initial.get("page")))
  view().page = initial.get("page");
if (initial.get("page") === "record") {
  const item = getRecord(initial.get("record"));
  if (item && item.runKey === state.run) {
    view().record = item.uid;
    view().page = "record";
    view().openKind = item.kind;
  }
}
render();
