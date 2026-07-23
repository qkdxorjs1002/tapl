import { CSSProperties, FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { resolveLocale, type SupportedLocale } from '../i18n';
import type {
  HostMessage,
  TaplArchive,
  TaplArchiveDetail,
  TaplEvent,
  TaplItem,
  TaplItemDetail,
  TaplJsonValue,
  TaplSearchPayload,
  TaplSearchResult,
  TaplStatus,
  WebviewCommand,
  WebviewView
} from './types';
import { vscodeApi } from './vscodeApi';
import { I18nProvider, useI18n } from './i18n';

const TASK_STATUSES = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped'];
const DEFAULT_TASK_COUNTS: Record<string, number> = {
  Pending: 0,
  'In Progress': 0,
  Blocked: 0,
  Completed: 0,
  Skipped: 0
};

export function App(): JSX.Element {
  const api = vscodeApi();
  const restored = api.getState() as { view?: WebviewView; locale?: SupportedLocale } | undefined;
  const [view, setView] = useState<WebviewView | undefined>(restored?.view);
  const [locale, setLocale] = useState<SupportedLocale>(() => resolveLocale(
    restored?.locale ?? document.documentElement.lang ?? navigator.language
  ));

  useEffect(() => {
    const listener = (event: MessageEvent<HostMessage>) => {
      const message = event.data;
      if (!message || typeof message.type !== 'string') {
        return;
      }
      if (message.type === 'hydrate' || message.type === 'view:update') {
        const nextLocale = resolveLocale(message.locale);
        setView(message.view);
        setLocale(nextLocale);
        api.setState({ view: message.view, locale: nextLocale });
      }
      if (message.type === 'error') {
        const nextLocale = resolveLocale(message.locale);
        const errorView: WebviewView = { type: 'error', message: message.message };
        setView(errorView);
        setLocale(nextLocale);
        api.setState({ view: errorView, locale: nextLocale });
      }
    };
    window.addEventListener('message', listener);
    api.postMessage({ command: 'ready' });
    return () => window.removeEventListener('message', listener);
  }, [api]);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  if (!view) {
    return (
      <I18nProvider locale={locale}>
        <LoadingView />
      </I18nProvider>
    );
  }

  return (
    <I18nProvider locale={locale}>
      <main className="tapl-shell" data-theme="tapl">
        <ViewRenderer view={view} send={(message) => api.postMessage(message)} />
      </main>
    </I18nProvider>
  );
}

function LoadingView(): JSX.Element {
  const { t } = useI18n();
  return (
    <main className="tapl-shell">
      <section className="tapl-card">
        <div className="tapl-card-body">
          <span className="loading loading-spinner loading-md" />
          <p className="tapl-muted m-0">{t('loadingWorkflow')}</p>
        </div>
      </section>
    </main>
  );
}

function ViewRenderer({ view, send }: { view: WebviewView; send: (message: WebviewCommand) => void }): JSX.Element {
  switch (view.type) {
    case 'overview':
      return <OverviewView view={view} send={send} />;
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
      return <ErrorView message={view.message} />;
  }
}

function OverviewView({
  view,
  send
}: {
  view: Extract<WebviewView, { type: 'overview' }>;
  send: (message: WebviewCommand) => void;
}): JSX.Element {
  const { t } = useI18n();
  const { status, archives, searchQuery } = view;
  const counts = { ...DEFAULT_TASK_COUNTS, ...(status.task_counts || {}) };
  const totalTasks = status.tasks.length;
  const completedTasks = counts.Completed ?? 0;
  const openTasks = (counts.Pending ?? 0) + (counts['In Progress'] ?? 0) + (counts.Blocked ?? 0);
  const completionPercent = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0;
  const activeSummary = status.active_run
    ? String(status.active_run.request_summary || status.active_run.slug || t('active'))
    : t('noActiveRunTitle');
  const activeRunSlug = status.active_run ? String(status.active_run.slug || t('active')) : t('noActiveRunTitle');
  const pendingCount = counts.Pending ?? 0;
  const activeCount = counts['In Progress'] ?? 0;
  const blockedCount = counts.Blocked ?? 0;
  const nextTask = status.tasks.find((task) => task.status === 'In Progress')
    ?? status.tasks.find((task) => task.status === 'Pending');
  const currentPlan = status.plans[0];

  return (
    <>
      <header className="tapl-hero">
        <div className="tapl-hero-main">
          <div className="tapl-hero-copy">
            <div className="tapl-hero-meta">
              <span className="tapl-eyebrow">{t('workspace')}</span>
              <Badge label={activeRunSlug} tone={status.active_run ? 'in-progress' : undefined} />
            </div>
            <h1 className="m-0 text-3xl font-semibold">{t('appTitle')}</h1>
            <p className="tapl-hero-summary">{conciseText(activeSummary, 220)}</p>
            <div className="tapl-hero-pills">
              <Pill label="Pending" value={pendingCount} />
              <Pill label="In Progress" value={activeCount} />
              <Pill label="Blocked" value={blockedCount} />
            </div>
          </div>
          <div className="tapl-command-panel">
            <div className="tapl-command-actions">
              <button className="btn btn-primary btn-sm" type="button" onClick={() => send({ command: 'refresh' })}>
                {t('refresh')}
              </button>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'debug' })}>
                {t('debug')}
              </button>
            </div>
            <SearchForm defaultQuery={searchQuery} send={send} />
            <ProgressMeter
              label={t('runProgress')}
              value={completionPercent}
              detail={t('completedOfTotal', { completed: completedTasks, total: totalTasks })}
            />
          </div>
        </div>
      </header>
      <section className="tapl-metric-grid">
        <Stat label={t('openWork')} value={String(openTasks)} detail={t('activeAndBlocked', { active: activeCount, blocked: blockedCount })} tone={blockedCount ? 'blocked' : 'in-progress'} />
        <Stat label={t('currentPlan')} value={String(status.plans.length)} detail={currentPlan ? conciseText(currentPlan.title, 48) : t('noExecutionSpec')} tone="info" />
        <Stat label={t('nextTask')} value={nextTask ? nextTask.stable_id : t('none')} detail={nextTask ? conciseText(nextTask.title, 48) : t('queueIsClear')} tone="pending" />
        <Stat label={t('archives')} value={String(archives.length)} detail={t('recentSavedRuns')} tone="completed" />
      </section>
      <section className="tapl-grid">
        <div className="tapl-main">
          <Card
            title={t('activeBoard')}
            eyebrow={t('workItems')}
            aside={<span className="tapl-muted text-sm">{t('incompleteCount', { count: status.incomplete_tasks })}</span>}
          >
            <TaskBoard tasks={status.tasks} />
          </Card>
          <Card title={t('workflowRecords')} eyebrow={t('views')}>
            <RecordTabs
              tabs={[
                { id: 'plan', label: t('plan'), count: status.plans.length, content: <ItemList items={status.plans} empty={t('noPlanRecords')} /> },
                { id: 'tasks', label: t('tasks'), count: status.tasks.length, content: <ItemList items={status.tasks} empty={t('noTaskRecords')} /> },
                { id: 'findings', label: t('findings'), count: status.findings.length, content: <ItemList items={status.findings} empty={t('noFindingRecords')} /> }
              ]}
            />
          </Card>
        </div>
        <aside className="tapl-rail">
          <RunFocus status={status} counts={counts} />
          <Card title={t('recentArchives')} eyebrow={t('activity')}>
            <ArchiveList archives={archives} send={send} />
          </Card>
        </aside>
      </section>
    </>
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
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>{t('back')}</button>}
      />
      <section className="tapl-metric-grid">
        <Stat label={t('archive')} value={t('saved')} detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug} />
        <Stat label={t('tasks')} value={String(tasks.length)} detail={t('incompleteCount', { count: (counts.Pending ?? 0) + (counts['In Progress'] ?? 0) + (counts.Blocked ?? 0) })} />
        <Stat label={t('records')} value={String(items.length)} detail={t('planAndFindings', { plans: plans.length, findings: findings.length })} />
        <Stat label={t('events')} value={String(detail?.events.length ?? 0)} detail={detail ? t('archivedHookEvents') : t('detailUnavailable')} />
      </section>
      <div className="flex flex-wrap gap-2">
        {TASK_STATUSES.map((status) => <Pill key={status} label={status} value={counts[status]} />)}
      </div>
      <section className="tapl-grid">
        <div className="tapl-main">
          <Card title={t('archivedWorkflowRecords')}>
            <RecordTabs
              tabs={[
                { id: 'plan', label: t('plan'), count: plans.length, content: <ItemList items={plans} empty={detail ? t('noPlanRecords') : t('archiveDetailsUnavailable')} /> },
                { id: 'tasks', label: t('tasks'), count: tasks.length, content: <ItemList items={tasks} empty={detail ? t('noTaskRecords') : t('archiveDetailsUnavailable')} /> },
                { id: 'findings', label: t('findings'), count: findings.length, content: <ItemList items={findings} empty={detail ? t('noFindingRecords') : t('archiveDetailsUnavailable')} /> }
              ]}
            />
          </Card>
        </div>
        <aside className="tapl-rail">
          <ArchiveSummary archive={archiveMeta} />
          <Card title={t('otherRecords')}>
            <ItemList items={otherItems} empty={detail ? t('noOtherArchivedRecords') : t('archiveDetailsUnavailable')} />
          </Card>
        </aside>
      </section>
      <footer>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          onClick={() => send({ command: 'archiveEvents', archiveId: archiveMeta.id })}
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
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>{t('back')}</button>}
      />
      <section className="tapl-metric-grid">
        <Stat label={t('archive')} value={t('saved')} detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug} />
        <Stat label={t('events')} value={String(events.length)} detail={detail ? t('archivedHookEvents') : t('detailUnavailable')} />
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
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>{t('back')}</button>}
      />
      <Card title={t('recentHookEvents')}>
        <EventList events={status.recent_events} empty={t('noHookEvents')} />
      </Card>
    </>
  );
}

