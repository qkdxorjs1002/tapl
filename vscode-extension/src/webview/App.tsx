import { useEffect, useRef, useState } from 'react';
import { resolveLocale, type SupportedLocale } from '../i18n';
import type {
  DisplayLayout,
  HostMessage,
  RunDiscardResult,
  SettingsResult,
  TaplWorkflowRun,
  WebviewCommand,
  WebviewView,
  WorkspaceSelectionResult,
  WorkspaceDirectoryResult
} from './types';
import { vscodeApi } from './vscodeApi';
import { I18nProvider, useI18n } from './i18n';
import { MemoryView } from './MemoryView';
import { Workbench } from './workbench';
import { RecordDetail } from './workbench/RecordDetail';
import { SecondaryView } from './workbench/SecondaryViews';
import { Icon as WorkbenchIcon } from './workbench/Icon';
import { mergePersistedAppState, type PersistedAppState } from './appState';
import { sameMindmapValue } from './workbench/mindmapCache';

const BOOTSTRAP_VIEW: WebviewView = {
  type: 'overview',
  archives: [],
  searchQuery: '',
  status: {
    active_run: null,
    task_counts: {},
    incomplete_tasks: 0,
    plans: [],
    tasks: [],
    findings: [],
    recent_events: [],
    schema: {}
  }
};
function systemLanguage(): string {
  return typeof navigator === 'undefined' ? 'en' : navigator.language;
}

function resolveDisplayLayout(value: unknown): DisplayLayout {
  return value === 'small' || value === 'medium' || value === 'large' ? value : 'auto';
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
  const [restored] = useState(() => api.getState() as PersistedAppState | undefined);
  const persistedRef = useRef(restored);
  const [memorySupported, setMemorySupported] = useState(restored?.capabilities?.associativeMemory === true);
  const [discardSupported, setDiscardSupported] = useState(restored?.capabilities?.discardRun === true);
  const [discardResult, setDiscardResult] = useState<RunDiscardResult>();
  const [settingsResult, setSettingsResult] = useState<SettingsResult>();
  const [workspaceResult, setWorkspaceResult] = useState<WorkspaceSelectionResult>();
  const [directoryResult, setDirectoryResult] = useState<WorkspaceDirectoryResult>();
  const [view, setView] = useState<WebviewView | undefined>(restored?.view);
  const [locale, setLocale] = useState<SupportedLocale>(() =>
    resolveLocale(restored?.preferences?.language === 'auto'
      ? systemLanguage()
      : restored?.preferences?.language ?? systemLanguage())
  );
  const [layout, setLayout] = useState<DisplayLayout>(() => resolveDisplayLayout(restored?.preferences?.layout));
  const [workspace, setWorkspace] = useState(restored?.workspace);
  const workspaceRef = useRef(workspace);
  const [workbenchSeed, setWorkbenchSeed] = useState(() =>
    restored?.workbenchWorkspace && restored.workbenchWorkspace !== restored.workspace
      ? savedTheme(restored.workbench)
      : restored?.workbench
  );
  const persist = (values: Partial<PersistedAppState>) => {
    const browser = typeof api.setPollingActive === 'function';
    // BrowserApi also owns request/route context; preserve its live state merge behavior.
    const previous = browser ? api.getState() : persistedRef.current;
    const next = mergePersistedAppState(previous, values, browser);
    if (!browser && sameMindmapValue(previous, next)) return;
    persistedRef.current = next;
    api.setState(next);
  };

  useEffect(() => {
    const listener = (event: MessageEvent<HostMessage>) => {
      const message = event.data;
      if (!message || typeof message.type !== 'string') return;
      if (message.type === 'workspace:directory') {
        setDirectoryResult(message);
        return;
      }
      if (message.type === 'settings:result') {
        if (message.workspace === workspaceRef.current) {
          if (message.ok) {
            const preferences = message.preferences;
            const language = preferences?.language ?? message.settings?.values['viewer.language'];
            const nextLocale = resolveLocale(message.locale ?? (language === 'ko' || language === 'en' ? language : systemLanguage()));
            const nextLayout = resolveDisplayLayout(message.layout ?? preferences?.layout ?? message.settings?.values['viewer.layout']);
            setLocale(nextLocale);
            setLayout(nextLayout);
            persist({ locale: nextLocale, layout: nextLayout, preferences });
          }
          setSettingsResult(message);
        }
        return;
      }
      if (message.type === 'workspace:result') {
        setWorkspaceResult(message);
        return;
      }
      if (message.type === 'hydrate' || message.type === 'view:update') {
        const nextLocale = resolveLocale(message.locale ?? systemLanguage());
        const nextLayout = resolveDisplayLayout(message.layout);
        const nextWorkspace =
          message.workspace ??
          ('workspace' in message.view ? message.view.workspace : undefined) ??
          workspaceRef.current;
        const state = persistedRef.current;
        const workspaceChanged = nextWorkspace !== workspaceRef.current;
        if (workspaceChanged) {
          setSettingsResult(undefined);
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
          preferences: message.preferences,
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
        const nextLocale = resolveLocale(message.locale ?? systemLanguage());
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

  return (
    <I18nProvider locale={locale}>
      <div className="tapl-app" data-layout={layout}>
        <Workbench
          key={workspace ?? ''}
          view={view ?? BOOTSTRAP_VIEW}
          loading={!view}
          workspaceResult={workspaceResult}
          directoryResult={directoryResult}
          settingsResult={settingsResult}
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
          renderPage={(page, send, back) => (
            <ViewRenderer view={page} memorySupported={memorySupported} send={send} back={back} workspaceKey={workspace} />
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
    </I18nProvider>
  );
}

function ViewRenderer({
  view,
  memorySupported,
  send,
  back,
  workspaceKey
}: {
  view: WebviewView;
  memorySupported: boolean;
  workspaceKey?: string;
  send: (command: WebviewCommand) => void;
  back?: () => void;
}): JSX.Element | null {
  switch (view.type) {
    case 'searchItem':
      return <RecordDetail view={view} send={send} back={back} />;
    case 'memories':
    case 'memory':
    case 'memorySource':
      return <MemoryView view={view} supported={memorySupported} send={send} back={back} workspaceKey={workspaceKey} />;
    case 'archive':
    case 'archiveEvents':
    case 'debug':
    case 'search':
    case 'error':
      return <SecondaryView view={view} send={send} back={back} />;
    case 'workspace':
    case 'overview':
    case 'run':
    case 'records':
      return null;
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
          aria-label={t('wbDiscard')}
          data-wb-tooltip="true"
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
          <span className="wb-nav-label" aria-hidden="true">{t('wbDiscard')}</span>
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
          className="tapl-discard-dialog wb-dialog"
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
          <div className="wb-dialog-heading">
            <h2 id="tapl-discard-title">{t('discardRunTitle')}</h2>
            <button
              type="button"
              className="btn btn-ghost btn-sm btn-square"
              aria-label={t('wbClose')}
              disabled={pending}
              onClick={cancel}
            >
              <WorkbenchIcon name="close" />
            </button>
          </div>
          <p className="tapl-discard-run-title">{target.title}</p>
          <p id="tapl-discard-scope">{t('discardRunScope')}</p>
          <p id="tapl-discard-effects">{t('discardRunEffects')}</p>
          <p id="tapl-discard-process">{t('discardRunProcess')}</p>
          <dl className="tapl-discard-identity">
            <dt>{t('runId')}</dt>
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
