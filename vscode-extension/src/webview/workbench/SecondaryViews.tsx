import { ValueTree } from './ValueTree';
import { useEffect, useState, type ReactNode } from 'react';
import { useI18n } from '../i18n';
import type {
  TaplArchive,
  TaplEvent,
  TaplItem,
  TaplSearchResult,
  TaplStatus,
  WebviewCommand,
  WebviewView
} from '../types';
import { EmptyState, PageHeading, StatusMark, TaskDuration } from './components';
import { Icon } from './Icon';

type Send = (message: WebviewCommand) => void;
type SecondaryScreen = Extract<WebviewView, { type: 'archive' | 'archiveEvents' | 'debug' | 'search' | 'error' }>;

/** Compatibility screens for payloads that do not contain a complete RUN snapshot. */
export function SecondaryView({
  view,
  send,
  back
}: {
  view: SecondaryScreen;
  send: Send;
  back?: () => void;
}): JSX.Element {
  const { t } = useI18n();
  if (view.type === 'archive' || view.type === 'archiveEvents')
    return <ArchivePage view={view} send={send} back={back} />;
  if (view.type === 'debug') return <DebugPage status={view.status} back={back} />;
  if (view.type === 'search') return <SearchPage view={view} send={send} back={back} />;
  return (
    <div className="wb-secondary">
      <PageHeading title={t('taplUnavailable')} back={back} />
      <div role="alert">
        <EmptyState title={t('errorLabel')} help={view.message} icon="alert">
          <div className="wb-secondary-actions">
            <button type="button" className="btn btn-primary btn-sm" onClick={() => send({ command: 'refresh' })}>
              <Icon name="refresh" />
              {t('wbRetry')}
            </button>
            <button type="button" className="btn btn-sm" onClick={() => send({ command: 'chooseWorkspace' })}>
              <Icon name="folder" />
              {t('chooseWorkspace')}
            </button>
          </div>
        </EmptyState>
      </div>
    </div>
  );
}

export function PageLoading({ back }: { back?: () => void }): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="wb-secondary">
      <PageHeading title={t('loadingWorkflow')} back={back} />
      <div className="wb-secondary-loading" role="status">
        <span className="loading loading-spinner loading-md" />
        <span>{t('wbLoad')}</span>
      </div>
    </div>
  );
}

