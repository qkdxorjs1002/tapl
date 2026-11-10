import type { TranslationKey } from '../../i18n';
import { useI18n } from '../i18n';
import type { TaplItem, TaplRunSnapshot, TaplWorkflowRun } from '../types';
import { Icon } from './Icon';
import { EmptyState, HorizontalTrack, ItemCount, PageHeading, StatusMark, TaskDuration } from './components';
import { filterTasks, itemSummary, TASK_STATUSES, taskCounts, type RunPageState } from './model';

export type OpenItem = (item: TaplItem, run?: TaplWorkflowRun) => void;
const metadataValueKeys: Record<string, TranslationKey> = {
  answer: 'wbMetadataAnswer',
  investigation: 'wbMetadataInvestigation',
  analysis: 'wbMetadataAnalysis',
  mixed: 'wbMetadataMixed',
  planned: 'wbMetadataPlanned',
  lightweight: 'wbMetadataLightweight',
  implementation: 'wbMetadataImplementation',
  planning: 'wbMetadataPlanning',
  research: 'wbMetadataResearch',
  review: 'wbMetadataReview',
  standard: 'wbMetadataStandard',
  strict: 'wbMetadataStrict',
  fast: 'wbMetadataFast',
  lean: 'wbMetadataLean',
  full: 'wbMetadataFull'
};
function RunInformation({ run }: { run: TaplWorkflowRun }): JSX.Element | null {
  const { t } = useI18n();
  const fields: Array<[keyof TaplWorkflowRun, TranslationKey, TranslationKey]> = [
    ['work_type', 'wbWorkType', 'wbWorkTypeHelp'],
    ['workflow_mode', 'wbWorkflowMode', 'wbWorkflowModeHelp'],
    ['record_mode', 'wbRecordMode', 'wbRecordModeHelp']
  ];
  const present = fields.filter(([key]) => typeof run[key] === 'string' && String(run[key]).trim());
  if (!present.length) return null;
  return (
    <section className="wb-run-information" aria-label={t('wbRunInfo')} tabIndex={0}>
      <dl className="wb-run-facts">
        {present.map(([field, label, help]) => (
          <div key={field} title={t(help)}>
            <dt>{t(label)}</dt>
            <dd>
              <strong>
                {metadataValueKeys[String(run[field])] ? t(metadataValueKeys[String(run[field])]) : String(run[field])}
              </strong>
              <p className="wb-sr-only">{t(help)}</p>
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
function owner(item: TaplItem): string | undefined {
  const value = item.custom_fields?.owner ?? item.custom_fields?.assignee ?? item.executor_kind;
  return typeof value === 'string' && value.trim() ? value : undefined;
}
function TaskFlow({ snapshot, open }: { snapshot: TaplRunSnapshot; open: OpenItem }): JSX.Element | null {
  const { t, status } = useI18n();
  if (!snapshot.tasks.length) return null;
  const states: string[] = [
    ...TASK_STATUSES.filter((value) => value !== 'Skipped' || snapshot.tasks.some((task) => task.status === value)),
    ...new Set(
      snapshot.tasks
        .map((task) => task.status)
        .filter((value): value is string => !!value && !(TASK_STATUSES as readonly string[]).includes(value))
    )
  ];
  if (snapshot.tasks.some((task) => !task.status)) states.push('');
  const ordered = [...snapshot.tasks].sort((a, b) =>
    a.stable_id.localeCompare(b.stable_id, undefined, { numeric: true })
  );
  return (
    <section className="wb-flow-section">
      <div className="wb-section-title">
        <h2>{t('wbFlow')}</h2>
      </div>
      <HorizontalTrack name="flow" label={t('wbFlow')} className="wb-flow-board">
        {states.map((value) => {
          const tasks = ordered.filter((item) => (item.status ?? '') === value);
          return (
            <section className="wb-flow-lane" key={value} aria-label={status(value) || t('status')}>
              <header className="wb-flow-heading">
                <h3>{value ? <StatusMark value={value} /> : t('status')}</h3>
                <span>
                  <ItemCount count={tasks.length} />
                </span>
              </header>
              <ul>
                {tasks.map((item) => (
                  <li key={item.id ?? item.stable_id}>
                    <button
                      type="button"
                      className="card wb-flow-task"
                      data-status={item.status}
                      data-wb-focus={`flow:${item.id ?? item.stable_id}`}
                      onClick={() => open(item, snapshot.run)}
                      disabled={item.id == null}
                      title={item.id == null ? t('wbRecordUnavailable') : undefined}
                    >
                      <span className="wb-mono wb-flow-id">{item.stable_id}</span>
                      <strong>{item.title}</strong>
                      <span className="wb-flow-footer">
                        {owner(item) && <span>{owner(item)}</span>}
                        {!!item.depends_on?.length && (
                          <span>
                            {t('wbPrerequisites')} <ItemCount count={item.depends_on.length} />
                          </span>
                        )}
                        <TaskDuration item={item} />
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
              {!tasks.length && <p className="wb-flow-empty">{t('wbEmptyLane')}</p>}
            </section>
          );
        })}
      </HorizontalTrack>
    </section>
  );
}
export function CurrentRun({
  snapshot,
  title,
  open,
  back
}: {
  snapshot?: TaplRunSnapshot;
  title: string;
  open: OpenItem;
  back?: () => void;
}): JSX.Element {
  const { t } = useI18n();
  if (!snapshot)
    return (
      <>
        <PageHeading title={t('wbCurrent')} back={back} />
        <EmptyState title={t('wbNoRun')} help={t('wbNoRunHelp')} />
      </>
    );
  const blocked = snapshot.tasks.find((item) => item.status === 'Blocked');
  return (
    <>
      <PageHeading title={title} back={back} />
      <div className="wb-current-overview">
        <RunInformation run={snapshot.run} />
        <section className="wb-plan-section">
          <div className="wb-section-title">
            <h2>PLAN</h2>
            <span>
              <ItemCount count={snapshot.plans.length} />
            </span>
          </div>
          {snapshot.plans.length ? (
            <HorizontalTrack
              name="plans"
              label="PLAN"
              className={`wb-plan-board ${snapshot.plans.length === 1 ? 'wb-single-plan' : ''}`}
            >
              {snapshot.plans.map((plan) => (
                <button
                  type="button"
                  key={plan.id ?? plan.stable_id}
                  className="card wb-plan-summary"
                  onClick={() => open(plan, snapshot.run)}
                  data-wb-focus={`plan:${plan.id ?? plan.stable_id}`}
                  disabled={plan.id == null}
                  title={plan.id == null ? t('wbRecordUnavailable') : undefined}
                >
                  <span className="wb-plan-meta">
                    <span className="wb-mono">{plan.stable_id}</span>
                    {plan.status && (
                      <span className="badge badge-outline badge-sm">
                        <StatusMark value={plan.status} />
                      </span>
                    )}
                  </span>
                  <span className="wb-plan-heading">
                    <strong>{plan.title}</strong>
                    <Icon name="arrow" />
                  </span>
                  {itemSummary(plan) && <span className="wb-plan-goal">{itemSummary(plan)}</span>}
                </button>
              ))}
            </HorizontalTrack>
          ) : (
            <p className="wb-plan-placeholder">{t('wbNoPlans')}</p>
          )}
        </section>
        {blocked && (
          <section className="wb-blocker">
            <Icon name="alert" />
            <div>
              <h2>{t('wbBlockerTitle')}</h2>
              <p>
                {blocked.stable_id} · {blocked.title}
              </p>
              {blocked.id != null && (
                <button
                  className="btn btn-link btn-xs"
                  type="button"
                  onClick={() => open(blocked, snapshot.run)}
                  data-wb-focus="blocker"
                >
                  {t('wbBlockerLink')}
                  <Icon name="arrow" />
                </button>
              )}
            </div>
          </section>
        )}
        {snapshot.tasks.length ? (
          <TaskFlow snapshot={snapshot} open={open} />
        ) : (
          <EmptyState title={t('wbNoTasks')} help={t('wbNoTasksHelp')} />
        )}
      </div>
    </>
  );
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
