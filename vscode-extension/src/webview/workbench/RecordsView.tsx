import { useI18n } from '../i18n';
import type { TaplSearchResult, TaplWorkflowRun, WebviewCommand, WebviewView } from '../types';
import { Icon } from './Icon';
import { EmptyState, PageHeading, StatusMark } from './components';
import { recordRunKey, runKey, runTitle, type RunPageState } from './model';

type Records = Extract<WebviewView, { type: 'records' }>;
export function RecordsView({
  view,
  prefs,
  run,
  update,
  request,
  open,
  openRun,
  back,
  loading
}: {
  view?: Records;
  prefs: RunPageState;
  run?: TaplWorkflowRun;
  update: (patch: Partial<RunPageState>) => void;
  request: (command: Extract<WebviewCommand, { command: 'records' }>) => void;
  open: (record: TaplSearchResult & { run_id: string }, run?: TaplWorkflowRun) => void;
  openRun: (run: TaplWorkflowRun) => void;
  back?: () => void;
  loading?: boolean;
}): JSX.Element {
  const { t, kind } = useI18n();
  const query = (patch: { query?: string; scope?: 'all' | 'run'; offset?: number } = {}) => {
    const scope = patch.scope ?? prefs.scope;
    request({
      command: 'records',
      query: patch.query ?? prefs.query,
      scope,
      runId: scope === 'run' ? run?.id : undefined,
      source_db: scope === 'run' ? run?.source_db : undefined,
      offset: patch.offset ?? 0,
      limit: view?.limit ?? 50
    });
  };
  const groups =
    view?.runs.map((source) => ({
      run: source,
      records: view.records.filter((record) => recordRunKey(record.source_db, record.run_id) === runKey(source))
    })) ?? [];
  const orphanRecords =
    view?.records.filter(
      (record) => !view.runs.some((source) => runKey(source) === recordRunKey(record.source_db, record.run_id))
    ) ?? [];
  const reset = () => {
    update({ query: '', scope: 'all', expanded: [] });
    query({ query: '', scope: 'all' });
  };
  const row = (record: TaplSearchResult & { run_id: string }, source?: TaplWorkflowRun, showSource = true) => (
    <button
      type="button"
      key={`${record.source_db ?? ''}:${record.id ?? record.stable_id}`}
      className="wb-search-result"
      data-wb-focus={`record:${JSON.stringify([record.source_db ?? '', record.id])}`}
      disabled={record.id == null}
      onClick={() => open(record, source)}
      title={record.id == null ? t('wbRecordUnavailable') : undefined}
    >
      <span className="wb-result-meta">
        <span className="badge badge-outline badge-sm">{kind(record.kind)}</span>
        <span className="wb-mono">{record.stable_id}</span>
        <StatusMark value={record.status} />
      </span>
      <h3>{record.title}</h3>
      {record.snippet && <p>{record.snippet}</p>}
      {showSource && (
        <span className="wb-result-tail">
          <span>{source ? runTitle(source) : record.run_id}</span>
          {record.source_db && <span className="wb-mono">{record.source_db}</span>}
        </span>
      )}
    </button>
  );
  return (
    <>
      <PageHeading title={t('wbRecords')} back={back} />
      <form
        className="wb-search-box"
        onSubmit={(event) => {
          event.preventDefault();
          update({ expanded: [] });
          query();
        }}
      >
        <label className="input input-sm">
          <Icon name="search" />
          <span className="wb-sr-only">{t('wbRecords')}</span>
          <input
            value={prefs.query}
            placeholder={t('wbSearchPlaceholder')}
            onChange={(event) => update({ query: event.target.value })}
            data-wb-focus="record-query"
          />
        </label>
        <button type="submit" className="btn btn-primary btn-sm" data-wb-focus="record-submit">
          {t('search')}
        </button>
      </form>
      <div className="wb-search-controls">
        <label className="wb-scope-controls">
          <span>{t('wbScope')}</span>
          <select
            className="select select-sm"
            value={prefs.scope}
            data-wb-focus="record-scope"
            onChange={(event) => {
              const scope = event.target.value === 'run' ? 'run' : 'all';
              update({ scope, expanded: [] });
              query({ scope });
            }}
          >
            <option value="all">{t('wbAllRecords')}</option>
            <option value="run" disabled={!run?.id}>
              {t('wbSelectedRun')}
            </option>
          </select>
        </label>
        <div className="wb-pill-tabs wb-view-controls" role="group" aria-label={t('wbResults')}>
          {(['run', 'record'] as const).map((group) => (
            <button
              className={`btn btn-sm ${prefs.group === group ? 'btn-primary' : 'btn-ghost'}`}
              type="button"
              key={group}
              aria-pressed={prefs.group === group}
              onClick={() => update({ group })}
              data-wb-focus={`record-group:${group}`}
            >
              <Icon name={group === 'run' ? 'folder' : 'file'} />
              {t(group === 'run' ? 'wbGrouped' : 'wbFlat')}
            </button>
          ))}
        </div>
      </div>
      {loading && (
        <p className="wb-loading-line" role="status">
          <span className="loading loading-spinner loading-xs" />
          {t('wbLoad')}
        </p>
      )}
      {view && (
        <>
          <p className="wb-search-context" role="status">
            {t('wbResults')} <strong>{view.total}</strong>
          </p>
          {!!view.source_errors?.length && (
            <details className="wb-source-errors">
              <summary>
                {t('wbSourceErrors')} ({view.source_errors.length})
              </summary>
              {view.source_errors.map((error) => (
                <p key={error.source_db}>
                  <code>{error.source_db}</code> · {error.error}
                </p>
              ))}
            </details>
          )}
          {view.total === 0 && groups.length === 0 ? (
            <EmptyState title={t('wbNoMatches')} help={t('wbNoMatchesHelp')} icon="search">
              <button type="button" className="btn btn-sm" onClick={reset}>
                {t('wbReset')}
              </button>
            </EmptyState>
          ) : prefs.group === 'run' ? (
            <div className="wb-grouped-results">
              {groups.map((group) => {
                const key = runKey(group.run);
                const expanded = prefs.expanded.includes(key);
                return (
                  <section className="wb-search-group" key={key}>
                    <button
                      type="button"
                      className="wb-search-group-header"
                      aria-expanded={expanded}
                      aria-controls={`wb-group-${encodeURIComponent(key)}`}
                      data-wb-focus={`group:${key}`}
                      onClick={() =>
                        update({
                          expanded: expanded
                            ? prefs.expanded.filter((value) => value !== key)
                            : [...prefs.expanded, key]
                        })
                      }
                    >
                      <span>
                        <strong>{runTitle(group.run)}</strong>
                        <span className="wb-group-source wb-mono">
                          {group.run.id}
                          {group.run.source_db && <> · {group.run.source_db}</>}
                        </span>
                      </span>
                      <span className="wb-search-group-meta">
                        {group.run.record_count != null && (
                          <span className="badge badge-outline badge-sm">
                            {t('wbRecordCount', {
                              count: group.run.record_count
                            })}
                          </span>
                        )}
                        <Icon name="chevron" />
                      </span>
                    </button>
                    {expanded && (
                      <div className="wb-search-group-body" id={`wb-group-${encodeURIComponent(key)}`}>
                        {group.records.map((record) => row(record, group.run, false))}
                        {!group.records.length && <p className="wb-no-page-records">{t('wbNoPageRecords')}</p>}
                        <button
                          type="button"
                          className="btn btn-ghost btn-sm wb-source-run-link"
                          data-wb-focus={`source-run:${key}`}
                          onClick={() => openRun(group.run)}
                        >
                          {t('wbRunPage')}
                          <Icon name="arrow" />
                        </button>
                      </div>
                    )}
                  </section>
                );
              })}
              {orphanRecords.map((record) => row(record))}
            </div>
          ) : (
            <section className="wb-flat-results">
              {view.records.map((record) =>
                row(
                  record,
                  view.runs.find((source) => runKey(source) === recordRunKey(record.source_db, record.run_id))
                )
              )}
            </section>
          )}
          <nav className="wb-pagination" aria-label={t('wbResults')}>
            <span>
              {t('wbRange', {
                start: view.total ? view.offset + 1 : 0,
                end: Math.min(view.total, view.offset + view.records.length),
                total: view.total
              })}
            </span>
            <div>
              <button
                className="btn btn-sm"
                type="button"
                disabled={loading || view.offset <= 0}
                data-wb-focus="records-previous"
                onClick={() => query({ offset: Math.max(0, view.offset - view.limit) })}
              >
                {t('previousPage')}
              </button>
              <button
                className="btn btn-sm"
                type="button"
                disabled={loading || view.offset + view.limit >= view.total}
                data-wb-focus="records-next"
                onClick={() => query({ offset: view.offset + view.limit })}
              >
                {t('nextPage')}
              </button>
            </div>
          </nav>
        </>
      )}
      {!view && !loading && <EmptyState title={t('wbNoMatches')} help={t('wbNoMatchesHelp')} />}
    </>
  );
}
