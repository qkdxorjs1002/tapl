import { ValueTree } from './workbench/ValueTree';
import { FormEvent, useEffect, useState } from 'react';
import type { AssociativeMemory, MemoryDiagnostics, WebviewCommand, WebviewView } from './types';
import { useI18n } from './i18n';
import { EmptyState, PageHeading } from './workbench/components';
import { Icon } from './workbench/Icon';
import { MemoryMindmap } from './workbench/MemoryMindmap';

type MemoryScreen = Extract<WebviewView, { type: 'memories' | 'memory' | 'memorySource' }>;
type Send = (message: WebviewCommand) => void;

export function MemoryView({
  view,
  supported,
  send,
  back,
  workspaceKey
}: {
  view: MemoryScreen;
  supported: boolean;
  send: Send;
  back?: () => void;
  workspaceKey?: string;
}): JSX.Element {
  const { t } = useI18n();
  return (
    <div className="wb-secondary wb-memory-page">
      <div className="wb-secondary-titlebar">
        <PageHeading
          title={t(view.type === 'memories' ? 'memories' : view.type === 'memory' ? 'memoryDetail' : 'memoryRunSource')}
          back={back}
        />
        {supported && (
          <button
            type="button"
            className="btn btn-ghost btn-sm btn-square"
            title={t('refresh')}
            aria-label={t('refresh')}
            onClick={() => send({ command: 'refresh' })}
          >
            <Icon name="refresh" />
          </button>
        )}
      </div>
      {!supported ? (
        <EmptyState title={t('memoryUnsupported')} icon="book" />
      ) : view.type === 'memories' ? (
        <MemoryList view={view} send={send} workspaceKey={workspaceKey} />
      ) : view.type === 'memory' ? (
        view.memory && view.memory.state !== 'deleted' ? (
          <MemoryDetail memory={view.memory} send={send} />
        ) : (
          <EmptyState title={t('memoryUnavailable')} icon="book" />
        )
      ) : (
        <MemoryRunSource view={view} />
      )}
    </div>
  );
}

function MemoryList({
  view,
  send,
  workspaceKey
}: {
  view: Extract<WebviewView, { type: 'memories' }>;
  send: Send;
  workspaceKey?: string;
}): JSX.Element {
  const { t } = useI18n();
  const [query, setQuery] = useState(view.query);
  useEffect(() => {
    setQuery(view.query);
  }, [view.query]);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    send({ command: 'memories', query: query.trim(), offset: 0 });
  };
  const limit = Math.max(1, view.limit || 20);
  return (
    <div className="wb-memory-list">
      <div className="wb-memory-intro">
        <div className="wb-memory-scope">
          <span>{t('wbMemoryScope')}</span>
          <ReadOnlyBadge />
        </div>
        <form className="wb-search-box" role="search" aria-label={t('searchMemories')} onSubmit={submit}>
          <label className="input input-sm">
            <Icon name="search" />
            <span className="wb-sr-only">{t('searchMemories')}</span>
            <input
              type="search"
              maxLength={500}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('searchMemories')}
              data-wb-focus="memory-query"
            />
          </label>
          <button className="btn btn-sm" type="submit" data-wb-focus="memory-submit">
            {t('search')}
          </button>
        </form>
      </div>
      {view.diagnostics && <MemoryDiagnosticRows diagnostics={view.diagnostics} />}
      <p className="wb-search-context" role="status">
        {t('memoryRange', {
          start: view.memories.length ? view.offset + 1 : 0,
          end: view.offset + view.memories.length,
          total: view.total
        })}
        <span className="wb-memory-map-scope">{t('wbMemoryMapPage')}</span>
      </p>
      {view.memories.length ? (
        <MemoryMindmap
          memories={view.memories}
          send={send}
          cameraKey={JSON.stringify(['memories', workspaceKey ?? '', view.query, view.offset])}
        />
      ) : (
        <EmptyState
          title={t(view.query ? 'noMemoryMatches' : 'noMemories')}
          help={view.query ? t('wbNoMatchesHelp') : t('memoryIntro')}
          icon={view.query ? 'search' : 'book'}
        >
          {view.query && (
            <button
              className="btn btn-sm"
              type="button"
              onClick={() => send({ command: 'memories', query: '', offset: 0 })}
            >
              {t('wbReset')}
            </button>
          )}
        </EmptyState>
      )}
      <nav className="wb-secondary-pagination" aria-label={t('memories')}>
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          disabled={view.offset === 0}
          onClick={() =>
            send({
              command: 'memories',
              query: view.query,
              offset: Math.max(0, view.offset - limit)
            })
          }
        >
          <Icon name="back" />
          {t('previousPage')}
        </button>
        <button
          className="btn btn-ghost btn-sm"
          type="button"
          disabled={view.offset + view.memories.length >= view.total}
          onClick={() =>
            send({
              command: 'memories',
              query: view.query,
              offset: view.offset + limit
            })
          }
        >
          {t('nextPage')}
          <Icon name="arrow" />
        </button>
      </nav>
    </div>
  );
}

