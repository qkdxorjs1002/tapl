import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import type {
  HostMessage,
  TaplArchive,
  TaplArchiveDetail,
  TaplEvent,
  TaplItem,
  TaplItemDetail,
  TaplSearchPayload,
  TaplSearchResult,
  TaplStatus,
  WebviewCommand,
  WebviewView
} from './types';
import { vscodeApi } from './vscodeApi';

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
  const restored = api.getState() as { view?: WebviewView } | undefined;
  const [view, setView] = useState<WebviewView | undefined>(restored?.view);

  useEffect(() => {
    const listener = (event: MessageEvent<HostMessage>) => {
      const message = event.data;
      if (!message || typeof message.type !== 'string') {
        return;
      }
      if (message.type === 'hydrate' || message.type === 'view:update') {
        setView(message.view);
        api.setState({ view: message.view });
      }
      if (message.type === 'error') {
        const errorView: WebviewView = { type: 'error', message: message.message };
        setView(errorView);
        api.setState({ view: errorView });
      }
    };
    window.addEventListener('message', listener);
    api.postMessage({ command: 'ready' });
    return () => window.removeEventListener('message', listener);
  }, [api]);

  if (!view) {
    return (
      <main className="tapl-shell">
        <section className="tapl-card">
          <div className="tapl-card-body">
            <span className="loading loading-spinner loading-md" />
            <p className="tapl-muted m-0">Loading tapl workflow...</p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="tapl-shell" data-theme="tapl">
      <ViewRenderer view={view} send={(message) => api.postMessage(message)} />
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
  const { status, archives, searchQuery } = view;
  const counts = { ...DEFAULT_TASK_COUNTS, ...(status.task_counts || {}) };
  const totalTasks = status.tasks.length;
  const completedTasks = counts.Completed ?? 0;
  const openTasks = (counts.Pending ?? 0) + (counts['In Progress'] ?? 0) + (counts.Blocked ?? 0);
  const completionPercent = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0;
  const activeSummary = status.active_run
    ? String(status.active_run.request_summary || status.active_run.slug || 'active')
    : 'No active run';
  const activeRunSlug = status.active_run ? String(status.active_run.slug || 'active') : 'No active run';
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
              <span className="tapl-eyebrow">workspace</span>
              <Badge label={activeRunSlug} tone={status.active_run ? 'in-progress' : undefined} />
            </div>
            <h1 className="m-0 text-3xl font-semibold">tapl Workflow</h1>
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
                Refresh
              </button>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'debug' })}>
                Debug
              </button>
            </div>
            <SearchForm defaultQuery={searchQuery} send={send} />
            <ProgressMeter
              label="Run progress"
              value={completionPercent}
              detail={`${completedTasks} of ${totalTasks} work items completed`}
            />
          </div>
        </div>
      </header>
      <section className="tapl-metric-grid">
        <Stat label="Open work" value={String(openTasks)} detail={`${activeCount} active / ${blockedCount} blocked`} tone={blockedCount ? 'blocked' : 'in-progress'} />
        <Stat label="Current plan" value={String(status.plans.length)} detail={currentPlan ? conciseText(currentPlan.title, 48) : 'no execution spec'} tone="info" />
        <Stat label="Next task" value={nextTask ? nextTask.stable_id : 'None'} detail={nextTask ? conciseText(nextTask.title, 48) : 'queue is clear'} tone="pending" />
        <Stat label="Archives" value={String(archives.length)} detail="recent saved runs" tone="completed" />
      </section>
      <section className="tapl-grid">
        <div className="tapl-main">
          <Card
            title="Active board"
            eyebrow="Work items"
            aside={<span className="tapl-muted text-sm">{status.incomplete_tasks} incomplete</span>}
          >
            <TaskBoard tasks={status.tasks} />
          </Card>
          <Card title="Workflow records" eyebrow="Views">
            <RecordTabs
              tabs={[
                { id: 'plan', label: 'Plan', count: status.plans.length, content: <ItemList items={status.plans} empty="No plan records." /> },
                { id: 'tasks', label: 'Tasks', count: status.tasks.length, content: <ItemList items={status.tasks} empty="No task records." /> },
                { id: 'findings', label: 'Findings', count: status.findings.length, content: <ItemList items={status.findings} empty="No finding records." /> }
              ]}
            />
          </Card>
        </div>
        <aside className="tapl-rail">
          <RunFocus status={status} counts={counts} />
          <Card title="Recent archives" eyebrow="Activity">
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
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>Back</button>}
      />
      <section className="tapl-stats">
        <Stat label="Archive" value="Saved" detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug} />
        <Stat label="Tasks" value={String(tasks.length)} detail={`${(counts.Pending ?? 0) + (counts['In Progress'] ?? 0) + (counts.Blocked ?? 0)} incomplete`} />
        <Stat label="Records" value={String(items.length)} detail={`${plans.length} plan / ${findings.length} findings`} />
        <Stat label="Events" value={String(detail?.events.length ?? 0)} detail={detail ? 'archived hook events' : 'detail unavailable'} />
      </section>
      <div className="flex flex-wrap gap-2">
        {TASK_STATUSES.map((status) => <Pill key={status} label={status} value={counts[status]} />)}
      </div>
      <section className="tapl-grid">
        <div className="tapl-main">
          <Card title="Archived workflow records">
            <RecordTabs
              tabs={[
                { id: 'plan', label: 'Plan', count: plans.length, content: <ItemList items={plans} empty={detail ? 'No plan records.' : 'Archive details unavailable.'} /> },
                { id: 'tasks', label: 'Tasks', count: tasks.length, content: <ItemList items={tasks} empty={detail ? 'No task records.' : 'Archive details unavailable.'} /> },
                { id: 'findings', label: 'Findings', count: findings.length, content: <ItemList items={findings} empty={detail ? 'No finding records.' : 'Archive details unavailable.'} /> }
              ]}
            />
          </Card>
        </div>
        <aside className="tapl-rail">
          <ArchiveSummary archive={archiveMeta} />
          <Card title="Other records">
            <ItemList items={otherItems} empty={detail ? 'No other archived records.' : 'Archive details unavailable.'} />
          </Card>
        </aside>
      </section>
      <footer>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          onClick={() => send({ command: 'archiveEvents', archiveId: archiveMeta.id })}
        >
          Hook Events
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
  const archiveMeta = detail?.archive ?? archive;
  const events = detail?.events ?? [];
  return (
    <>
      <Topbar
        eyebrow={archiveMeta.slug}
        title="Hook Events"
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>Back</button>}
      />
      <section className="tapl-stats">
        <Stat label="Archive" value="Saved" detail={formatTimestamp(archiveMeta.created_at) || archiveMeta.slug} />
        <Stat label="Events" value={String(events.length)} detail={detail ? 'archived hook events' : 'detail unavailable'} />
      </section>
      <Card title="Archived hook events">
        <EventList events={events} empty={detail ? 'No archived hook events.' : 'Archive details unavailable.'} />
      </Card>
    </>
  );
}

