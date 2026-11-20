import { useEffect, useRef, useState, type RefObject } from 'react';
import { useBrowserLayoutEffect } from './effects';
import type { RunDiscardResult, TaplRunSnapshot, TaplWorkflowRun, WebviewCommand, WebviewView } from '../types';
import {
  createNavigation,
  navigate,
  pageState,
  patchPage,
  persistedNavigation,
  receiveView,
  routeIdentity,
  runKey,
  runsForView,
  snapshotForView,
  tabRuns,
  uniqueRuns,
  viewIdentity,
  type NavigationState,
  type PagePosition,
  type RunPageState,
  type WorkbenchPage,
  type WorkbenchRoute
} from './model';

export function expectedForCommand(command: WebviewCommand, targetRun?: TaplWorkflowRun): string | undefined {
  switch (command.command) {
    case 'selectRun':
      return targetRun ? `run:${runKey(targetRun)}` : 'overview';
    case 'openRun':
      return `run:${runKey({ id: command.runId, source_db: command.source_db })}`;
    case 'records':
      return JSON.stringify([
        'records',
        command.query ?? '',
        command.scope ?? 'all',
        command.runId ?? '',
        command.source_db ?? '',
        command.offset ?? 0
      ]);
    case 'openSearchResult':
      return JSON.stringify(['item', command.source_db ?? '', command.itemId]);
    case 'memories':
      return JSON.stringify(['memories', command.query ?? '', command.offset ?? 0]);
    case 'openMemory':
      return JSON.stringify(['memory', command.source_db ?? '', command.memoryId]);
    case 'openMemorySource':
      return JSON.stringify(['memorySource', command.source_db ?? '', command.memoryId]);
    case 'openArchive':
      return JSON.stringify(['archive', command.source_db ?? '', command.archiveId]);
    case 'archiveEvents':
      return JSON.stringify(['archiveEvents', command.source_db ?? '', command.archiveId]);
    case 'search':
      return JSON.stringify(['search', command.query]);
    case 'debug':
      return 'debug';
    case 'chooseWorkspace':
      return 'workspace';
    default:
      return undefined;
  }
}
export function commandForRun(run: TaplWorkflowRun, active: TaplWorkflowRun[]): WebviewCommand | undefined {
  if (!run.id) return undefined;
  return typeof run.session_id === 'string' && active.some((candidate) => runKey(candidate) === runKey(run))
    ? {
        command: 'selectRun',
        sessionId: run.session_id,
        source_db: run.source_db
      }
    : { command: 'openRun', runId: run.id, source_db: run.source_db };
}

function reportsArchive(view: WebviewView, snapshot: TaplRunSnapshot | undefined, key: string): boolean {
  if (!key) return false;
  if (snapshot?.run.status === 'archived' && runKey(snapshot.run) === key) return true;
  if (view.type === 'overview') {
    return view.archives.some(archive => runKey({ id: archive.run_id, source_db: archive.source_db }) === key);
  }
  return view.type === 'records' && view.runs.some(run => run.status === 'archived' && runKey(run) === key);
}
function positionForPage(page: HTMLElement | null): PagePosition {
  const focused = document.activeElement as HTMLElement | null;
  const focus = focused?.closest<HTMLElement>('[data-wb-focus]')?.dataset.wbFocus;
  const selection =
    focused instanceof HTMLInputElement && !['number', 'email'].includes(focused.type)
      ? ([focused.selectionStart, focused.selectionEnd] as [number | null, number | null])
      : undefined;
  return {
    top: page?.scrollTop ?? 0,
    tracks: Object.fromEntries(
      [...(page?.querySelectorAll<HTMLElement>('[data-wb-track]') ?? [])].map((track) => [
        track.dataset.wbTrack!,
        track.scrollLeft
      ])
    ),
    focus,
    selection
  };
}