function ArchivePage({
  view,
  send,
  back
}: {
  view: Extract<SecondaryScreen, { type: 'archive' | 'archiveEvents' }>;
  send: Send;
  back?: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const archive = view.detail?.archive ?? view.archive;
  const events = view.detail?.events ?? [];
  const records = view.detail?.items ?? [];
  const eventsOnly = view.type === 'archiveEvents';
  return (
    <div className="wb-secondary">
      <PageHeading title={eventsOnly ? t('hookEvents') : archive.slug || archive.id} back={back} />
      <div className="wb-secondary-context">
        <span className="badge badge-outline badge-sm">{t('wbArchived')}</span>
        <span className="wb-mono">{archive.id}</span>
        <Timestamp value={archive.created_at} />
        {eventsOnly && <span>{archive.slug}</span>}
      </div>
      <dl className="wb-secondary-counts">
        {!eventsOnly && (
          <div>
            <dt>{t('records')}</dt>
            <dd>{view.detail ? records.length : t('detailUnavailable')}</dd>
          </div>
        )}
        <div>
          <dt>{t('events')}</dt>
          <dd>{view.detail ? events.length : t('detailUnavailable')}</dd>
        </div>
        {!eventsOnly && (
          <div>
            <dt>{t('tasks')}</dt>
            <dd>{view.detail ? records.filter((item) => item.kind === 'task').length : t('detailUnavailable')}</dd>
          </div>
        )}
      </dl>
      {eventsOnly ? (
        <section className="wb-secondary-section">
          <h2>{t('archivedHookEvents')}</h2>
          {view.detail ? (
            <EventRows events={events} empty={t('noArchivedHookEvents')} />
          ) : (
            <EmptyState title={t('archiveDetailsUnavailable')} icon="archive" />
          )}
        </section>
      ) : (
        <>
          <div className="wb-secondary-reading">
            <div className="wb-secondary-document">
              <section className="wb-secondary-section">
                <h2>{t('summary')}</h2>
                <p className="wb-secondary-prose">{archive.summary || t('noSummaryRecorded')}</p>
                {archive.request_summary && (
                  <>
                    <h3>{t('request')}</h3>
                    <p className="wb-secondary-prose">{archive.request_summary}</p>
                  </>
                )}
              </section>
              <section className="wb-secondary-section">
                <div className="wb-secondary-section-heading">
                  <h2>{t('archivedWorkflowRecords')}</h2>
                  {view.detail && <span className="wb-secondary-meta">{records.length}</span>}
                </div>
                {view.detail ? (
                  records.length ? (
                    <div className="wb-secondary-records">
                      {records.map((item, index) => (
                        <ArchivedRecord
                          key={`${item.source_db ?? archive.source_db ?? ''}:${item.id ?? item.stable_id}:${index}`}
                          item={item}
                          archive={archive}
                          send={send}
                        />
                      ))}
                    </div>
                  ) : (
                    <EmptyState title={t('wbNoPageRecords')} icon="file" />
                  )
                ) : (
                  <EmptyState title={t('archiveDetailsUnavailable')} icon="file" />
                )}
              </section>
            </div>
            <aside className="wb-secondary-properties">
              <h2>{t('wbProperties')}</h2>
              <ArchiveFacts archive={archive} />
              {records.some((item) => item.kind === 'task') && (
                <>
                  <h3>{t('tasks')}</h3>
                  <dl className="wb-secondary-facts">
                    {Object.entries(taskCounts(records)).map(([status, count]) => (
                      <div key={status}>
                        <dt>
                          <StatusMark value={status} />
                        </dt>
                        <dd>{count}</dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
            </aside>
          </div>
          <footer className="wb-secondary-footer">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() =>
                send({
                  command: 'archiveEvents',
                  archiveId: archive.id,
                  source_db: archive.source_db ?? view.archive.source_db
                })
              }
            >
              {t('hookEvents')}
              {view.detail && <span className="badge badge-sm">{events.length}</span>}
              <Icon name="arrow" />
            </button>
            {!view.detail && <span className="wb-secondary-meta">{t('detailUnavailable')}</span>}
          </footer>
        </>
      )}
    </div>
  );
}

function ArchiveFacts({ archive }: { archive: TaplArchive }): JSX.Element {
  const { t } = useI18n();
  return (
    <Facts
      rows={[
        [t('archive'), archive.slug],
        [t('run'), [archive.run_slug, archive.run_id].filter(Boolean).join(' · ')],
        [t('created'), archive.run_created_at && <Timestamp value={archive.run_created_at} />],
        [t('updated'), archive.run_updated_at && <Timestamp value={archive.run_updated_at} />],
        [t('archivedRun'), archive.run_archived_at && <Timestamp value={archive.run_archived_at} />],
        [t('archivedAt'), <Timestamp value={archive.created_at} />],
        [t('source'), archive.source_db]
      ]}
    />
  );
}

function ArchivedRecord({ item, archive, send }: { item: TaplItem; archive: TaplArchive; send: Send }): JSX.Element {
  const { t, kind } = useI18n();
  return (
    <article className="wb-secondary-record">
      <div className="wb-result-meta">
        <span className="badge badge-outline badge-sm">{kind(item.kind)}</span>
        <span className="wb-mono">{item.stable_id}</span>
        <StatusMark value={item.status} />
        {item.kind === 'task' && <TaskDuration item={item} />}
      </div>
      <div className="wb-secondary-record-heading">
        <h3>{item.title}</h3>
        {typeof item.id === 'number' && (
          <button
            className="btn btn-ghost btn-xs btn-square"
            type="button"
            title={t('details')}
            aria-label={`${t('details')}: ${item.stable_id}`}
            onClick={() =>
              send({
                command: 'openSearchResult',
                itemId: item.id as number,
                source_db: item.source_db ?? archive.source_db
              })
            }
          >
            <Icon name="arrow" />
          </button>
        )}
      </div>
      {item.body && <p className="wb-secondary-prose">{item.body}</p>}
      {!!Object.keys(item.custom_fields ?? {}).length && (
        <section className="wb-secondary-custom">
          <h4>{t('customFields')}</h4>
          <Facts
            rows={Object.entries(item.custom_fields ?? {}).map(([key, value]) => [
              key,
              <StructuredValue value={value} />
            ])}
          />
        </section>
      )}
      {(item.source || item.updated_at || item.run_id) && (
        <div className="wb-secondary-meta">
          {item.source && <span>{item.source}</span>}
          {item.updated_at && <Timestamp value={item.updated_at} />}
          {item.run_id && <span className="wb-mono">{item.run_id}</span>}
        </div>
      )}
      <StructuredInspect value={item} />
    </article>
  );
}

function DebugPage({ status, back }: { status: TaplStatus; back?: () => void }): JSX.Element {
  const { t, status: displayStatus } = useI18n();
  return (
    <div className="wb-secondary">
      <PageHeading title={t('debug')} back={back} />
      <dl className="wb-secondary-counts">
        {[
          [t('plan'), status.counts?.plans ?? status.plans.length],
          [t('tasks'), status.counts?.tasks ?? status.tasks.length],
          [t('findings'), status.counts?.findings ?? status.findings.length],
          [t('events'), status.recent_events.length],
          [t('activeBatches'), status.counts?.active_batches ?? status.active_batches?.length ?? 0],
          [t('activeExecutions'), status.counts?.active_executions ?? status.active_executions?.length ?? 0]
        ].map(([label, count]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{count}</dd>
          </div>
        ))}
      </dl>
      <details className="wb-secondary-disclosure">
        <summary>
          {t('wbDiagnostics')}
          <Icon name="chevron" />
        </summary>
        <div className="wb-secondary-disclosure-body">
          <Facts
            rows={[
              [t('incompleteCount', { count: status.incomplete_tasks }), status.incomplete_tasks],
              ...Object.entries(status.task_counts).map(([key, value]): [string, ReactNode] => [
                displayStatus(key),
                value
              ])
            ]}
          />
          {!!Object.keys(status.schema).length && (
            <>
              <h3>{t('wbSchema')}</h3>
              <Facts rows={Object.entries(status.schema)} />
            </>
          )}
          <StructuredInspect value={status} />
        </div>
      </details>
      <section className="wb-secondary-section">
        <h2>{t('recentHookEvents')}</h2>
        <EventRows events={status.recent_events} empty={t('noHookEvents')} />
      </section>
    </div>
  );
}

function EventRows({ events, empty }: { events: TaplEvent[]; empty: string }): JSX.Element {
  const { t } = useI18n();
  if (!events.length) return <EmptyState title={empty} icon="debug" />;
  const ordered = events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      const delta = Date.parse(a.event.created_at) - Date.parse(b.event.created_at);
      return Number.isNaN(delta) ? a.index - b.index : delta || a.index - b.index;
    });
  return (
    <ol className="wb-secondary-events">
      {ordered.map(({ event, index }) => (
        <li key={`${event.event_type}:${event.created_at}:${index}`} className="wb-secondary-event">
          <span className="wb-secondary-event-dot" aria-hidden="true" />
          <div className="wb-secondary-event-content">
            <div className="wb-secondary-event-heading">
              <strong>{event.event_type}</strong>
              {event.tool_name && <code>{event.tool_name}</code>}
              <span className="badge badge-outline badge-sm">{event.mode}</span>
              <Timestamp value={event.created_at} />
            </div>
            <p className="wb-secondary-prose">{event.message || t('recorded')}</p>
            <StructuredInspect value={event} />
          </div>
        </li>
      ))}
    </ol>
  );
}

function SearchPage({
  view,
  send,
  back
}: {
  view: Extract<SecondaryScreen, { type: 'search' }>;
  send: Send;
  back?: () => void;
}): JSX.Element {
  const { t } = useI18n();
  const [query, setQuery] = useState(view.search.query);
  useEffect(() => setQuery(view.search.query), [view.search.query]);
  return (
    <div className="wb-secondary">
      <PageHeading title={t('searchResults')} back={back} />
      <form
        className="wb-search-box"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim()) send({ command: 'search', query: query.trim() });
        }}
      >
        <label className="input input-sm">
          <Icon name="search" />
          <span className="wb-sr-only">{t('searchWorkflowHistory')}</span>
          <input
            value={query}
            placeholder={t('searchWorkflowHistory')}
            onChange={(event) => setQuery(event.target.value)}
            data-wb-focus="hybrid-query"
          />
        </label>
        <button type="submit" className="btn btn-primary btn-sm">
          {t('search')}
        </button>
      </form>
      <div className="wb-secondary-context">
        <span>{t('searchMode', { mode: view.search.mode })}</span>
        <span>
          {t('wbResults')} <strong>{view.search.results.length}</strong>
        </span>
      </div>
      {view.search.results.length ? (
        <div className="wb-flat-results">
          {view.search.results.map((result, index) => (
            <SearchRow
              key={`${result.source_db ?? ''}:${result.id ?? result.stable_id}:${index}`}
              result={result}
              send={send}
            />
          ))}
        </div>
      ) : (
        <EmptyState title={t('noResultsFor', { query: view.search.query })} help={t('wbNoMatchesHelp')} icon="search" />
      )}
    </div>
  );
}