function DebugView({ status, send }: { status: TaplStatus; send: (message: WebviewCommand) => void }): JSX.Element {
  return (
    <>
      <Topbar
        eyebrow="Debug"
        title="Hook Events"
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>Back</button>}
      />
      <Card title="Recent hook events">
        <EventList events={status.recent_events} empty="No hook events." />
      </Card>
    </>
  );
}

function SearchView({ search, send }: { search: TaplSearchPayload; send: (message: WebviewCommand) => void }): JSX.Element {
  return (
    <>
      <Topbar
        eyebrow={`${search.mode} search`}
        title="Search Results"
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>Back</button>
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
          <p className="tapl-muted m-0">No results for {search.query}.</p>
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
  const title = detail?.title ?? result.title;
  const status = detail?.status ?? result.status;
  const content = detail?.body || detail?.raw_text || result.snippet || '';
  return (
    <>
      <Topbar
        eyebrow={`${detail?.kind ?? result.kind} ${detail?.stable_id ?? result.stable_id}`}
        title={title}
        action={<button className="btn btn-secondary btn-sm" type="button" onClick={() => send({ command: 'back' })}>Back</button>}
      />
      <div className="tapl-stack max-w-5xl">
        <Card title="Details">
          <DetailList
            fields={[
              ['Status', status],
              ['Run', detail?.run_slug],
              ['Run status', detail?.run_status],
              ['Source', detail?.source ?? result.source],
              ['Archive', detail?.archive_slug],
              ['Search source', result.search_source]
            ]}
          />
          {detail?.archive_id ? (
            <button className="btn btn-primary btn-sm mt-3" type="button" onClick={() => send({ command: 'openArchive', archiveId: detail.archive_id as string })}>
              Open Archive
            </button>
          ) : null}
        </Card>
        {content ? (
          <Card title="Content">
            <ReadableBlock content={content} />
          </Card>
        ) : null}
        {detail ? <ItemMetadata item={detail} /> : null}
      </div>
    </>
  );
}

function ErrorView({ message }: { message: string }): JSX.Element {
  return (
    <Card title="tapl unavailable">
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
        placeholder="Search workflow history"
        aria-label="Search workflow history"
        onChange={(event) => setQuery(event.target.value)}
      />
      <button className="btn btn-primary btn-sm join-item" type="submit">Search</button>
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
  return (
    <section className="tapl-board" aria-label="Tasks grouped by status">
      {TASK_STATUSES.map((status) => {
        const statusTasks = tasks.filter((task) => task.status === status);
        return (
          <section key={status} className={`tapl-lane ${statusClass(status)} ${statusTasks.length ? '' : 'empty'}`}>
            <div className="tapl-lane-body">
              <div className="tapl-lane-header">
                <div className="flex min-w-0 items-center gap-2">
                  <span className={`tapl-status-dot ${statusClass(status)}`} />
                  <h3 className="m-0 text-sm font-semibold">{status}</h3>
                </div>
                <span className="badge badge-sm">{statusTasks.length}</span>
              </div>
              <div className="tapl-stack">
                {statusTasks.slice(0, 5).map((task) => <TaskCard key={task.stable_id} task={task} />)}
                {statusTasks.length > 5 ? <p className="tapl-muted m-0 text-xs">+{statusTasks.length - 5} more</p> : null}
                {!statusTasks.length ? <p className="tapl-empty-state">No work items.</p> : null}
              </div>
            </div>
          </section>
        );
      })}
    </section>
  );
}

function TaskCard({ task }: { task: TaplItem }): JSX.Element {
  const summary = conciseText(task.body || task.title, 150);
  const hasBadges = Boolean(task.status);
  return (
    <article className="tapl-item tapl-task-card">
      <div className="tapl-task-meta">
        <span className="tapl-task-id kbd kbd-xs">{task.stable_id}</span>
        {hasBadges ? (
          <div className="tapl-task-badges">
            {task.status ? <Badge label={task.status} tone={statusClass(task.status)} /> : null}
          </div>
        ) : null}
      </div>
      <h4 className="m-0 text-sm font-semibold">{task.title}</h4>
      {summary && summary !== task.title ? <p className="tapl-muted mt-2 text-xs">{summary}</p> : null}
      <p className="tapl-muted mt-2 text-xs">{[formatTimestamp(task.updated_at), task.source].filter(Boolean).join(' / ')}</p>
    </article>
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
  return (
    <article className="tapl-item tapl-record-card">
      <div className="mb-2 flex items-start justify-between gap-2">
        <strong>{event.event_type}{event.tool_name ? ` ${event.tool_name}` : ''}</strong>
        <Badge label={event.mode} />
      </div>
      <p className="m-0">{event.message || 'recorded'}</p>
      <p className="tapl-muted mt-2 text-xs">{formatTimestamp(event.created_at)}</p>
    </article>
  );
}

function ArchiveList({ archives, send }: { archives: TaplArchive[]; send: (message: WebviewCommand) => void }): JSX.Element {
  if (!archives.length) {
    return <p className="tapl-empty-state">No archives.</p>;
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
          <span className="tapl-muted mt-1 block text-sm">{conciseText(archive.summary || 'No summary', 140)}</span>
          <span className="tapl-muted mt-1 block text-xs">{formatTimestamp(archive.created_at)}</span>
        </button>
      ))}
    </div>
  );
}

