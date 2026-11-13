import { useI18n } from '../i18n';
import type { TaplItem, TaplRunReference, TaplRunSnapshot, TaplWorkflowRun } from '../types';
import { EmptyState, PageHeading, StatusMark, TaskDuration } from './components';
import { filterTasks, TASK_STATUSES, taskCounts, type RunPageState } from './model';
import { RunMindmap } from './RunMindmap';

export type OpenItem = (item: TaplItem, run?: TaplWorkflowRun) => void;
function owner(item: TaplItem): string | undefined {
  const value = item.custom_fields?.owner ?? item.custom_fields?.assignee ?? item.executor_kind;
  return typeof value === 'string' && value.trim() ? value : undefined;
}
export function CurrentRun({ snapshot, open, openReference, back }: {
  snapshot?: TaplRunSnapshot;
  title: string;
  open: OpenItem;
  openReference?: (reference: TaplRunReference) => void;
  back?: () => void;
}): JSX.Element {
  const { t } = useI18n();
  if (!snapshot) return <>
    <PageHeading title={t('wbCurrent')} back={back} />
    <EmptyState title={t('wbNoRun')} help={t('wbNoRunHelp')} />
  </>;
  return <RunMindmap snapshot={snapshot} open={open} openReference={openReference} back={back} />;
}
export function TaskStatus({
  snapshot,
  prefs,
  update,
  open,
  back
}: {
  snapshot?: TaplRunSnapshot;
  prefs: RunPageState;
  update: (patch: Partial<RunPageState>) => void;
  open: OpenItem;
  back?: () => void;
}): JSX.Element {
  const { t, status } = useI18n();
  const counts = taskCounts(snapshot);
  const tasks = filterTasks(snapshot?.tasks ?? [], prefs.taskFilter, prefs.taskQuery);
  const states: string[] = [
    ...TASK_STATUSES,
    ...Object.keys(counts.counts).filter((value) => !(TASK_STATUSES as readonly string[]).includes(value))
  ];
  const showOwner = snapshot?.tasks.some((item) => owner(item));
  const showTiming = snapshot?.tasks.some((item) => item.execution_timing);
  return (
    <>
      <PageHeading title={t('wbTasks')} back={back} />
      <div className="wb-run-meter">
        <span>
          {t('wbCompleted')}{' '}
          <strong>
            {counts.completed} / {counts.total}
          </strong>
        </span>
        <progress
          className="progress progress-primary"
          value={counts.completed}
          max={counts.total || 1}
          aria-label={t('wbProgress')}
        />
        <span>
          {t('inProgress')} {counts.counts['In Progress'] ?? 0} · {t('blocked')} {counts.counts.Blocked ?? 0} ·{' '}
          {t('pending')} {counts.counts.Pending ?? 0}
        </span>
      </div>
      <div className="wb-filter-toolbar">
        <div className="wb-pill-tabs" role="group" aria-label={t('status')}>
          {['all', ...states].map((value) => (
            <button
              type="button"
              className={`btn btn-xs ${prefs.taskFilter === value ? 'btn-primary' : 'btn-ghost'}`}
              key={value}
              aria-pressed={prefs.taskFilter === value}
              onClick={() => update({ taskFilter: value })}
              data-wb-focus={`filter:${value}`}
            >
              {value === 'all' ? t('wbAll') : status(value)}
            </button>
          ))}
        </div>
        <form className="wb-task-search" onSubmit={(event) => event.preventDefault()}>
          <label>
            <span className="wb-sr-only">{t('wbTaskSearch')}</span>
            <input
              className="input input-sm"
              value={prefs.taskQuery}
              placeholder={t('wbTaskSearch')}
              onChange={(event) => update({ taskQuery: event.target.value })}
              data-wb-focus="task-query"
            />
          </label>
          <button type="submit" className="btn btn-sm">
            {t('search')}
          </button>
        </form>
      </div>
      {tasks.length ? (
        <div className="wb-task-table-wrap">
          <table className="table wb-tasks-table">
            <caption className="wb-sr-only">{t('wbTasks')}</caption>
            <thead>
              <tr>
                <th scope="col">
                  <span className="wb-sr-only">{t('status')}</span>
                </th>
                <th scope="col">{t('wbTaskColumn')}</th>
                {showOwner && <th scope="col">{t('wbOwner')}</th>}
                {showTiming && <th scope="col">{t('duration')}</th>}
                <th scope="col">{t('status')}</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((item) => (
                <tr key={item.id ?? item.stable_id}>
                  <td>
                    <StatusMark value={item.status} dotOnly />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="wb-task-title"
                      onClick={() => open(item, snapshot?.run)}
                      data-wb-focus={`task:${item.id ?? item.stable_id}`}
                      disabled={item.id == null}
                    >
                      <strong>{item.title}</strong>
                      <span className="wb-mono">{item.stable_id}</span>
                    </button>
                  </td>
                  {showOwner && <td className="wb-owner-cell">{owner(item)}</td>}
                  {showTiming && (
                    <td>
                      <TaskDuration item={item} />
                    </td>
                  )}
                  <td>
                    <StatusMark value={item.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title={t(snapshot?.tasks.length ? 'wbNoMatches' : 'wbNoTasks')}
          help={t(snapshot?.tasks.length ? 'wbNoMatchesHelp' : 'wbNoTasksHelp')}
        >
          {!!snapshot?.tasks.length && (
            <button className="btn btn-sm" type="button" onClick={() => update({ taskFilter: 'all', taskQuery: '' })}>
              {t('wbReset')}
            </button>
          )}
        </EmptyState>
      )}
    </>
  );
}