export function useWorkbench({
  view,
  send,
  discardResult,
  initialState,
  onStateChange,
  pageRef,
  sidebarRef
}: {
  view: WebviewView;
  send: (command: WebviewCommand) => void;
  discardResult?: RunDiscardResult;
  initialState?: unknown;
  onStateChange?: (state: unknown) => void;
  pageRef: RefObject<HTMLElement>;
  sidebarRef: RefObject<HTMLElement>;
}) {
  const [state, setState] = useState(() => createNavigation(view, initialState));
  const stateRef = useRef(state);
  const initialSnapshot = snapshotForView(view);
  const [snapshots, setSnapshots] = useState<Record<string, TaplRunSnapshot>>(() =>
    initialSnapshot ? { [runKey(initialSnapshot.run)]: initialSnapshot } : {}
  );
  const [activeRuns, setActiveRuns] = useState<TaplWorkflowRun[]>(
    () => runsForView(view) ?? (initialSnapshot && !initialSnapshot.readonly ? [initialSnapshot.run] : [])
  );
  const [knownRuns, setKnownRuns] = useState<TaplWorkflowRun[]>(() => (initialSnapshot ? [initialSnapshot.run] : []));
  const [restore, setRestore] = useState(0);
  const visited = useRef(new Map<string, WorkbenchRoute>());
  const returnRoute = useRef<WorkbenchRoute>();
  const retainedArchive = useRef<TaplWorkflowRun>();
  const afterRun = useRef<{
    expected: string;
    route: WorkbenchRoute;
    command: WebviewCommand;
  }>();
  const stateChangeRef = useRef(onStateChange);
  stateChangeRef.current = onStateChange;
  const update = (fn: (current: NavigationState) => NavigationState) => {
    const next = fn(stateRef.current);
    stateRef.current = next;
    setState(next);
  };
  useEffect(() => {
    const snapshot = snapshotForView(view);
    if (snapshot)
      setSnapshots((current) => ({
        ...current,
        [runKey(snapshot.run)]: snapshot
      }));
    const inventory = runsForView(view);
    if (inventory) setActiveRuns(inventory);
    setKnownRuns((current) =>
      uniqueRuns([
        ...current,
        ...(inventory ?? []),
        ...(view.type === 'records' ? view.runs : []),
        ...(snapshot ? [snapshot.run] : []),
        ...(view.type === 'memorySource' ? [view.run] : [])
      ])
    );
    const current = stateRef.current;
    const identity = viewIdentity(view);
    const key = current.route.runKey;
    const former = snapshots[key]?.run ?? activeRuns.find(run => runKey(run) === key);
    const discarded = discardResult?.ok && discardResult.runId === former?.id;
    // A delayed response for another route must not take over navigation.
    const mayRetain = !current.pending ||
      [identity, `run:${key}`].includes(current.pending.expected);
    const justArchived = mayRetain && former?.status === 'active' && !discarded && reportsArchive(view, snapshot, key);
    if (runKey(retainedArchive.current) !== key) retainedArchive.current = undefined;
    if (justArchived) retainedArchive.current = former;
    const retained = retainedArchive.current;
    if (retained?.id && mayRetain) {
      if (inventory?.some(run => runKey(run) === key)) {
        setActiveRuns(inventory.filter(run => runKey(run) !== key));
      }
      const successor = typeof retained.session_id === 'string' && inventory?.find(run =>
        run.status === 'active' && run.session_id === retained.session_id &&
        run.source_db === retained.source_db && runKey(run) !== key
      );
      if (successor) {
        retainedArchive.current = undefined;
        afterRun.current = undefined;
        const route = { page: 'current' as const, runKey: runKey(successor) };
        if (snapshot && runKey(snapshot.run) === route.runKey) {
          update(state => ({ ...navigate(state, route, false), hostIdentity: identity }));
        } else {
          const command = commandForRun(successor, inventory ?? []);
          update(state => navigate(state, route, false, command && expectedForCommand(command, successor)));
          if (command) send(command);
        }
        setRestore(value => value + 1);
        return;
      }
      if (justArchived) {
        afterRun.current = undefined;
        const route = { page: 'current' as const, runKey: key };
        if (snapshot?.run.status === 'archived' && runKey(snapshot.run) === key) {
          update(state => ({ ...navigate(state, route, false), hostIdentity: identity }));
        } else {
          const archived = { ...retained, status: 'archived', writable: false };
          setKnownRuns(runs => uniqueRuns([...runs, archived]));
          setSnapshots(snapshots => {
            const previous = snapshots[key];
            return previous ? { ...snapshots, [key]: { ...previous, readonly: true, run: archived } } : snapshots;
          });
          const command = { command: 'openRun' as const, runId: retained.id, source_db: retained.source_db };
          update(state => navigate(state, route, false, expectedForCommand(command)));
          send(command);
        }
        setRestore(value => value + 1);
        return;
      }
      // An overview may pick a different concurrently active owner when the
      // selected owner has no RUN. Keep the archive until an actual switch.
      if (!current.pending && view.type === 'overview') return;
    }
    update((state) => receiveView(state, view));
    const followUp = afterRun.current;
    if (followUp && identity === followUp.expected) {
      afterRun.current = undefined;
      update((current) => navigate(current, followUp.route, 'replace', expectedForCommand(followUp.command)));
      send(followUp.command);
    } else if (view.type === 'error') afterRun.current = undefined;
  }, [view]);
  useEffect(() => stateChangeRef.current?.(persistedNavigation(state)), [state.pages]);

  const capture = () =>
    update((current) => {
      visited.current.set(current.route.runKey, current.route);
      if (!current.route.runKey || tabRuns(activeRuns, undefined).some((run) => runKey(run) === current.route.runKey))
        returnRoute.current = current.route;
      const saved = pageState(current);
      return patchPage(current, {
        positions: {
          ...saved.positions,
          [routeIdentity(current.route)]: positionForPage(pageRef.current)
        },
        sidebarScroll: sidebarRef.current?.scrollTop ?? saved.sidebarScroll
      });
    });
  const changePage = (patch: Partial<RunPageState>, key?: string) =>
    update((current) => patchPage(current, patch, key));
  const go = (
    route: WorkbenchRoute,
    command?: WebviewCommand,
    internal: boolean | 'replace' = false,
    targetRun?: TaplWorkflowRun
  ) => {
    afterRun.current = undefined;
    if (runKey(retainedArchive.current) !== route.runKey) retainedArchive.current = undefined;
    capture();
    update((current) => navigate(current, route, internal, command && expectedForCommand(command, targetRun)));
    setRestore((value) => value + 1);
    if (command) send(command);
  };
  const selectedRun = snapshots[state.route.runKey]?.run ?? knownRuns.find((run) => runKey(run) === state.route.runKey);
  const snapshot = snapshots[state.route.runKey];
  const requestForRoute = (route: WorkbenchRoute): WebviewCommand | undefined => {
    const run = snapshots[route.runKey]?.run ?? knownRuns.find((candidate) => runKey(candidate) === route.runKey);
    if (route.page === 'records' && route.view?.type === 'records') {
      const previous = route.view;
      return {
        command: 'records',
        query: previous.query,
        scope: previous.scope,
        runId: previous.runId,
        source_db: previous.source_db,
        offset: previous.offset,
        limit: previous.limit
      };
    }
    const legacy = route.view;
    if (legacy?.type === 'memories')
      return {
        command: 'memories',
        query: legacy.query,
        offset: legacy.offset
      };
    if (legacy?.type === 'memory')
      return {
        command: 'openMemory',
        memoryId: legacy.memoryId,
        source_db: legacy.source_db
      };
    if (legacy?.type === 'memorySource')
      return {
        command: 'openMemorySource',
        memoryId: legacy.memoryId,
        source_db: legacy.source_db
      };
    if (legacy?.type === 'searchItem' && legacy.result.id != null)
      return {
        command: 'openSearchResult',
        itemId: legacy.result.id,
        source_db: legacy.result.source_db
      };
    if (legacy?.type === 'archive' || legacy?.type === 'archiveEvents')
      return {
        command: legacy.type === 'archive' ? 'openArchive' : 'archiveEvents',
        archiveId: legacy.archive.id,
        source_db: legacy.archive.source_db
      };
    return run ? commandForRun(run, activeRuns) : undefined;
  };
  const switchRun = (run: TaplWorkflowRun) => {
    const key = runKey(run);
    if (key === stateRef.current.route.runKey) return;
    const command = commandForRun(run, activeRuns);
    const saved = key === stateRef.current.route.runKey ? stateRef.current.route : visited.current.get(key);
    const route = saved?.page !== 'management' && saved ? saved : { page: 'current' as const, runKey: key };
    const followUp = ['records', 'memories', 'legacy'].includes(route.page) ? requestForRoute(route) : undefined;
    const nextFollowUp =
      command && followUp && followUp.command !== 'selectRun' && followUp.command !== 'openRun'
        ? {
            expected: expectedForCommand(command, run)!,
            route,
            command: followUp
          }
        : undefined;
    go(route, command, false, run);
    afterRun.current = nextFollowUp;
  };
  const restoreRoute = (route: WorkbenchRoute, trail: WorkbenchRoute[]) => {
    afterRun.current = undefined;
    if (runKey(retainedArchive.current) !== route.runKey) retainedArchive.current = undefined;
    capture();
    const command: WebviewCommand | undefined = requestForRoute(route) ??
      (route.page === 'records' ? { command: 'records', scope: 'all' } : undefined);
    const run = snapshots[route.runKey]?.run ?? knownRuns.find((candidate) => runKey(candidate) === route.runKey);
    update((current) => navigate({ ...current, trail }, route, 'replace', command && expectedForCommand(command, run)));
    setRestore((value) => value + 1);
    if (command) send(command);
  };
  const goBack = () => {
    const { trail } = stateRef.current;
    const previous = trail[trail.length - 1];
    if (previous) restoreRoute(previous, trail.slice(0, -1));
  };
  const openCurrentRun = (selection?: TaplWorkflowRun) => go({ page: 'current', runKey: '' }, {
    command: 'selectRun', sessionId: selection?.session_id ?? '', source_db: selection?.source_db
  });
  const closeTemporaryRun = () => {
    const current = stateRef.current;
    const regularRuns = tabRuns(activeRuns, undefined);
    const regularRoute = (route: WorkbenchRoute) =>
      !route.runKey || regularRuns.some((run) => runKey(run) === route.runKey);
    if (!current.route.runKey || regularRoute(current.route)) return;
    if (!regularRuns.length && runKey(retainedArchive.current) === current.route.runKey) {
      openCurrentRun(retainedArchive.current);
      return;
    }
    // Skip details belonging to the temporary RUN so closing cannot reopen it.
    let index = current.trail.length - 1;
    while (index >= 0 && !regularRoute(current.trail[index])) index--;
    const previous = current.trail[index];
    const origin = returnRoute.current;
    const fallback = regularRuns[0];
    const route: WorkbenchRoute = previous ?? (origin && regularRoute(origin) ? origin : undefined) ??
      (fallback
        ? visited.current.get(runKey(fallback)) ?? { page: 'current', runKey: runKey(fallback) }
        : { page: 'records', runKey: '' });
    restoreRoute(
      route,
      index >= 0 ? current.trail.slice(0, index).filter((entry) => entry.runKey !== current.route.runKey) : []
    );
  };
  const selectPage = (page: WorkbenchPage) => {
    afterRun.current = undefined;
    const current = stateRef.current;
    const prefs = pageState(current);
    const key = current.route.runKey;
    if (page === 'records') {
      const command: WebviewCommand = {
        command: 'records',
        query: prefs.query,
        scope: prefs.scope,
        runId: prefs.scope === 'run' ? selectedRun?.id : undefined,
        source_db: prefs.scope === 'run' ? selectedRun?.source_db : undefined
      };
      go(
        {
          page,
          runKey: key,
          view: current.route.page === 'records' ? current.route.view : undefined
        },
        command
      );
    } else if (page === 'memories') go({ page, runKey: key }, { command: 'memories' });
    else if (page === 'current' && !selectedRun && current.route.page !== 'current') openCurrentRun(activeRuns[0]);
    else go({ page, runKey: key }, selectedRun && commandForRun(selectedRun, activeRuns), false, selectedRun);
  };
  const wrappedSend = (command: WebviewCommand) => {
    if (command.command === 'back' && stateRef.current.trail.length) {
      goBack();
      return;
    }
    const expected = expectedForCommand(command);
    if (!expected) {
      send(command);
      return;
    }
    let key = stateRef.current.route.runKey;
    let page: WorkbenchPage = 'legacy';
    if (command.command === 'openRun') {
      key = runKey({ id: command.runId, source_db: command.source_db });
      page = 'current';
    } else if (command.command === 'memories' || command.command === 'openMemory') page = 'memories';
    else if (command.command === 'records') page = 'records';
    const sameList =
      (command.command === 'memories' && stateRef.current.route.page === 'memories') ||
      (command.command === 'records' && stateRef.current.route.page === 'records');
    go({ page, runKey: key }, command, sameList ? 'replace' : true);
  };
  const routeKey = routeIdentity(state.route);
  useBrowserLayoutEffect(() => {
    const saved = pageState(stateRef.current).positions[routeIdentity(stateRef.current.route)];
    const page = pageRef.current;
    if (!page) return;
    page.scrollTop = saved?.top ?? 0;
    page.querySelectorAll<HTMLElement>('[data-wb-track]').forEach((track) => {
      track.scrollLeft = saved?.tracks[track.dataset.wbTrack!] ?? 0;
    });
    if (sidebarRef.current) sidebarRef.current.scrollTop = pageState(stateRef.current).sidebarScroll;
    const target =
      saved?.focus &&
      [...document.querySelectorAll<HTMLElement>('.tapl-workbench [data-wb-focus]')].find(
        (element) => element.dataset.wbFocus === saved.focus
      );
    if (target) {
      target.focus({ preventScroll: true });
      if (target instanceof HTMLInputElement && saved?.selection) target.setSelectionRange(...saved.selection);
    } else if (restore > 0) page.querySelector<HTMLElement>('[data-wb-page-heading]')?.focus({ preventScroll: true });
  }, [routeKey, restore]);
  return {
    state,
    snapshot,
    selectedRun,
    activeRuns,
    knownRuns,
    prefs: pageState(state),
    go,
    goBack,
    closeTemporaryRun,
    selectPage,
    switchRun,
    changePage,
    capture,
    wrappedSend
  };
}