function ArchiveSummary({ archive }: { archive: TaplArchive }): JSX.Element {
  return (
    <Card title="Summary">
      <p>{archive.summary || 'No summary recorded.'}</p>
      {archive.request_summary ? <p className="tapl-muted">{archive.request_summary}</p> : null}
      <DetailList
        fields={[
          ['Run', archive.run_slug],
          ['Created', formatTimestamp(archive.run_created_at)],
          ['Updated', formatTimestamp(archive.run_updated_at)],
          ['Archived run', formatTimestamp(archive.run_archived_at)]
        ]}
      />
    </Card>
  );
}

function RunFocus({ status, counts }: { status: TaplStatus; counts: Record<string, number> }): JSX.Element {
  const currentPlan = status.plans[0];
  const blockedTasks = status.tasks.filter((task) => task.status === 'Blocked');
  const latestFinding = status.findings[0];
  const nextTask = status.tasks.find((task) => task.status === 'In Progress')
    ?? status.tasks.find((task) => task.status === 'Pending');
  return (
    <Card title="Run health" eyebrow="Focus" className="tapl-focus-card">
      <div className="tapl-detail-grid">
        <FocusRow label="Current plan" value={currentPlan ? currentPlan.title : 'No plan records'} detail={currentPlan?.stable_id} />
        <FocusRow label="Next work" value={nextTask ? nextTask.title : 'No active task'} detail={nextTask?.stable_id} />
        <FocusRow label="Blocked" value={`${counts.Blocked ?? blockedTasks.length} work items`} detail={blockedTasks[0]?.title} />
        <FocusRow label="Latest finding" value={latestFinding ? latestFinding.title : 'No findings'} detail={latestFinding?.stable_id} />
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
  const content = (
    <>
      <div className="mb-1 flex items-start justify-between gap-2">
        <strong><span className="kbd kbd-xs">{result.stable_id}</span> {result.title}</strong>
        <Badge label={result.kind} />
      </div>
      {result.status ? <span className="tapl-muted text-sm">{result.status}</span> : null}
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
  const executionFields: Array<[string, unknown]> = [
    ['Spec', item.spec_id],
    ['Goal', item.goal],
    ['Action', item.action],
    ['Verification', item.verification],
    ['Result', item.result],
    ['Blocker', item.blocker],
    ['Next Action', item.next_action]
  ];
  const auditFields: Array<[string, unknown]> = [
    ['Related IDs', item.related_ids],
    ['Impact', item.impact],
    ['Request', item.request_summary],
    ['Updated', formatTimestamp(item.updated_at)],
    ['Archived at', formatTimestamp(item.archive_created_at)]
  ];
  return (
    <>
      <Card title="Execution">
        <DetailList fields={executionFields} empty="No execution metadata." />
      </Card>
      <Card title="Audit">
        <DetailList fields={auditFields} empty="No audit metadata." />
      </Card>
    </>
  );
}

function DetailList({ fields, empty }: { fields: Array<[string, unknown]>; empty?: string }): JSX.Element {
  const rows = fields.filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!rows.length) {
    return <p className="tapl-muted m-0">{empty ?? 'Not recorded.'}</p>;
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
  const blocks = useMemo(() => parseReadableBlocks(String(content ?? '')), [content]);
  if (!blocks.length) {
    return <p className="tapl-muted m-0">Not recorded.</p>;
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
  return <span className={`badge badge-outline ${tone ?? statusClass(label)}`}>{label}</span>;
}

function Pill({ label, value }: { label: string; value: number | undefined }): JSX.Element {
  return <Badge label={`${label} ${value ?? 0}`} tone={statusClass(label)} />;
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