function SearchView({ search, send }: { search: TaplSearchPayload; send: (message: WebviewCommand) => void }): JSX.Element {
  const { t } = useI18n();
  return (
    <>
      <Topbar
        eyebrow={t('searchMode', { mode: search.mode })}
        title={t('searchResults')}
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>{t('back')}</button>
            <SearchForm defaultQuery={search.query} send={send} />
          </div>
        }
      />
      <Card title={search.query}>
        {search.results.length ? (
          <div className="tapl-stack">
            {search.results.map((result, index) => <SearchResult key={`${result.id ?? result.stable_id}-${index}`} result={result} send={send} />)}
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
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>{t('back')}</button>}
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
            <button className="btn btn-primary btn-sm mt-3" type="button" onClick={() => send({ command: 'openArchive', archiveId: detail.archive_id as string })}>
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

function ErrorView({ message }: { message: string }): JSX.Element {
  const { t } = useI18n();
  return (
    <Card title={t('taplUnavailable')}>
      <p className="text-error">{message}</p>
    </Card>
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

function Stat({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: string }): JSX.Element {
  return (
    <article className={`tapl-stat stat min-w-0 ${tone ? statusClass(tone) : ''}`}>
      <span className="stat-title">{label}</span>
      <strong className="stat-value text-xl">{value}</strong>
      <small className="stat-desc">{detail}</small>
    </article>
  );
}

function ProgressMeter({ label, value, detail }: { label: string; value: number; detail: string }): JSX.Element {
  return (
    <div className="tapl-progress-card">
      <div className="flex items-center justify-between gap-3">
        <span className="tapl-eyebrow">{label}</span>
        <strong>{value}%</strong>
      </div>
      <progress className="progress progress-primary tapl-progress" value={value} max={100} />
      <small className="tapl-muted">{detail}</small>
    </div>
  );
}

function SearchForm({ defaultQuery, send }: { defaultQuery: string; send: (message: WebviewCommand) => void }): JSX.Element {
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
        className="input input-bordered input-sm join-item"
        value={query}
        placeholder={t('searchWorkflowHistory')}
        aria-label={t('searchWorkflowHistory')}
        onChange={(event) => setQuery(event.target.value)}
      />
      <button className="btn btn-primary btn-sm join-item" type="submit">{t('search')}</button>
    </form>
  );
}

function RecordTabs({ tabs }: { tabs: Array<{ id: string; label: string; count: number; content: ReactNode }> }): JSX.Element {
  const [selected, setSelected] = useState(tabs[0]?.id ?? '');
  const selectedTab = tabs.find((tab) => tab.id === selected) ?? tabs[0];
  return (
    <div>
      <div className="tapl-tabs tabs-boxed" role="tablist">
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

function TaskBoard({ tasks }: { tasks: TaplItem[] }): JSX.Element {
  const { t } = useI18n();
  const orderedTasks = [...tasks].sort((left, right) => (
    left.stable_id.localeCompare(right.stable_id, undefined, { numeric: true, sensitivity: 'base' })
  ));

  if (!orderedTasks.length) {
    return (
      <section className="tapl-journey-empty" aria-label={t('workItemSteps')}>
        <span className="tapl-journey-empty-icon" aria-hidden="true">✓</span>
        <div>
          <h3 className="m-0 text-sm font-semibold">{t('noWorkItemsYet')}</h3>
          <p className="tapl-muted m-0 mt-1 text-xs">{t('approvedTasksAppear')}</p>
        </div>
      </section>
    );
  }

  const upperStepCount = Math.ceil(orderedTasks.length / 2);
  const journeyStyle = {
    '--journey-columns': String(upperStepCount)
  } as CSSProperties;

  return (
    <section
      className={`tapl-journey ${orderedTasks.length === 1 ? 'single' : ''} ${orderedTasks.length > 8 ? 'dense' : ''}`}
      style={journeyStyle}
      aria-label={t('workItemsInOrder', { count: orderedTasks.length })}
    >
      <ol className="tapl-journey-list">
        {orderedTasks.map((task, index) => {
          const isReturnStep = index >= upperStepCount;
          const returnIndex = index - upperStepCount;
          const column = isReturnStep ? upperStepCount - returnIndex : index + 1;
          const row = isReturnStep ? 2 : 1;
          const stepStyle = {
            '--step-column': String(column),
            '--step-row': String(row)
          } as CSSProperties;
          return (
            <TaskStep
              key={task.stable_id}
              task={task}
              index={index}
              style={stepStyle}
              phase={isReturnStep ? 'return' : 'outbound'}
              turns={orderedTasks.length > 1 && index === upperStepCount - 1}
              isLast={index === orderedTasks.length - 1}
            />
          );
        })}
      </ol>
      <div className="tapl-journey-direction" aria-hidden="true">
        <span>{t('start')}</span>
        <span>{t('continueLabel')}</span>
      </div>
    </section>
  );
}

function TaskStep({
  task,
  index,
  style,
  phase,
  turns,
  isLast
}: {
  task: TaplItem;
  index: number;
  style: CSSProperties;
  phase: 'outbound' | 'return';
  turns: boolean;
  isLast: boolean;
}): JSX.Element {
  const taskStatus = task.status || 'Pending';
  const tone = statusClass(taskStatus);
  const summary = conciseText(task.body || task.title, 132);
  const metadata = [formatTimestamp(task.updated_at), task.source].filter(Boolean).join(' / ');
  const isCurrent = taskStatus === 'In Progress';
  return (
    <li
      className={`tapl-journey-step ${tone} ${phase} ${turns ? 'turns' : ''} ${isLast ? 'is-last' : ''}`}
      style={style}
      aria-current={isCurrent ? 'step' : undefined}
    >
      <div className="tapl-step-node" aria-hidden="true">
        <span>{String(index + 1).padStart(2, '0')}</span>
      </div>
      <article className="tapl-step-card">
        <div className="tapl-step-meta">
          <span className="tapl-task-id">{task.stable_id}</span>
          <Badge label={taskStatus} tone={tone} />
        </div>
        <h4 className="tapl-step-title">{task.title}</h4>
        {summary && summary !== task.title ? <p className="tapl-step-summary">{summary}</p> : null}
        <CustomFieldSummary fields={task.custom_fields} />
        {metadata ? <p className="tapl-step-detail">{metadata}</p> : null}
      </article>
    </li>
  );
}

function ItemList({ items, empty }: { items: TaplItem[]; empty: string }): JSX.Element {
  if (!items.length) {
    return <p className="tapl-empty-state">{empty}</p>;
  }
  return (
    <div className="tapl-stack">
      {items.map((item) => <ItemCard key={`${item.kind}-${item.stable_id}`} item={item} />)}
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
      {events.map((event, index) => <EventCard key={`${event.event_type}-${event.created_at}-${index}`} event={event} />)}
    </div>
  );
}

function EventCard({ event }: { event: TaplEvent }): JSX.Element {
  const { t } = useI18n();
  return (
    <article className="tapl-item tapl-record-card">
      <div className="mb-2 flex items-start justify-between gap-2">
        <strong>{event.event_type}{event.tool_name ? ` ${event.tool_name}` : ''}</strong>
        <Badge label={event.mode} />
      </div>
      <p className="m-0">{event.message || t('recorded')}</p>
      <p className="tapl-muted mt-2 text-xs">{formatTimestamp(event.created_at)}</p>
    </article>
  );
}

function ArchiveList({ archives, send }: { archives: TaplArchive[]; send: (message: WebviewCommand) => void }): JSX.Element {
  const { t } = useI18n();
  if (!archives.length) {
    return <p className="tapl-empty-state">{t('noTaplArchives')}</p>;
  }
  return (
    <div className="tapl-stack">
      {archives.map((archive) => (
        <button
          key={archive.id}
          className="tapl-item tapl-clickable tapl-archive-button"
          type="button"
          onClick={() => send({ command: 'openArchive', archiveId: archive.id })}
        >
          <span className="tapl-archive-title">{archive.slug}</span>
          <span className="tapl-muted mt-1 block text-sm">{conciseText(archive.summary || t('noSummary'), 140)}</span>
          <span className="tapl-muted mt-1 block text-xs">{formatTimestamp(archive.created_at)}</span>
        </button>
      ))}
    </div>
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

function RunFocus({ status, counts }: { status: TaplStatus; counts: Record<string, number> }): JSX.Element {
  const { t } = useI18n();
  const currentPlan = status.plans[0];
  const blockedTasks = status.tasks.filter((task) => task.status === 'Blocked');
  const latestFinding = status.findings[0];
  const nextTask = status.tasks.find((task) => task.status === 'In Progress')
    ?? status.tasks.find((task) => task.status === 'Pending');
  return (
    <Card title={t('runHealth')} eyebrow={t('focus')} className="tapl-focus-card">
      <div className="tapl-detail-grid">
        <FocusRow label={t('currentPlan')} value={currentPlan ? currentPlan.title : t('noPlanRecordsTitle')} detail={currentPlan?.stable_id} />
        <FocusRow label={t('nextWork')} value={nextTask ? nextTask.title : t('noActiveTask')} detail={nextTask?.stable_id} />
        <FocusRow label={t('blocked')} value={t('blockedWorkItems', { count: counts.Blocked ?? blockedTasks.length })} detail={blockedTasks[0]?.title} />
        <FocusRow label={t('latestFinding')} value={latestFinding ? latestFinding.title : t('noFindings')} detail={latestFinding?.stable_id} />
      </div>
    </Card>
  );
}

function FocusRow({ label, value, detail }: { label: string; value: string; detail?: string }): JSX.Element {
  return (
    <div className="tapl-detail-row tapl-focus-row">
      <span className="tapl-muted text-xs">{label}</span>
      <strong className="text-sm">{value}</strong>
      {detail ? <small className="tapl-muted">{detail}</small> : null}
    </div>
  );
}

function SearchResult({ result, send }: { result: TaplSearchResult; send: (message: WebviewCommand) => void }): JSX.Element {
  const { kind, status } = useI18n();
  const content = (
    <>
      <div className="mb-1 flex items-start justify-between gap-2">
        <strong><span className="kbd kbd-xs">{result.stable_id}</span> {result.title}</strong>
        <Badge label={kind(result.kind)} />
      </div>
      {result.status ? <span className="tapl-muted text-sm">{status(result.status)}</span> : null}
      {result.snippet ? <p className="tapl-muted mt-2 text-sm">{conciseText(result.snippet, 180)}</p> : null}
      <p className="tapl-muted mt-2 text-xs">{result.search_source}{result.source ? ` / ${result.source}` : ''}</p>
    </>
  );
  if (typeof result.id !== 'number') {
    return <article className="tapl-item tapl-record-card">{content}</article>;
  }
  return (
    <button className="tapl-item tapl-clickable tapl-record-card" type="button" onClick={() => send({ command: 'openSearchResult', itemId: result.id as number })}>
      {content}
    </button>
  );
}

function ItemMetadata({ item }: { item: TaplItemDetail }): JSX.Element {
  const { t } = useI18n();
  const executionFields: Array<[string, unknown]> = [
    [t('spec'), item.spec_id],
    [t('goal'), item.goal],
    [t('action'), item.action],
    [t('verification'), item.verification],
    [t('result'), item.result],
    [t('blocker'), item.blocker],
    [t('nextAction'), item.next_action]
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

function CustomFieldSummary({ fields }: { fields?: Record<string, TaplJsonValue> }): JSX.Element | null {
  const { t } = useI18n();
  const entries = Object.entries(fields ?? {});
  if (!entries.length) {
    return null;
  }
  const visible = entries.filter(([, value]) => isCompactCustomValue(value)).slice(0, 2);
  const remaining = entries.length - visible.length;
  return (
    <div className="tapl-custom-summary" aria-label={t('customFields')}>
      {visible.map(([label, value]) => (
        <span key={label} className="tapl-custom-chip" title={`${label}: ${String(value)}`}>
          <span className="tapl-custom-chip-label">{label}</span>
          <span className="tapl-custom-chip-value">{String(value)}</span>
        </span>
      ))}
      {remaining > 0 ? (
        <span className="tapl-custom-more" title={t('customFieldCount', { count: entries.length })}>
          +{remaining}
        </span>
      ) : null}
    </div>
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
          <dd><JsonValue value={value} /></dd>
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
        {value.map((item, index) => <li key={index}><JsonValue value={item} depth={depth + 1} /></li>)}
      </ol>
    );
  }
  if (typeof value === 'object') {
    return (
      <dl className="tapl-json-object">
        {Object.entries(value).map(([label, item]) => (
          <div key={label} className="tapl-json-entry">
            <dt>{label}</dt>
            <dd><JsonValue value={item} depth={depth + 1} /></dd>
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

function isCompactCustomValue(value: TaplJsonValue): value is string | number | boolean {
  return value !== '' && (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean');
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
      nodes.push(<ul key={`ul-${nodes.length}`}>{list.map((item, index) => <li key={index}>{item}</li>)}</ul>);
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
      nodes.push(<h3 key={`h-${nodes.length}`} className="text-sm font-semibold">{heading[2]}</h3>);
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
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
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
