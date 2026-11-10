import type { TaplItem, TaplRunSnapshot, TaplWorkflowRun, WebviewView } from '../types';

export const TASK_STATUSES = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped'] as const;
export type WorkbenchPage = 'current' | 'tasks' | 'records' | 'memories' | 'management' | 'legacy';
export interface PagePosition {
  top: number;
  tracks: Record<string, number>;
  focus?: string;
  selection?: [number | null, number | null];
}
export interface RunPageState {
  page: WorkbenchPage;
  taskFilter: string;
  taskQuery: string;
  query: string;
  scope: 'all' | 'run';
  group: 'run' | 'record';
  expanded: string[];
  positions: Record<string, PagePosition>;
  exploreScrolls: Record<string, number>;
  sidebarScroll: number;
}
export interface WorkbenchRoute {
  page: WorkbenchPage;
  runKey: string;
  view?: WebviewView;
}
export interface NavigationState {
  route: WorkbenchRoute;
  pages: Record<string, RunPageState>;
  trail: WorkbenchRoute[];
  hostIdentity: string;
  pending?: { expected: string; route: WorkbenchRoute };
}

/** JSON tuples avoid collisions when display IDs or database paths contain separators. */
export function runKey(run: Pick<TaplWorkflowRun, 'source_db' | 'id'> | undefined): string {
  return run?.id ? JSON.stringify([run.source_db ?? '', run.id]) : '';
}
export function recordRunKey(source: string | undefined, id: string): string {
  return runKey({ source_db: source, id });
}
export function runTitle(run: TaplWorkflowRun | undefined): string {
  return run?.request_summary?.trim() || run?.slug || run?.id || '';
}
export function isArchivedRun(run: TaplWorkflowRun): boolean {
  return /^(archived|discarded)$/i.test(run.status ?? '');
}
export function uniqueRuns(runs: TaplWorkflowRun[]): TaplWorkflowRun[] {
  return [...new Map(runs.filter((run) => run.id).map((run) => [runKey(run), run])).values()];
}
export function tabRuns(active: TaplWorkflowRun[], selected: TaplWorkflowRun | undefined): TaplWorkflowRun[] {
  const runs = uniqueRuns(active.filter((run) => !isArchivedRun(run)));
  return selected && !runs.some((run) => runKey(run) === runKey(selected)) ? [...runs, selected] : runs;
}
export function snapshotForView(view: WebviewView): TaplRunSnapshot | undefined {
  if (view.type === 'run') return view.snapshot;
  if (view.type === 'overview' || view.type === 'debug') {
    const status = view.status;
    if (!status.active_run) return undefined;
    return {
      run: {
        ...status.active_run,
        source_db: status.active_run.source_db ?? status.source_db
      },
      plans: status.plans,
      tasks: status.tasks,
      findings: status.findings,
      task_counts: status.task_counts,
      active_batches: status.active_batches ?? [],
      active_executions: status.active_executions ?? [],
      readonly: status.active_run.writable === false,
      active_runs: status.active_runs
    };
  }
  return 'context' in view ? view.context : undefined;
}
export function runsForView(view: WebviewView): TaplWorkflowRun[] | undefined {
  if (view.type === 'overview' || view.type === 'debug') return view.status.active_runs;
  if (view.type === 'run') return view.snapshot.active_runs;
  if ('active_runs' in view && view.active_runs) return view.active_runs;
  return snapshotForView(view)?.active_runs;
}
export function defaultRunPage(): RunPageState {
  return {
    page: 'current',
    taskFilter: 'all',
    taskQuery: '',
    query: '',
    scope: 'all',
    group: 'run',
    expanded: [],
    positions: {},
    exploreScrolls: {},
    sidebarScroll: 0
  };
}
export function pageState(state: NavigationState, key = state.route.runKey): RunPageState {
  return state.pages[key] ?? defaultRunPage();
}
export function patchPage(
  state: NavigationState,
  patch: Partial<RunPageState>,
  key = state.route.runKey
): NavigationState {
  return {
    ...state,
    pages: { ...state.pages, [key]: { ...pageState(state, key), ...patch } }
  };
}
export function viewIdentity(view: WebviewView): string {
  switch (view.type) {
    case 'overview':
    case 'run':
      return `run:${runKey(snapshotForView(view)?.run)}`;
    case 'records':
      return JSON.stringify(['records', view.query, view.scope, view.runId ?? '', view.source_db ?? '', view.offset]);
    case 'searchItem':
      return JSON.stringify([
        'item',
        view.result.source_db ?? view.detail?.source_db ?? '',
        view.detail?.id ?? view.result.id
      ]);
    case 'memory':
    case 'memorySource':
      return JSON.stringify([view.type, view.source_db ?? '', view.memoryId]);
    case 'memories':
      return JSON.stringify(['memories', view.query, view.offset]);
    case 'archive':
    case 'archiveEvents':
      return JSON.stringify([view.type, view.archive.source_db ?? '', view.archive.id]);
    case 'search':
      return JSON.stringify(['search', view.search.query]);
    case 'workspace':
      return 'workspace';
    case 'error':
      return JSON.stringify(['error', view.message]);
    default:
      return view.type;
  }
}
export function routeForView(view: WebviewView, fallbackKey = ''): WorkbenchRoute {
  const detailKey =
    view.type === 'searchItem' && view.detail?.run_id
      ? recordRunKey(view.detail.source_db ?? view.result.source_db, view.detail.run_id)
      : '';
  const key =
    view.type === 'overview' || view.type === 'run'
      ? runKey(snapshotForView(view)?.run)
      : runKey(snapshotForView(view)?.run) ||
        detailKey ||
        (view.type === 'memorySource' ? runKey(view.run) : '') ||
        fallbackKey;
  if (
    view.type === 'overview' ||
    view.type === 'run' ||
    ((view.type === 'memorySource' || view.type === 'archive') && view.context)
  )
    return { page: 'current', runKey: key };
  if (view.type === 'records') return { page: 'records', runKey: key, view };
  if (view.type === 'memories' || view.type === 'memory') return { page: 'memories', runKey: key, view };
  return { page: 'legacy', runKey: key, view };
}
export function routeIdentity(route: WorkbenchRoute): string {
  return JSON.stringify([route.runKey, route.page, route.view ? viewIdentity(route.view) : '']);
}
export function createNavigation(view: WebviewView, restored?: unknown): NavigationState {
  const value = restored as { version?: unknown; pages?: Record<string, Partial<RunPageState>> } | undefined;
  const pages: Record<string, RunPageState> = {};
  if (value?.version === 1 && value.pages && typeof value.pages === 'object') {
    for (const [key, page] of Object.entries(value.pages)) {
      if (page && typeof page === 'object')
        pages[key] = {
          ...defaultRunPage(),
          taskFilter: typeof page.taskFilter === 'string' ? page.taskFilter : 'all',
          taskQuery: typeof page.taskQuery === 'string' ? page.taskQuery : '',
          query: typeof page.query === 'string' ? page.query : '',
          scope: page.scope === 'run' ? 'run' : 'all',
          group: page.group === 'record' ? 'record' : 'run',
          expanded: Array.isArray(page.expanded) ? page.expanded.filter((v): v is string => typeof v === 'string') : []
        };
    }
  }
  let state: NavigationState = {
    route: routeForView(view),
    pages,
    trail: [],
    hostIdentity: viewIdentity(view)
  };
  if (view.type === 'records') state = patchPage(state, { query: view.query, scope: view.scope });
  return state;
}
/** Persist preferences only. A reload is a new visit and never resurrects a Back trail. */
export function persistedNavigation(state: NavigationState): unknown {
  return {
    version: 1,
    pages: Object.fromEntries(
      Object.entries(state.pages).map(([key, page]) => [
        key,
        {
          taskFilter: page.taskFilter,
          taskQuery: page.taskQuery,
          query: page.query,
          scope: page.scope,
          group: page.group,
          expanded: page.expanded
        }
      ])
    )
  };
}
export function navigate(
  state: NavigationState,
  route: WorkbenchRoute,
  internal: boolean | 'replace',
  expected?: string
): NavigationState {
  const next = {
    ...state,
    route,
    trail: internal === 'replace' ? state.trail : internal ? [...state.trail, state.route] : [],
    pending: expected ? { expected, route } : undefined
  };
  return patchPage(next, { page: route.page });
}
export function back(state: NavigationState, expected?: string): NavigationState {
  const route = state.trail[state.trail.length - 1];
  if (!route) return state;
  return {
    ...state,
    route,
    trail: state.trail.slice(0, -1),
    pending: expected ? { expected, route } : undefined
  };
}
/** Polling refreshes data, while explicit navigation owns the selected page. */
export function receiveView(state: NavigationState, view: WebviewView): NavigationState {
  const identity = viewIdentity(view);
  if (state.pending && view.type === 'error')
    return {
      ...state,
      route: { ...state.route, page: 'legacy', view },
      hostIdentity: identity,
      pending: undefined
    };
  const memoryItemSource = state.pending && matchesMemoryItemSource(state.pending.expected, view);
  if (state.pending && state.pending.expected !== identity && !memoryItemSource && view.type !== 'error') return state;
  if (state.pending && (state.pending.expected === identity || memoryItemSource)) {
    const desired = state.pending.route;
    const incoming = routeForView(view, desired.runKey);
    const page = (view.type === 'memorySource' || view.type === 'archive') && view.context ? 'current' : desired.page;
    // A RUN switch may first fetch its snapshot, then restore that RUN's library/detail page.
    const routeView = view.type === 'run' || view.type === 'overview' ? desired.view : view;
    const route = {
      ...desired,
      page,
      runKey: incoming.runKey,
      view: ['records', 'memories', 'legacy'].includes(page) ? routeView : undefined
    };
    return { ...state, route, pending: undefined, hostIdentity: identity };
  }
  if (identity === state.hostIdentity) {
    return state.route.view && viewIdentity(state.route.view) === identity
      ? { ...state, route: { ...state.route, view } }
      : state;
  }
  const route = routeForView(view, state.route.runKey);
  let next: NavigationState = {
    ...state,
    route,
    pending: undefined,
    hostIdentity: identity,
    trail: []
  };
  if (view.type === 'records')
    next = patchPage(next, {
      query: view.query,
      scope: view.scope,
      expanded: []
    });
  return next;
}
function matchesMemoryItemSource(expected: string, view: WebviewView): boolean {
  if (view.type !== 'searchItem') return false;
  let token: unknown;
  try {
    token = JSON.parse(expected);
  } catch {
    return false;
  }
  if (!Array.isArray(token) || token[0] !== 'memorySource') return false;
  const source = view.detail?.source_db ?? view.result.source_db;
  if (token[1] && token[1] !== source) return false;
  const context = view.context?.run;
  return !!context?.id && context.source_db === source && view.detail?.run_id === context.id;
}
export function taskCounts(snapshot: TaplRunSnapshot | undefined): {
  total: number;
  completed: number;
  percent: number;
  counts: Record<string, number>;
} {
  const counts =
    snapshot && Object.keys(snapshot.task_counts).length
      ? snapshot.task_counts
      : (snapshot?.tasks ?? []).reduce<Record<string, number>>((all, task) => {
          const status = task.status ?? '';
          all[status] = (all[status] ?? 0) + 1;
          return all;
        }, {});
  const total = Object.values(counts).reduce(
    (sum, count) => sum + (Number.isFinite(count) && count > 0 ? count : 0),
    0
  );
  const completed = Math.max(0, counts.Completed ?? 0);
  return {
    total,
    completed,
    percent: total ? Math.round((completed / total) * 100) : 0,
    counts
  };
}
export function filterTasks(tasks: TaplItem[], filter: string, query: string): TaplItem[] {
  const text = query.trim().toLocaleLowerCase();
  return tasks.filter(
    (task) =>
      (filter === 'all' || task.status === filter) &&
      (!text || `${task.stable_id} ${task.title} ${task.body ?? ''}`.toLocaleLowerCase().includes(text))
  );
}
export function itemSummary(item: TaplItem): string {
  const goal = item.custom_fields?.goal;
  const body = typeof goal === 'string' ? goal : (item.body ?? '');
  return body
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/[*_`]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 220);
}