function MemoryDiagnosticRows({ diagnostics }: { diagnostics: MemoryDiagnostics }): JSX.Element {
  const { t, locale } = useI18n();
  const error = diagnostics.last_capture_error;
  return (
    <section aria-label={t('memoryDiagnostics')} className="wb-memory-diagnostics">
      <dl className="wb-secondary-counts">
        <div>
          <dt>{t('memoryStoredCount')}</dt>
          <dd>{diagnostics.stored_count}</dd>
        </div>
        <div>
          <dt>{t('memoryMatchedCount')}</dt>
          <dd>{diagnostics.matched_count}</dd>
        </div>
        {diagnostics.injected_count !== undefined && (
          <div>
            <dt>{t('memoryInjectedCount')}</dt>
            <dd>{diagnostics.injected_count}</dd>
          </div>
        )}
      </dl>
      {error && (
        <details className="wb-secondary-disclosure wb-memory-capture-error" open>
          <summary>
            <Icon name="alert" />
            {t('memoryLastCaptureError')}
          </summary>
          <div className="wb-secondary-disclosure-body" role="status">
            <p className="wb-secondary-prose">{error.message}</p>
            <p className="wb-secondary-meta">
              {t('memoryErrorRun', { run: error.run_id })}
              {error.slot !== undefined ? ` · ${t('memoryErrorSlot', { slot: error.slot })}` : ''} ·{' '}
              <code>{error.code}</code> ·{' '}
              <time dateTime={error.created_at}>{formatTime(error.created_at, locale)}</time>
            </p>
            <p className="wb-secondary-meta">{t('memoryCaptureErrorHelp')}</p>
          </div>
        </details>
      )}
    </section>
  );
}

function ReadOnlyBadge(): JSX.Element {
  const { t } = useI18n();
  return (
    <span className="wb-secondary-readonly" title={t('memoryReadOnly')} aria-label={t('memoryReadOnly')}>
      <Icon name="lock" />
    </span>
  );
}

function Cues({ memory }: { memory: AssociativeMemory }): JSX.Element | null {
  const { t } = useI18n();
  if (!memory.cue.length) return null;
  return (
    <div className="wb-memory-cues" aria-label={t('memoryCues')}>
      {memory.cue.map((cue, index) => (
        <span
          key={`${cue}:${index}`}
          className={`badge badge-sm${memory.matched_cues.includes(cue) ? ' is-matched' : ''}`}
          title={memory.matched_cues.includes(cue) ? t('matchedCues') : undefined}
        >
          {cue}
        </span>
      ))}
    </div>
  );
}

function MemoryUse({ memory }: { memory: AssociativeMemory }): JSX.Element {
  const { t, locale } = useI18n();
  const ease = memory.strength >= 0.67 ? 'recallEasy' : memory.strength >= 0.33 ? 'recallModerate' : 'recallFaint';
  return (
    <dl className="wb-memory-use">
      <div>
        <dt>{t('recallEase')}</dt>
        <dd title={t('recallHelp')}>{t(ease)}</dd>
      </div>
      <div>
        <dt>{t('lastMemoryUse')}</dt>
        <dd>
          {memory.last_reinforced_at ? (
            <time dateTime={memory.last_reinforced_at}>{formatTime(memory.last_reinforced_at, locale)}</time>
          ) : (
            t('memoryNeverUsed')
          )}
        </dd>
      </div>
    </dl>
  );
}