function SearchRow({ result, send }: { result: TaplSearchResult; send: Send }): JSX.Element {
  const { kind } = useI18n();
  const content = (
    <>
      <span className="wb-result-meta">
        <span className="badge badge-outline badge-sm">{kind(result.kind)}</span>
        <span className="wb-mono">{result.stable_id}</span>
        <StatusMark value={result.status} />
      </span>
      <h3>{result.title}</h3>
      {result.snippet && <p>{result.snippet}</p>}
      <span className="wb-result-tail">
        <span>{[result.search_source, result.source].filter(Boolean).join(' · ')}</span>
        {result.run_id && <span className="wb-mono">{result.run_id}</span>}
        {result.source_db && <span className="wb-mono">{result.source_db}</span>}
        {result.score !== undefined && <span>{result.score}</span>}
      </span>
    </>
  );
  return typeof result.id === 'number' ? (
    <button
      type="button"
      className="wb-search-result"
      data-wb-focus={`hybrid-result:${result.source_db ?? ''}:${result.id}`}
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
  ) : (
    <article className="wb-search-result">{content}</article>
  );
}

function Timestamp({ value }: { value?: string }): JSX.Element | null {
  const { locale } = useI18n();
  if (!value) return null;
  const date = new Date(value);
  return <time dateTime={value}>{Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale)}</time>;
}

function Facts({ rows }: { rows: Array<[string, ReactNode]> }): JSX.Element {
  return (
    <dl className="wb-secondary-facts">
      {rows
        .filter(([, value]) => value !== undefined && value !== null && value !== '')
        .map(([label, value], index) => (
          <div key={`${label}:${index}`}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function StructuredValue({ value }: { value: unknown }): JSX.Element {
  return value !== null && typeof value === 'object' ? (
    <ValueTree value={value} />
  ) : (
    <span>{value === null ? 'null' : String(value)}</span>
  );
}

function StructuredInspect({ value }: { value: unknown }): JSX.Element {
  const { t } = useI18n();
  return (
    <details className="wb-secondary-inspect">
      <summary>{t('wbInspect')}</summary>
      <ValueTree value={value} />
    </details>
  );
}

function taskCounts(records: TaplItem[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of records)
    if (item.kind === 'task') counts[item.status || 'Pending'] = (counts[item.status || 'Pending'] ?? 0) + 1;
  return counts;
}
