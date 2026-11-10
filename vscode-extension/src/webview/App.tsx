import { FormEvent, ReactNode, createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { resolveLocale, type SupportedLocale } from '../i18n';
import type {
  DisplayLayout,
  HostMessage,
  HostCapabilities,
  RunDiscardResult,
  TaplArchive,
  TaplArchiveDetail,
  TaplEvent,
  TaplExecutionTiming,
  TaplItem,
  TaplItemDetail,
  TaplJsonValue,
  TaplSearchPayload,
  TaplSearchResult,
  TaplStatus,
  TaplWorkflowRun,
  WebviewCommand,
  WebviewView
} from './types';
import { vscodeApi } from './vscodeApi';
import { I18nProvider, useI18n } from './i18n';
import { MemoryView } from './MemoryView';
import { Workbench } from './workbench';
import { Icon as WorkbenchIcon } from './workbench/Icon';
import { formatExecutionTiming, isRunningExecutionTiming, type FormattedExecutionTiming } from './executionTiming';

const ExecutionClockContext = createContext(0);

function viewHasRunningTiming(view: WebviewView | undefined): boolean {
  if (view?.type === 'overview') {
    return view.status.tasks.some((item) => isRunningExecutionTiming(item.execution_timing, item.status));
  }
  if (view?.type === 'archive') {
    return view.detail?.items.some((item) => isRunningExecutionTiming(item.execution_timing, item.status)) ?? false;
  }
  if (view?.type === 'searchItem') {
    return isRunningExecutionTiming(view.detail?.execution_timing, view.detail?.status);
  }
  return false;
}

const TASK_STATUSES = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped'];
const DEFAULT_TASK_COUNTS: Record<string, number> = {
  Pending: 0,
  'In Progress': 0,
  Blocked: 0,
  Completed: 0,
  Skipped: 0
};

function resolveDisplayLayout(value: unknown): DisplayLayout {
  return value === 'small' || value === 'medium' || value === 'large' ? value : 'auto';
}

interface PersistedAppState {
  view?: WebviewView;
  locale?: SupportedLocale;
  hostLocale?: SupportedLocale;
  userLocale?: SupportedLocale;
  layout?: unknown;
  capabilities?: HostCapabilities;
  workspace?: string;
  workbench?: unknown;
  workbenchWorkspace?: string;
}
function savedTheme(state: unknown): unknown {
  const theme = state && typeof state === 'object' ? (state as { theme?: unknown }).theme : undefined;
  return {
    version: 1,
    theme: theme === 'light' || theme === 'dark' ? theme : undefined
  };
}
export function App(): JSX.Element {
  const api = vscodeApi();
  const restored = api.getState() as PersistedAppState | undefined;
  const [memorySupported, setMemorySupported] = useState(restored?.capabilities?.associativeMemory === true);
  const [discardSupported, setDiscardSupported] = useState(restored?.capabilities?.discardRun === true);
  const [discardResult, setDiscardResult] = useState<RunDiscardResult>();
  const [view, setView] = useState<WebviewView | undefined>(restored?.view);
  const userLocale = useRef<SupportedLocale | undefined>(restored?.userLocale);
  const hostLocale = useRef<SupportedLocale | undefined>(restored?.hostLocale);
  const [locale, setLocale] = useState<SupportedLocale>(() =>
    resolveLocale(
      restored?.userLocale ??
        restored?.locale ??
        (typeof document === 'undefined' ? 'en' : document.documentElement.lang || navigator.language)
    )
  );
  const [layout, setLayout] = useState<DisplayLayout>(() => resolveDisplayLayout(restored?.layout));
  const [workspace, setWorkspace] = useState(restored?.workspace);
  const workspaceRef = useRef(workspace);
  const [workbenchSeed, setWorkbenchSeed] = useState(() =>
    restored?.workbenchWorkspace && restored.workbenchWorkspace !== restored.workspace
      ? savedTheme(restored.workbench)
      : restored?.workbench
  );
  const [nowMs, setNowMs] = useState(Date.now);
  const hasRunningTiming = viewHasRunningTiming(view);
  const persist = (values: Partial<PersistedAppState>) => {
    const previous = api.getState();
    api.setState({
      ...(previous && typeof previous === 'object' ? previous : {}),
      ...values
    });
  };

  useEffect(() => {
    if (!hasRunningTiming) return;
    setNowMs(Date.now());
    const interval = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [hasRunningTiming]);

  useEffect(() => {
    const listener = (event: MessageEvent<HostMessage>) => {
      const message = event.data;
      if (!message || typeof message.type !== 'string') return;
      if (message.type === 'hydrate' || message.type === 'view:update') {
        const receivedLocale = resolveLocale(message.locale);
        if (hostLocale.current && hostLocale.current !== receivedLocale) userLocale.current = undefined;
        hostLocale.current = receivedLocale;
        const nextLocale = userLocale.current ?? receivedLocale;
        const nextLayout = resolveDisplayLayout(message.layout);
        const nextWorkspace =
          message.workspace ??
          ('workspace' in message.view ? message.view.workspace : undefined) ??
          workspaceRef.current;
        const state = api.getState() as PersistedAppState | undefined;
        const workspaceChanged = nextWorkspace !== workspaceRef.current;
        if (workspaceChanged) {
          workspaceRef.current = nextWorkspace;
          setWorkspace(nextWorkspace);
          setWorkbenchSeed(savedTheme(state?.workbench));
        }
        setMemorySupported(message.capabilities?.associativeMemory === true);
        setDiscardSupported(message.capabilities?.discardRun === true);
        if (message.discardResult) setDiscardResult(message.discardResult);
        setView(message.view);
        setLocale(nextLocale);
        setLayout(nextLayout);
        persist({
          view: message.view,
          locale: nextLocale,
          hostLocale: receivedLocale,
          userLocale: userLocale.current,
          layout: nextLayout,
          capabilities: message.capabilities,
          workspace: nextWorkspace,
          ...(workspaceChanged
            ? {
                workbench: savedTheme(state?.workbench),
                workbenchWorkspace: nextWorkspace
              }
            : {})
        });
      }
      if (message.type === 'error') {
        if (message.discardResult) {
          setDiscardResult(message.discardResult);
          return;
        }
        const nextLocale = userLocale.current ?? resolveLocale(message.locale);
        const nextLayout = resolveDisplayLayout(message.layout);
        const errorView: WebviewView = {
          type: 'error',
          message: message.message
        };
        setView(errorView);
        setLocale(nextLocale);
        setLayout(nextLayout);
        persist({ view: errorView, locale: nextLocale, layout: nextLayout });
      }
    };
    window.addEventListener('message', listener);
    api.setPollingActive?.(true);
    api.postMessage({ command: 'ready' });
    return () => {
      window.removeEventListener('message', listener);
      api.setPollingActive?.(false);
    };
  }, [api]);
  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  if (!view)
    return (
      <I18nProvider locale={locale}>
        <LoadingView layout={layout} />
      </I18nProvider>
    );
  return (
    <I18nProvider locale={locale}>
      <ExecutionClockContext.Provider value={nowMs}>
        <div className="tapl-app" data-layout={layout}>
          <Workbench
            key={workspace ?? ''}
            view={view}
            layout={layout}
            workspace={workspace}
            memorySupported={memorySupported}
            discardSupported={discardSupported}
            discardResult={discardResult}
            send={(message) => api.postMessage(message)}
            locale={locale}
            browser={!!api.setPollingActive}
            initialState={workbenchSeed}
            onStateChange={(workbench) => persist({ workbench, workbenchWorkspace: workspaceRef.current })}
            onLocaleChange={(nextLocale) => {
              userLocale.current = nextLocale;
              setLocale(nextLocale);
              persist({ locale: nextLocale, userLocale: nextLocale });
            }}
            renderLegacy={(legacy, send) => (
              <ViewRenderer
                view={legacy}
                layout={layout}
                memorySupported={memorySupported}
                discardSupported={discardSupported}
                discardResult={discardResult}
                send={send}
              />
            )}
            renderManagement={(run, context) => (
              <RunTabs
                managementOnly
                runs={run ? [run] : []}
                selectedId={run?.id}
                selectedSourceDb={run?.source_db}
                workspace={workspace}
                discardSupported={discardSupported && context?.readonly !== true && run?.status !== 'archived'}
                discardResult={discardResult}
                send={(message) => api.postMessage(message)}
              />
            )}
          />
        </div>
      </ExecutionClockContext.Provider>
    </I18nProvider>
  );
}

function useExecutionTiming(
  timing: TaplExecutionTiming | null | undefined,
  status?: string
): FormattedExecutionTiming | null {
  const { locale } = useI18n();
  const nowMs = useContext(ExecutionClockContext);
  return formatExecutionTiming(timing, status, locale, nowMs);
}

function TaskDuration({ item }: { item: TaplItem }): JSX.Element | null {
  const { t } = useI18n();
  const timing = useExecutionTiming(item.execution_timing, item.status);
  return timing ? (
    <span className="tapl-muted mt-1 block text-xs tabular-nums">
      {t(timing.running ? 'elapsedTime' : 'duration')}{' '}
      <span className="inline-block whitespace-nowrap">{timing.duration}</span>
    </span>
  ) : null;
}

function LoadingView({ layout }: { layout: DisplayLayout }): JSX.Element {
  const { t } = useI18n();
  return (
    <main className="tapl-shell" data-layout={layout}>
      <section className="tapl-card">
        <div className="tapl-card-body">
          <span className="loading loading-spinner loading-md" />
          <p className="tapl-muted m-0">{t('loadingWorkflow')}</p>
        </div>
      </section>
    </main>
  );
}

function ViewRenderer({
  view,
  memorySupported,
  send
}: {
  memorySupported: boolean;
  discardSupported: boolean;
  discardResult?: RunDiscardResult;
  view: WebviewView;
  layout: DisplayLayout;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  switch (view.type) {
    case 'memories':
    case 'memory':
    case 'memorySource':
      return <MemoryView view={view} supported={memorySupported} send={send} />;
    case 'workspace':
      return <WorkspaceView view={view} send={send} />;
    case 'overview':
    case 'run':
    case 'records':
      return <></>;
    case 'archive':
      return <ArchiveView archive={view.archive} detail={view.detail} send={send} />;
    case 'archiveEvents':
      return <ArchiveEventsView archive={view.archive} detail={view.detail} send={send} />;
    case 'debug':
      return <DebugView status={view.status} send={send} />;
    case 'search':
      return <SearchView search={view.search} send={send} />;
    case 'searchItem':
      return <SearchItemView result={view.result} detail={view.detail} send={send} />;
    case 'error':
      return <ErrorView message={view.message} send={send} />;
  }
}

export function RunTabs({
  runs,
  selectedId,
  selectedSourceDb,
  workspace,
  discardSupported,
  discardResult,
  send,
  managementOnly = false
}: {
  runs: TaplWorkflowRun[];
  managementOnly?: boolean;
  selectedId?: string;
  selectedSourceDb?: string;
  workspace?: string;
  discardSupported: boolean;
  discardResult?: RunDiscardResult;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const tabListRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const pendingRef = useRef(false);
  const [target, setTarget] = useState<{
    runId: string;
    targetSessionId: string;
    workspace: string;
    title: string;
    source_db?: string;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [confirmationRunId, setConfirmationRunId] = useState('');
  const confirmationMatches = target !== null && confirmationRunId === target.runId;
  const confirmationMismatch = confirmationRunId.length > 0 && !confirmationMatches;
  const targetAvailable =
    target !== null &&
    discardSupported &&
    target.workspace === workspace &&
    (!managementOnly || (target.runId === selectedId && target.source_db === selectedSourceDb)) &&
    runs.some(
      (run) =>
        run.id === target.runId &&
        run.session_id === target.targetSessionId &&
        run.source_db === target.source_db &&
        run.writable !== false
    );
  const focusIndex = Math.max(
    0,
    runs.findIndex((run) => run.id === selectedId && run.source_db === selectedSourceDb)
  );
  const selectRun = (run: TaplWorkflowRun) => {
    if (run.id !== selectedId || run.source_db !== selectedSourceDb)
      send({
        command: 'selectRun',
        sessionId: run.session_id ?? '',
        source_db: run.source_db
      });
  };

  useEffect(() => {
    if (!target) return;
    const dialog = dialogRef.current;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog?.showModal();
    cancelRef.current?.focus();
    return () => {
      dialog?.close();
      if (opener?.isConnected) opener.focus();
      else tabListRef.current?.querySelector<HTMLButtonElement>('[role="tab"][tabindex="0"]')?.focus();
    };
  }, [target]);

  useEffect(() => {
    // Polling or a workspace switch must never retarget an already-open dialog.
    if (target && !targetAvailable) {
      setTarget(null);
      setConfirmationRunId('');
      pendingRef.current = false;
      setPending(false);
    }
  }, [target, targetAvailable]);

  useEffect(() => {
    if (!discardResult || !pendingRef.current || discardResult.runId !== target?.runId) return;
    pendingRef.current = false;
    setPending(false);
    if (discardResult.ok) {
      setTarget(null);
      setConfirmationRunId('');
    } else setError(discardResult.message || t('discardRunFailed'));
    // Only a newly received host result resolves a submitted request. Opening a
    // dialog again must not consume a result left over from an earlier attempt.
  }, [discardResult]);

  const requestDiscard = (run: TaplWorkflowRun | undefined) => {
    if (!discardSupported || !workspace || !run?.id || typeof run.session_id !== 'string' || run.writable === false)
      return;
    setError('');
    setConfirmationRunId('');
    setTarget({
      runId: run.id,
      targetSessionId: run.session_id,
      workspace,
      title: String(run.request_summary || run.slug || run.id),
      source_db: run.source_db
    });
  };
  const managedRun = runs.find((run) => run.id === selectedId && run.source_db === selectedSourceDb);
  const cancel = () => {
    if (!pendingRef.current) {
      setTarget(null);
      setConfirmationRunId('');
    }
  };
  const confirm = () => {
    if (!target || !targetAvailable || !confirmationMatches || pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    setError('');
    send({
      command: 'discardRun',
      runId: target.runId,
      targetSessionId: target.targetSessionId,
      workspace: target.workspace,
      source_db: target.source_db,
      confirmed: true,
      confirmationRunId
    });
  };

  return (
    <>
      {managementOnly ? (
        <button
          className="wb-nav-button wb-discard-button"
          type="button"
          data-wb-focus="discard"
          disabled={
            !discardSupported ||
            !workspace ||
            !managedRun?.id ||
            typeof managedRun.session_id !== 'string' ||
            managedRun.writable === false ||
            pending
          }
          title={!discardSupported || managedRun?.writable === false ? t('wbDiscardUnavailable') : undefined}
          onClick={() => requestDiscard(managedRun)}
        >
          <WorkbenchIcon name="trash" />
          <span>{t('wbDiscard')}</span>
          <WorkbenchIcon name="arrow" />
        </button>
      ) : (
        <div className="tapl-run-tabs" role="tablist" aria-label={t('activeRun')} ref={tabListRef}>
          {runs.length ? (
            runs.map((run, index) => {
              const title = String(run.request_summary || run.slug || run.id || t('active'));
              const closeLabel = t('closeRun', { title });
              return (
                <div className="tapl-run-tab-slot" key={`${run.source_db}:${run.id}`} role="presentation">
                  <button
                    id={`tapl-run-tab-${run.source_db ?? 'local'}-${run.id}`}
                    className="tapl-run-tab"
                    type="button"
                    role="tab"
                    aria-selected={run.id === selectedId && run.source_db === selectedSourceDb}
                    aria-controls="tapl-run-panel"
                    tabIndex={index === focusIndex ? 0 : -1}
                    title={[title, run.session_id, run.source_db].filter(Boolean).join('\n')}
                    onClick={() => selectRun(run)}
                    onKeyDown={(event) => {
                      let nextIndex: number;
                      switch (event.key) {
                        case 'ArrowRight':
                          nextIndex = (index + 1) % runs.length;
                          break;
                        case 'ArrowLeft':
                          nextIndex = (index - 1 + runs.length) % runs.length;
                          break;
                        case 'Home':
                          nextIndex = 0;
                          break;
                        case 'End':
                          nextIndex = runs.length - 1;
                          break;
                        default:
                          return;
                      }
                      event.preventDefault();
                      tabListRef.current?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[nextIndex]?.focus();
                      selectRun(runs[nextIndex]);
                    }}
                  >
                    <span className="tapl-run-tab-title">{title}</span>
                    <span className="tapl-run-tab-session">{run.session_id?.slice(0, 8) || t('active')}</span>
                  </button>
                  {discardSupported &&
                  run.writable !== false &&
                  workspace &&
                  run.id &&
                  typeof run.session_id === 'string' ? (
                    <button
                      className="tapl-run-tab-close"
                      type="button"
                      aria-label={closeLabel}
                      title={closeLabel}
                      disabled={pending}
                      onClick={() => {
                        if (!workspace || !run.id || typeof run.session_id !== 'string') return;
                        setError('');
                        setConfirmationRunId('');
                        setTarget({
                          runId: run.id,
                          targetSessionId: run.session_id,
                          workspace,
                          title,
                          source_db: run.source_db
                        });
                      }}
                    >
                      <span aria-hidden="true">×</span>
                    </button>
                  ) : null}
                </div>
              );
            })
          ) : (
            <button className="tapl-run-tab" type="button" role="tab" aria-selected={false} disabled>
              <span className="tapl-run-tab-title">{t('noActiveRunTitle')}</span>
            </button>
          )}
        </div>
      )}
      {target ? (
        <dialog
          ref={dialogRef}
          className="tapl-discard-dialog"
          aria-labelledby="tapl-discard-title"
          aria-describedby="tapl-discard-scope tapl-discard-effects tapl-discard-process"
          tabIndex={-1}
          onKeyDown={(event) => {
            if (event.key !== 'Tab') return;
            const controls = Array.from(
              event.currentTarget.querySelectorAll<HTMLElement>(
                'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
              )
            ).filter((control) => control.getClientRects().length > 0);
            const first = controls[0];
            const last = controls[controls.length - 1];
            if (!first) {
              event.preventDefault();
              event.currentTarget.focus();
            } else if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first.focus();
            }
          }}
          onCancel={(event) => {
            event.preventDefault();
            cancel();
          }}
        >
          <h2 id="tapl-discard-title">{t('discardRunTitle')}</h2>
          <p className="tapl-discard-run-title">{target.title}</p>
          <p id="tapl-discard-scope">{t('discardRunScope')}</p>
          <p id="tapl-discard-effects">{t('discardRunEffects')}</p>
          <p id="tapl-discard-process">{t('discardRunProcess')}</p>
          <dl className="tapl-discard-identity">
            <dt>{t('run')}</dt>
            <dd>
              <code className="tapl-discard-run-id">{target.runId}</code>
            </dd>
            <dt>{t('workspace')}</dt>
            <dd>{target.workspace}</dd>
            <dt>{t('discardRunOwner')}</dt>
            <dd>{target.targetSessionId || t('discardRunLegacyOwner')}</dd>
          </dl>
          <div className="tapl-discard-confirmation">
            <label htmlFor="tapl-discard-confirmation-id">{t('discardRunIdLabel')}</label>
            <p id="tapl-discard-confirmation-help">{t('discardRunIdHelp')}</p>
            <input
              id="tapl-discard-confirmation-id"
              type="text"
              className="input input-sm w-full"
              value={confirmationRunId}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="none"
              spellCheck={false}
              disabled={pending}
              aria-invalid={confirmationMismatch}
              aria-describedby={`tapl-discard-confirmation-help${confirmationMismatch ? ' tapl-discard-confirmation-mismatch' : ''}`}
              onChange={(event) => setConfirmationRunId(event.currentTarget.value)}
            />
            {confirmationMismatch ? (
              <p id="tapl-discard-confirmation-mismatch" role="status" className="tapl-discard-error">
                {t('discardRunIdMismatch')}
              </p>
            ) : null}
          </div>
          {error ? (
            <p role="alert" className="tapl-discard-error">
              {error}
            </p>
          ) : null}
          <div className="tapl-discard-actions">
            <button
              ref={cancelRef}
              type="button"
              className="btn btn-secondary btn-sm"
              disabled={pending}
              onClick={cancel}
            >
              {t('cancel')}
            </button>
            <button
              type="button"
              className="btn btn-error btn-sm"
              disabled={pending || !targetAvailable || !confirmationMatches}
              onClick={confirm}
            >
              {t(pending ? 'discardingRun' : 'discardRunConfirm')}
            </button>
          </div>
        </dialog>
      ) : null}
    </>
  );
}

function WorkspaceView({
  view,
  send
}: {
  view: Extract<WebviewView, { type: 'workspace' }>;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const [workspace, setWorkspace] = useState(view.workspace);
  useEffect(() => setWorkspace(view.workspace), [view.workspace]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (workspace.trim()) {
      send({ command: 'selectWorkspace', workspace: workspace.trim() });
    }
  };

  return (
    <section className="tapl-workspace-shell" aria-labelledby="workspace-title">
      <div className="tapl-workspace-orbit" aria-hidden="true" />
      <div className="tapl-workspace-card">
        <div className="tapl-workspace-mark" aria-hidden="true">
          T
        </div>
        <p className="tapl-eyebrow">{t('localViewer')}</p>
        <h1 id="workspace-title" className="m-0 text-3xl font-semibold">
          {t('chooseWorkspace')}
        </h1>
        <p className="tapl-muted m-0 leading-6">{t('workspaceHelp')}</p>
        <form className="tapl-workspace-form" onSubmit={submit}>
          <label className="tapl-workspace-label" htmlFor="tapl-workspace-path">
            {t('workspacePath')}
          </label>
          <div className="join flex w-full min-w-0">
            <input
              id="tapl-workspace-path"
              className="input join-item min-w-0 flex-1"
              value={workspace}
              placeholder={t('workspacePlaceholder')}
              autoComplete="off"
              autoFocus
              onChange={(event) => setWorkspace(event.target.value)}
            />
            <button className="btn btn-primary join-item" type="submit" disabled={!workspace.trim()}>
              {t('openWorkspace')}
            </button>
          </div>
        </form>
        {view.message ? (
          <p className="tapl-workspace-message" role="status">
            {view.message}
          </p>
        ) : null}
        <p className="tapl-workspace-hint">
          <code>{t('workspaceSetupHint')}</code>
        </p>
      </div>
    </section>
  );
}

function ArchiveView({
  archive,
  detail,
  send
}: {
  archive: TaplArchive;
  detail?: TaplArchiveDetail;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const archiveMeta = detail?.archive ?? archive;
  const items = detail?.items ?? [];
  const plans = items.filter((item) => item.kind === 'plan');
  const tasks = items.filter((item) => item.kind === 'task');
  const findings = items.filter((item) => item.kind === 'finding');
  const otherItems = items.filter((item) => !['plan', 'task', 'finding'].includes(item.kind));
  const counts = countTaskStatuses(tasks);

  return (
    <>
      <Topbar
        eyebrow={formatTimestamp(archiveMeta.created_at)}
        title={archiveMeta.slug}
        action={
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            data-legacy-back
            onClick={() => send({ command: 'back' })}
          >
            {t('back')}
          </button>
        }
      />
      <section className="tapl-metric-grid">
        <Stat
          label={t('archive')}
          value={t('saved')}
          detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug}
        />
        <Stat
          label={t('tasks')}
          value={String(tasks.length)}
          detail={t('incompleteCount', {
            count: (counts.Pending ?? 0) + (counts['In Progress'] ?? 0) + (counts.Blocked ?? 0)
          })}
        />
        <Stat
          label={t('records')}
          value={String(items.length)}
          detail={t('planAndFindings', {
            plans: plans.length,
            findings: findings.length
          })}
        />
        <Stat
          label={t('events')}
          value={String(detail?.events.length ?? 0)}
          detail={detail ? t('archivedHookEvents') : t('detailUnavailable')}
        />
      </section>
      <div className="flex flex-wrap gap-2">
        {TASK_STATUSES.map((status) => (
          <Pill key={status} label={status} value={counts[status]} />
        ))}
      </div>
      <section className="tapl-grid">
        <div className="tapl-main">
          <Card title={t('archivedWorkflowRecords')}>
            <RecordTabs
              tabs={[
                {
                  id: 'plan',
                  label: t('plan'),
                  count: plans.length,
                  content: (
                    <ItemList items={plans} empty={detail ? t('noPlanRecords') : t('archiveDetailsUnavailable')} />
                  )
                },
                {
                  id: 'tasks',
                  label: t('tasks'),
                  count: tasks.length,
                  content: (
                    <ItemList items={tasks} empty={detail ? t('noTaskRecords') : t('archiveDetailsUnavailable')} />
                  )
                },
                {
                  id: 'findings',
                  label: t('findings'),
                  count: findings.length,
                  content: (
                    <ItemList
                      items={findings}
                      empty={detail ? t('noFindingRecords') : t('archiveDetailsUnavailable')}
                    />
                  )
                }
              ]}
            />
          </Card>
        </div>
        <aside className="tapl-rail">
          <ArchiveSummary archive={archiveMeta} />
          <Card title={t('otherRecords')}>
            <ItemList
              items={otherItems}
              empty={detail ? t('noOtherArchivedRecords') : t('archiveDetailsUnavailable')}
            />
          </Card>
        </aside>
      </section>
      <footer>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          onClick={() =>
            send({
              command: 'archiveEvents',
              archiveId: archiveMeta.id,
              source_db: archiveMeta.source_db
            })
          }
        >
          {t('hookEvents')}
        </button>
      </footer>
    </>
  );
}

function ArchiveEventsView({
  archive,
  detail,
  send
}: {
  archive: TaplArchive;
  detail?: TaplArchiveDetail;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const archiveMeta = detail?.archive ?? archive;
  const events = detail?.events ?? [];
  return (
    <>
      <Topbar
        eyebrow={archiveMeta.slug}
        title={t('hookEvents')}
        action={
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            data-legacy-back
            onClick={() => send({ command: 'back' })}
          >
            {t('back')}
          </button>
        }
      />
      <section className="tapl-metric-grid">
        <Stat
          label={t('archive')}
          value={t('saved')}
          detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug}
        />
        <Stat
          label={t('events')}
          value={String(events.length)}
          detail={detail ? t('archivedHookEvents') : t('detailUnavailable')}
        />
      </section>
      <Card title={t('archivedHookEvents')}>
        <EventList events={events} empty={detail ? t('noArchivedHookEvents') : t('archiveDetailsUnavailable')} />
      </Card>
    </>
  );
}

function DebugView({ status, send }: { status: TaplStatus; send: (message: WebviewCommand) => void }): JSX.Element {
  const { t } = useI18n();
  return (
    <>
      <Topbar
        eyebrow={t('debug')}
        title={t('hookEvents')}
        action={
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            data-legacy-back
            onClick={() => send({ command: 'back' })}
          >
            {t('back')}
          </button>
        }
      />
      <Card title={t('recentHookEvents')}>
        <EventList events={status.recent_events} empty={t('noHookEvents')} />
      </Card>
    </>
  );
}

function SearchView({
  search,
  send
}: {
  search: TaplSearchPayload;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  return (
    <>
      <Topbar
        eyebrow={t('searchMode', { mode: search.mode })}
        title={t('searchResults')}
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              data-legacy-back
              onClick={() => send({ command: 'back' })}
            >
              {t('back')}
            </button>
            <SearchForm defaultQuery={search.query} send={send} />
          </div>
        }
      />
      <Card title={search.query}>
        {search.results.length ? (
          <div className="tapl-stack">
            {search.results.map((result, index) => (
              <SearchResult key={`${result.id ?? result.stable_id}-${index}`} result={result} send={send} />
            ))}
          </div>
        ) : (
          <p className="tapl-muted m-0">{t('noResultsFor', { query: search.query })}</p>
        )}
      </Card>
    </>
  );
}

function SearchItemView({
  result,
  detail,
  send
}: {
  result: TaplSearchResult;
  detail?: TaplItemDetail;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t, kind, status: displayStatus } = useI18n();
  const title = detail?.title ?? result.title;
  const status = detail?.status ?? result.status;
  const content = detail?.body || detail?.raw_text || result.snippet || '';
  return (
    <>
      <Topbar
        eyebrow={`${kind(detail?.kind ?? result.kind)} ${detail?.stable_id ?? result.stable_id}`}
        title={title}
        action={
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            data-legacy-back
            onClick={() => send({ command: 'back' })}
          >
            {t('back')}
          </button>
        }
      />
      <div className="tapl-stack max-w-5xl">
        <Card title={t('details')}>
          <DetailList
            fields={[
              [t('status'), displayStatus(status)],
              [t('run'), detail?.run_slug],
              [t('runStatus'), detail?.run_status],
              [t('source'), detail?.source ?? result.source],
              [t('archive'), detail?.archive_slug],
              [t('searchSource'), result.search_source]
            ]}
          />
          {detail?.archive_id ? (
            <button
              className="btn btn-primary btn-sm mt-3"
              type="button"
              onClick={() =>
                send({
                  command: 'openArchive',
                  archiveId: detail.archive_id as string,
                  source_db: detail.source_db
                })
              }
            >
              {t('openArchive')}
            </button>
          ) : null}
        </Card>
        {content ? (
          <Card title={t('content')}>
            <ReadableBlock content={content} />
          </Card>
        ) : null}
        {detail ? <ItemMetadata item={detail} /> : null}
      </div>
    </>
  );
}

function ErrorView({ message, send }: { message: string; send: (message: WebviewCommand) => void }): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="tapl-stack max-w-3xl">
      <Card title={t('taplUnavailable')}>
        <p className="text-error m-0" role="alert">
          {message}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="btn btn-primary btn-sm" type="button" onClick={() => send({ command: 'refresh' })}>
            {t('refresh')}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            data-legacy-back
            onClick={() => send({ command: 'back' })}
          >
            {t('back')}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            type="button"
            onClick={() => send({ command: 'chooseWorkspace' })}
          >
            {t('chooseWorkspace')}
          </button>
        </div>
      </Card>
    </div>
  );
}

function Topbar({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }): JSX.Element {
  return (
    <header className="tapl-topbar">
      <div className="min-w-0">
        <p className="tapl-eyebrow">{eyebrow}</p>
        <h1 className="m-0 text-2xl font-semibold">{title}</h1>
      </div>
      {action}
    </header>
  );
}

function Card({
  title,
  eyebrow,
  aside,
  children,
  className
}: {
  title: string;
  eyebrow?: string;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}): JSX.Element {
  return (
    <section className={['tapl-card', className].filter(Boolean).join(' ')}>
      <div className="tapl-card-body">
        <div className="tapl-card-header">
          <div className="min-w-0">
            {eyebrow ? <p className="tapl-eyebrow">{eyebrow}</p> : null}
            <h2 className="card-title m-0 text-base">{title}</h2>
          </div>
          {aside}
        </div>
        {children}
      </div>
    </section>
  );
}

function Stat({
  label,
  value,
  detail,
  tone
}: {
  label: string;
  value: string;
  detail: string;
  tone?: string;
}): JSX.Element {
  return (
    <article className={`tapl-stat stat min-w-0 ${tone ? statusClass(tone) : ''}`}>
      <span className="stat-title">{label}</span>
      <strong className="stat-value text-xl">{value}</strong>
      <small className="stat-desc">{detail}</small>
    </article>
  );
}

function SearchForm({
  defaultQuery,
  send
}: {
  defaultQuery: string;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const [query, setQuery] = useState(defaultQuery);
  useEffect(() => setQuery(defaultQuery), [defaultQuery]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) {
      send({ command: 'search', query });
    }
  };
  return (
    <form className="tapl-search join" onSubmit={submit}>
      <input
        className="input input-sm join-item"
        value={query}
        placeholder={t('searchWorkflowHistory')}
        aria-label={t('searchWorkflowHistory')}
        onChange={(event) => setQuery(event.target.value)}
      />
      <button className="btn btn-primary btn-sm join-item" type="submit">
        {t('search')}
      </button>
    </form>
  );
}

function RecordTabs({
  tabs
}: {
  tabs: Array<{ id: string; label: string; count: number; content: ReactNode }>;
}): JSX.Element {
  const [selected, setSelected] = useState(tabs[0]?.id ?? '');
  const selectedTab = tabs.find((tab) => tab.id === selected) ?? tabs[0];
  return (
    <div>
      <div className="tapl-tabs tabs tabs-box" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab gap-2 ${selectedTab?.id === tab.id ? 'tab-active' : ''}`}
            type="button"
            role="tab"
            aria-selected={selectedTab?.id === tab.id}
            onClick={() => setSelected(tab.id)}
          >
            {tab.label}
            <span className="badge badge-sm">{tab.count}</span>
          </button>
        ))}
      </div>
      <section className="tapl-tab-panel" role="tabpanel">
        {selectedTab?.content}
      </section>
    </div>
  );
}

function ItemList({ items, empty }: { items: TaplItem[]; empty: string }): JSX.Element {
  if (!items.length) {
    return <p className="tapl-empty-state">{empty}</p>;
  }
  return (
    <div className="tapl-stack">
      {items.map((item) => (
        <ItemCard key={`${item.kind}-${item.stable_id}`} item={item} />
      ))}
    </div>
  );
}

function ItemCard({ item }: { item: TaplItem }): JSX.Element {
  const hasBadges = Boolean(item.status);
  return (
    <article className="tapl-item tapl-record-card">
      <div className="mb-2 flex items-start justify-between gap-2">
        <span className="kbd kbd-xs">{item.stable_id}</span>
        {hasBadges ? (
          <div className="flex min-w-0 flex-wrap justify-end gap-1">
            {item.status ? <Badge label={item.status} tone={statusClass(item.status)} /> : null}
          </div>
        ) : null}
      </div>
      <h3 className="m-0 text-sm font-semibold">{item.title}</h3>
      {item.kind === 'task' ? <TaskDuration item={item} /> : null}
      {item.body ? <ReadableBlock content={item.body} /> : null}
      <CustomFieldsBlock fields={item.custom_fields} />
    </article>
  );
}

function EventList({ events, empty }: { events: TaplEvent[]; empty: string }): JSX.Element {
  if (!events.length) {
    return <p className="tapl-empty-state">{empty}</p>;
  }
  return (
    <div className="tapl-stack">
      {events.map((event, index) => (
        <EventCard key={`${event.event_type}-${event.created_at}-${index}`} event={event} />
      ))}
    </div>
  );
}

function EventCard({ event }: { event: TaplEvent }): JSX.Element {
  const { t } = useI18n();
  return (
    <article className="tapl-item tapl-record-card">
      <div className="mb-2 flex items-start justify-between gap-2">
        <strong>
          {event.event_type}
          {event.tool_name ? ` ${event.tool_name}` : ''}
        </strong>
        <Badge label={event.mode} />
      </div>
      <p className="m-0">{event.message || t('recorded')}</p>
      <p className="tapl-muted mt-2 text-xs">{formatTimestamp(event.created_at)}</p>
    </article>
  );
}

function ArchiveSummary({ archive }: { archive: TaplArchive }): JSX.Element {
  const { t } = useI18n();
  return (
    <Card title={t('summary')}>
      <p>{archive.summary || t('noSummaryRecorded')}</p>
      {archive.request_summary ? <p className="tapl-muted">{archive.request_summary}</p> : null}
      <DetailList
        fields={[
          [t('run'), archive.run_slug],
          [t('created'), formatTimestamp(archive.run_created_at)],
          [t('updated'), formatTimestamp(archive.run_updated_at)],
          [t('archivedRun'), formatTimestamp(archive.run_archived_at)]
        ]}
      />
    </Card>
  );
}

function SearchResult({
  result,
  send
}: {
  result: TaplSearchResult;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { kind, status } = useI18n();
  const content = (
    <>
      <div className="mb-1 flex items-start justify-between gap-2">
        <strong>
          <span className="kbd kbd-xs">{result.stable_id}</span> {result.title}
        </strong>
        <Badge label={kind(result.kind)} />
      </div>
      {result.status ? <span className="tapl-muted text-sm">{status(result.status)}</span> : null}
      {result.snippet ? <p className="tapl-muted mt-2 text-sm">{conciseText(result.snippet, 180)}</p> : null}
      <p className="tapl-muted mt-2 text-xs">
        {result.search_source}
        {result.source ? ` / ${result.source}` : ''}
      </p>
    </>
  );
  if (typeof result.id !== 'number') {
    return <article className="tapl-item tapl-record-card">{content}</article>;
  }
  return (
    <button
      className="tapl-item tapl-clickable tapl-record-card"
      type="button"
      onClick={() =>
        send({
          command: 'openSearchResult',
          itemId: result.id as number,
          source_db: result.source_db
        })
      }
    >
      {content}
    </button>
  );
}

function ItemMetadata({ item }: { item: TaplItemDetail }): JSX.Element {
  const { t } = useI18n();
  const activeExecution = item.active_execution;
  const timing = useExecutionTiming(item.execution_timing, item.status);
  const executionFields: Array<[string, unknown]> = [
    [t('spec'), item.spec_id],
    [t('goal'), item.goal],
    [t('action'), item.action],
    [t('verification'), item.verification],
    [t('result'), item.result],
    [t('blocker'), item.blocker],
    [t('nextAction'), item.next_action],
    [t('executionMode'), item.execution_mode],
    [t('executor'), item.executor_kind],
    [t('parallelGroup'), item.parallel_group],
    [t('ownedPaths'), item.owned_paths?.join(', ')],
    [t('dependencies'), item.depends_on?.join(', ')],
    [t('executionId'), activeExecution?.execution_id],
    [t('executionState'), activeExecution?.execution_state],
    [
      t(timing?.running ? 'elapsedTime' : 'duration'),
      item.kind === 'task' ? (timing?.duration ?? t('notMeasured')) : undefined
    ]
  ];
  const auditFields: Array<[string, unknown]> = [
    [t('relatedIds'), item.related_ids],
    [t('impact'), item.impact],
    [t('request'), item.request_summary],
    [t('updated'), formatTimestamp(item.updated_at)],
    [t('archivedAt'), formatTimestamp(item.archive_created_at)]
  ];
  return (
    <>
      {hasCustomFields(item.custom_fields) ? (
        <Card title={t('customFields')}>
          <CustomFieldRows fields={item.custom_fields as Record<string, TaplJsonValue>} />
        </Card>
      ) : null}
      <Card title={t('execution')}>
        <DetailList fields={executionFields} empty={t('noExecutionMetadata')} />
      </Card>
      <Card title={t('audit')}>
        <DetailList fields={auditFields} empty={t('noAuditMetadata')} />
      </Card>
    </>
  );
}

function CustomFieldsBlock({ fields }: { fields?: Record<string, TaplJsonValue> }): JSX.Element | null {
  const { t } = useI18n();
  if (!hasCustomFields(fields)) {
    return null;
  }
  return (
    <section className="tapl-custom-fields" aria-label={t('customFields')}>
      <div className="tapl-custom-header">
        <span className="tapl-eyebrow">{t('customFields')}</span>
        <span className="badge badge-sm">{Object.keys(fields).length}</span>
      </div>
      <CustomFieldRows fields={fields} />
    </section>
  );
}

function CustomFieldRows({ fields }: { fields: Record<string, TaplJsonValue> }): JSX.Element {
  return (
    <dl className="tapl-custom-grid">
      {Object.entries(fields).map(([label, value]) => (
        <div key={label} className="tapl-custom-row">
          <dt>{label}</dt>
          <dd>
            <JsonValue value={value} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function JsonValue({ value, depth = 0 }: { value: TaplJsonValue; depth?: number }): JSX.Element {
  if (value === null) {
    return <span className="tapl-json-null">null</span>;
  }
  if (Array.isArray(value)) {
    return (
      <ol className="tapl-json-array">
        {value.map((item, index) => (
          <li key={index}>
            <JsonValue value={item} depth={depth + 1} />
          </li>
        ))}
      </ol>
    );
  }
  if (typeof value === 'object') {
    return (
      <dl className="tapl-json-object">
        {Object.entries(value).map(([label, item]) => (
          <div key={label} className="tapl-json-entry">
            <dt>{label}</dt>
            <dd>
              <JsonValue value={item} depth={depth + 1} />
            </dd>
          </div>
        ))}
      </dl>
    );
  }
  return <span className={`tapl-json-${typeof value}`}>{String(value)}</span>;
}

function hasCustomFields(fields: Record<string, TaplJsonValue> | undefined): fields is Record<string, TaplJsonValue> {
  return Boolean(fields && Object.keys(fields).length);
}

function DetailList({ fields, empty }: { fields: Array<[string, unknown]>; empty?: string }): JSX.Element {
  const { t } = useI18n();
  const rows = fields.filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!rows.length) {
    return <p className="tapl-muted m-0">{empty ?? t('notRecorded')}</p>;
  }
  return (
    <div className="tapl-detail-grid">
      {rows.map(([label, value]) => (
        <div key={label} className="tapl-detail-row">
          <span className="tapl-muted text-xs">{label}</span>
          <div>{String(value)}</div>
        </div>
      ))}
    </div>
  );
}

function ReadableBlock({ content }: { content: unknown }): JSX.Element {
  const { t } = useI18n();
  const blocks = useMemo(() => parseReadableBlocks(String(content ?? '')), [content]);
  if (!blocks.length) {
    return <p className="tapl-muted m-0">{t('notRecorded')}</p>;
  }
  return <div className="tapl-readable markdown-body mt-3">{blocks}</div>;
}

function parseReadableBlocks(content: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const lines = content.split(/\r\n|\n|\r/);
  let list: string[] = [];
  let paragraph: string[] = [];
  const flushParagraph = () => {
    if (paragraph.length) {
      nodes.push(<p key={`p-${nodes.length}`}>{paragraph.join(' ')}</p>);
      paragraph = [];
    }
  };
  const flushList = () => {
    if (list.length) {
      nodes.push(
        <ul key={`ul-${nodes.length}`}>
          {list.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      );
      list = [];
    }
  };
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushList();
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushList();
      nodes.push(
        <h3 key={`h-${nodes.length}`} className="text-sm font-semibold">
          {heading[2]}
        </h3>
      );
      continue;
    }
    const bullet = line.match(/^[-*+]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      list.push(bullet[1]);
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  flushList();
  return nodes;
}

function Badge({ label, tone }: { label: string; tone?: string }): JSX.Element {
  const { status } = useI18n();
  return <span className={`badge badge-sm ${tone ?? statusClass(label)}`}>{status(label)}</span>;
}

function Pill({ label, value }: { label: string; value: number | undefined }): JSX.Element {
  const { status } = useI18n();
  return <Badge label={`${status(label)} ${value ?? 0}`} tone={statusClass(label)} />;
}

function countTaskStatuses(tasks: TaplItem[]): Record<string, number> {
  const counts = { ...DEFAULT_TASK_COUNTS };
  for (const task of tasks) {
    if (task.status) {
      counts[task.status] = (counts[task.status] ?? 0) + 1;
    }
  }
  return counts;
}

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-');
}

function conciseText(value: unknown, maxLength: number): string {
  const text = String(value ?? '')
    .replace(/\s+/g, ' ')
    .trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
}

function formatTimestamp(value: unknown): string {
  const raw = String(value ?? '');
  if (!raw) {
    return '';
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  const twoDigits = (part: number) => String(part).padStart(2, '0');
  return [
    `${twoDigits(date.getFullYear() % 100)}-${twoDigits(date.getMonth() + 1)}-${twoDigits(date.getDate())}`,
    `${twoDigits(date.getHours())}:${twoDigits(date.getMinutes())}:${twoDigits(date.getSeconds())}`
  ].join(' ');
}