function MemoryDetail({ memory, send }: { memory: AssociativeMemory; send: Send }): JSX.Element {
  const { t, locale } = useI18n();
  return (
    <div className="wb-secondary-reading">
      <article className="wb-secondary-document">
        <div className="wb-secondary-meta">
          <span className="badge badge-outline badge-sm">
            {t(memory.state === 'active' ? 'memoryActive' : 'memorySuperseded')}
          </span>
          <span className="wb-mono">{memory.id}</span>
          <ReadOnlyBadge />
        </div>
        <p className="wb-memory-note">{memory.note}</p>
        <Cues memory={memory} />
        <section className="wb-memory-origin">
          <h2>{t('originalSource')}</h2>
          <h3>{memory.source.title || memory.source.run_id}</h3>
          <p className="wb-secondary-meta wb-mono">
            {memory.source.run_id}
            {memory.source.item_id !== null ? ` · ${memory.source.item_id}` : ''}
            {memory.source.archive_id ? ` · ${memory.source.archive_id}` : ''}
          </p>
          {memory.source_available ? (
            <button
              className="btn btn-sm"
              type="button"
              onClick={() =>
                send({
                  command: 'openMemorySource',
                  memoryId: memory.id,
                  source_db: memory.source_db
                })
              }
            >
              {t('openOriginalSource')}
              <Icon name="arrow" />
            </button>
          ) : (
            <p className="wb-secondary-meta">{t('sourceUnavailable')}</p>
          )}
          {memory.source_record && (
            <details className="wb-secondary-disclosure wb-memory-source-preview" open>
              <summary>
                {t('content')}
                <Icon name="chevron" />
              </summary>
              <div className="wb-secondary-disclosure-body">
                {memory.source_record.kind === 'item' ? (
                  <>
                    <h3>{memory.source_record.item.title}</h3>
                    <p className="wb-secondary-prose">
                      {memory.source_record.item.body || memory.source_record.item.raw_text || t('notRecorded')}
                    </p>
                    <details className="wb-secondary-inspect">
                      <summary>{t('wbInspect')}</summary>
                      <ValueTree value={memory.source_record.item} />
                    </details>
                  </>
                ) : (
                  <>
                    <h3>{memory.source_record.run.slug || memory.source_record.run.id}</h3>
                    <h4>{t('request')}</h4>
                    <p className="wb-secondary-prose">{memory.source_record.run.request_summary || t('notRecorded')}</p>
                    <h4>{t('result')}</h4>
                    <p className="wb-secondary-prose">{memory.source_record.run.result_summary || t('notRecorded')}</p>
                    <details className="wb-secondary-inspect">
                      <summary>{t('wbInspect')}</summary>
                      <ValueTree value={memory.source_record.run} />
                    </details>
                  </>
                )}
              </div>
            </details>
          )}
        </section>
        <details className="wb-secondary-inspect">
          <summary>{t('wbAdditionalFields')}</summary>
          <ValueTree
            value={{
              id: memory.id,
              revision: memory.revision,
              strength: memory.strength,
              half_life_days: memory.half_life_days,
              source_available: memory.source_available,
              last_reinforced_at: memory.last_reinforced_at
            }}
          />
        </details>
      </article>
      <aside className="wb-secondary-properties">
        <h2>{t('wbProperties')}</h2>
        <MemoryUse memory={memory} />
        <dl className="wb-secondary-facts">
          <div>
            <dt>{t('created')}</dt>
            <dd>
              <time dateTime={memory.created_at}>{formatTime(memory.created_at, locale)}</time>
            </dd>
          </div>
          <div>
            <dt>{t('memoryContentUpdated')}</dt>
            <dd>
              <time dateTime={memory.updated_at}>{formatTime(memory.updated_at, locale)}</time>
            </dd>
          </div>
          <div>
            <dt>{t('matchedCues')}</dt>
            <dd>{memory.matched_cues.join(', ') || t('none')}</dd>
          </div>
          <div>
            <dt>{t('wbRevision')}</dt>
            <dd>{memory.revision}</dd>
          </div>
          <div>
            <dt>{t('wbStrength')}</dt>
            <dd title={String(memory.strength)}>
              {new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }).format(memory.strength)}
            </dd>
          </div>
          <div>
            <dt>{t('wbHalfLife')}</dt>
            <dd>{memory.half_life_days}</dd>
          </div>
          <div>
            <dt>{t('source')}</dt>
            <dd>{t(memory.source.kind === 'item' ? 'records' : 'run')}</dd>
          </div>
          {memory.source_db && (
            <div>
              <dt>{t('wbSourceDatabase')}</dt>
              <dd className="wb-mono">{memory.source_db}</dd>
            </div>
          )}
        </dl>
      </aside>
    </div>
  );
}

function MemoryRunSource({ view }: { view: Extract<MemoryScreen, { type: 'memorySource' }> }): JSX.Element {
  const { t, status } = useI18n();
  const properties = [
    [t('run'), view.run.id],
    [t('wbOwner'), view.run.session_id],
    [t('status'), status(view.run.status)],
    [t('wbWorkType'), view.run.work_type],
    [t('wbWorkflowMode'), view.run.workflow_mode],
    [t('wbRecordMode'), view.run.record_mode],
    [t('records'), view.run.record_count],
    [t('wbSource'), view.source_db ?? view.run.source_db]
  ];
  return (
    <div className="wb-secondary-reading">
      <article className="wb-secondary-document">
        <div className="wb-secondary-meta">
          <span className="wb-mono">{view.run.id}</span>
          <ReadOnlyBadge />
        </div>
        <h2>{view.run.slug || view.run.id}</h2>
        <h3>{t('request')}</h3>
        <p className="wb-secondary-prose">{view.run.request_summary || t('notRecorded')}</p>
        <h3>{t('result')}</h3>
        <p className="wb-secondary-prose">{view.run.result_summary || t('notRecorded')}</p>
      </article>
      <aside className="wb-secondary-properties">
        <h2>{t('wbProperties')}</h2>
        <dl className="wb-secondary-facts">
          {properties.map(
            ([key, value]) =>
              value !== undefined &&
              value !== null &&
              value !== '' && (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              )
          )}
        </dl>
        <details className="wb-secondary-inspect">
          <summary>{t('wbInspect')}</summary>
          <ValueTree value={view.run} />
        </details>
      </aside>
    </div>
  );
}

function formatTime(value: string, locale: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale);
}
