import { useEffect, useState, type ReactNode } from 'react';
import type { TranslationKey } from '../../i18n';
import { useI18n } from '../i18n';
import { formatExecutionTiming, isRunningExecutionTiming } from '../executionTiming';
import type { TaplItem, TaplItemDetail, TaplJsonValue, TaplRunSnapshot, WebviewCommand, WebviewView } from '../types';
import { Icon } from './Icon';
import { StatusMark } from './components';
import {
  formatTimestamp,
  isRecorded,
  JsonRows,
  JsonValue,
  PropertyRows,
  ReadableContent,
  ReadingDisclosure,
  ReadingSection,
  type PropertyField
} from './ReadingPrimitives';

type RecordView = Extract<WebviewView, { type: 'searchItem' }>;
type Send = (message: WebviewCommand) => void;

function contextFor(view: RecordView): TaplRunSnapshot | undefined {
  const context = view.context;
  if (!context) return undefined;
  const source = view.detail?.source_db ?? view.result.source_db;
  if ((source ?? '') !== (context.run.source_db ?? '')) return undefined;
  const runId = view.detail?.run_id ?? view.result.run_id;
  if (runId) return context.run.id === runId ? context : undefined;
  const id = view.detail?.id ?? view.result.id;
  const stableId = view.detail?.stable_id ?? view.result.stable_id;
  return [...context.plans, ...context.tasks, ...context.findings].some(
    (item) => item.id === id && item.stable_id === stableId
  )
    ? context
    : undefined;
}

function parseRelatedData(value: string): TaplJsonValue {
  try {
    return JSON.parse(value) as TaplJsonValue;
  } catch {
    return value;
  }
}

function referenceIds(item: Partial<TaplItemDetail>): string[] {
  const related = item.related_ids;
  let extra: string[] = [];
  if (related) {
    try {
      const parsed: unknown = JSON.parse(related);
      extra = Array.isArray(parsed)
        ? parsed.filter((value): value is string => typeof value === 'string')
        : related.split(/[\s,;]+/);
    } catch {
      extra = related.split(/[\s,;]+/);
    }
  }
  return [
    ...new Set([item.spec_id, ...(item.depends_on ?? []), ...extra].filter((value): value is string => !!value?.trim()))
  ];
}

function contextItems(context: TaplRunSnapshot | undefined): TaplItem[] {
  if (!context) return [];
  return [...context.plans, ...context.tasks, ...context.findings].filter(
    (item) =>
      (!item.run_id || item.run_id === context.run.id) && (!item.source_db || item.source_db === context.run.source_db)
  );
}

function RecordLink({
  item,
  sourceDb,
  send,
  children
}: {
  item: TaplItem;
  sourceDb?: string;
  send: Send;
  children: ReactNode;
}): JSX.Element {
  if (typeof item.id !== 'number') return <span>{children}</span>;
  return (
    <button
      type="button"
      className="wb-reading-link"
      data-wb-focus={`related:${item.id}`}
      onClick={() =>
        send({ command: 'openSearchResult', itemId: item.id as number, source_db: item.source_db ?? sourceDb })
      }
    >
      {children}
    </button>
  );
}

function ExecutionFields({ item }: { item: TaplItemDetail }): JSX.Element {
  const { locale, t } = useI18n();
  const [now, setNow] = useState(Date.now);
  const running = isRunningExecutionTiming(item.execution_timing, item.status);
  useEffect(() => {
    if (!running) return;
    setNow(Date.now());
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [running]);
  const timing = formatExecutionTiming(item.execution_timing, item.status, locale, now);
  const execution = item.active_execution;
  const fields: PropertyField[] = [
    [t('spec'), item.spec_id],
    [t('executionMode'), item.execution_mode],
    [t('executor'), item.executor_kind],
    [t('parallelGroup'), item.parallel_group],
    [t('ownedPaths'), item.owned_paths ? <JsonValue value={item.owned_paths} /> : undefined],
    [t('dependencies'), item.depends_on ? <JsonValue value={item.depends_on} /> : undefined],
    [
      t(timing?.running ? 'elapsedTime' : 'duration'),
      item.kind === 'task' ? (timing?.duration ?? t('notMeasured')) : undefined
    ],
    [t('wbStartedAt'), item.execution_timing?.started_at],
    [t('wbFinishedAt'), item.execution_timing ? <JsonValue value={item.execution_timing.finished_at} /> : undefined],
    [
      t('wbRunningSince'),
      item.execution_timing ? <JsonValue value={item.execution_timing.running_since} /> : undefined
    ],
    [t('wbSnapshotAt'), item.execution_timing?.as_of],
    [t('wbElapsedSeconds'), item.execution_timing?.elapsed_seconds],
    [t('executionId'), execution?.execution_id],
    [t('executionState'), execution?.execution_state],
    [t('task'), execution?.task_id],
    [t('summary'), execution?.title],
    [t('batch'), execution?.batch_id],
    [t('wbBatchState'), execution?.batch_state],
    [t('executionMode'), execution?.execution_mode],
    [t('executor'), execution?.executor_kind],
    [t('parallelGroup'), execution?.parallel_group],
    [t('ownedPaths'), execution?.owned_paths ? <JsonValue value={execution.owned_paths} /> : undefined],
    [t('wbExecutionRef'), execution?.executor_ref],
    [t('wbModel'), execution?.model],
    [t('wbReasoningEffort'), execution?.reasoning_effort],
    [t('wbStartedAt'), execution?.started_at],
    [t('wbFinishedAt'), execution?.finished_at]
  ];
  return <PropertyRows fields={fields} empty={t('noExecutionMetadata')} />;
}

const taskNarrative: Array<[keyof TaplItemDetail, TranslationKey]> = [
  ['goal', 'goal'],
  ['action', 'action'],
  ['result', 'result'],
  ['verification', 'verification'],
  ['blocker', 'blocker'],
  ['next_action', 'nextAction']
];
const planNarrative: Array<[keyof TaplItemDetail, TranslationKey]> = [
  ['summary', 'summary'],
  ['objective', 'wbObjective'],
  ['requirements_trace', 'wbRequirements'],
  ['selected_approach', 'wbApproach'],
  ['affected_files', 'wbAffectedFiles'],
  ['execution_order', 'wbExecutionOrder'],
  ['risks', 'wbRisks'],
  ['validation', 'wbValidation'],
  ['approval_needs', 'approvalNeeds'],
  ['notes', 'wbNotes']
];
const planBodyLabels = [
  ['summary', 'Summary'],
  ['objective', 'Objective'],
  ['requirements_trace', 'Requirements trace'],
  ['selected_approach', 'Selected approach'],
  ['affected_files', 'Affected files'],
  ['execution_order', 'Execution order'],
  ['risks', 'Risks'],
  ['validation', 'Validation'],
  ['approval_needs', 'Approval needs'],
  ['notes', 'Notes']
] as const;
const taskBodyLabels = [
  ['goal', 'Goal'],
  ['action', 'Action'],
  ['verification', 'Verification'],
  ['result', 'Result'],
  ['blocker', 'Blocker'],
  ['next_action', 'Next action']
] as const;

export function RecordDetail({ view, send, back }: { view: RecordView; send: Send; back?: () => void }): JSX.Element {
  const { t, kind, status } = useI18n();
  const { result, detail } = view;
  const item = detail ?? result;
  const title = detail?.title ?? result.title;
  const stableId = detail?.stable_id ?? result.stable_id;
  const kindValue = detail?.kind ?? result.kind;
  const statusValue = detail?.status ?? result.status;
  const context = contextFor(view);
  const items = contextItems(context);
  const sourceDb = item.source_db ?? result.source_db;
  const originalContent = detail?.body || detail?.raw_text || result.snippet || '';
  const narrativeFields: Array<[keyof TaplItemDetail, TranslationKey]> =
    kindValue === 'plan' ? planNarrative : kindValue === 'finding' ? [['impact', 'impact']] : taskNarrative;
  const canonicalFields = kindValue === 'plan' ? planBodyLabels : taskBodyLabels;
  const canonicalBody =
    detail && kindValue !== 'finding'
      ? canonicalFields
          .filter(([key]) => typeof detail[key] === 'string' && detail[key]?.trim())
          .map(([key, label]) => `### ${label}\n${detail[key]?.trim()}`)
          .join('\n\n')
      : '';
  const content = canonicalBody && detail?.body?.trim() === canonicalBody ? '' : originalContent;
  const runId = detail?.run_id ?? result.run_id ?? context?.run.id;
  const runTitle =
    context?.run.request_summary ||
    (detail?.run_slug !== 'active' ? detail?.run_slug : undefined) ||
    (context?.run.slug !== 'active' ? context?.run.slug : undefined);
  const parent = detail?.spec_id ? items.find((candidate) => candidate.stable_id === detail.spec_id) : undefined;
  const references = referenceIds(detail ?? {});
  const related = items.filter(
    (candidate) =>
      candidate.stable_id !== stableId &&
      (references.includes(candidate.stable_id) ||
        referenceIds(candidate as Partial<TaplItemDetail>).includes(stableId))
  );
  const uniqueRelated = related.filter(
    (candidate, index) => related.findIndex((other) => other.stable_id === candidate.stable_id) === index
  );
  const owner = [detail?.custom_fields?.owner, detail?.custom_fields?.assignee].find(
    (value): value is string => typeof value === 'string' && !!value.trim()
  );
  const runStatus = detail?.run_status || context?.run.status;
  const properties: PropertyField[] = [
    [
      t('wbRun'),
      runId ? (
        <>
          <button
            type="button"
            className="wb-reading-link"
            data-wb-focus="record-run"
            onClick={() => send({ command: 'openRun', runId, source_db: sourceDb })}
          >
            {runId}
          </button>
          {runTitle && <span className="wb-property-caption" title={runTitle}>{runTitle}</span>}
        </>
      ) : (
        runTitle
      )
    ],
    [t('wbRunStatus'), runStatus ? status(runStatus) : undefined],
    [t('source'), detail?.source || result.source],
    [t('wbSourceDatabase'), sourceDb],
    [t('created'), formatTimestamp(detail?.created_at)],
    [t('wbOwner'), owner],
    [t('wbKind'), kind(kindValue)],
    [
      t('wbParentPlan'),
      parent ? (
        <RecordLink item={parent} sourceDb={sourceDb} send={send}>
          {parent.stable_id}
        </RecordLink>
      ) : (
        detail?.spec_id
      )
    ],
    [t('archive'), detail?.archive_slug]
  ];
  // Keep raw identities, fallback content, and any fields supplied by newer hosts inspectable.
  const displayed = new Set([
    'id',
    'stable_id',
    'kind',
    'title',
    'body',
    'status',
    'source',
    'updated_at',
    'custom_fields',
    'execution_mode',
    'executor_kind',
    'parallel_group',
    'owned_paths',
    'depends_on',
    'run_slug',
    'run_status',
    'request_summary',
    'archive_slug',
    'archive_created_at',
    'spec_id',
    'goal',
    'action',
    'verification',
    'result',
    'blocker',
    'next_action',
    'related_ids',
    'impact'
  ]);
  const additional: Record<string, TaplJsonValue> = Object.create(null);
  for (const [key, value] of Object.entries(detail ?? result)) {
    if (!displayed.has(key) && !narrativeFields.some(([field]) => field === key) && value !== undefined)
      additional[key] = value as TaplJsonValue;
  }
  additional.id = item.id ?? null;
  additional.stable_id = stableId;
  additional.search_source = result.search_source;
  if (result.score !== undefined) additional.score = result.score;
  if (result.snippet) additional.snippet = result.snippet;
  const hasNarrative = narrativeFields.some(([field]) => isRecorded(detail?.[field]));
  return (
    <article className="wb-record-page">
      <header className="wb-record-hero">
        <div className="wb-record-heading-row">
          <div className="wb-record-heading-copy">
            <div className="wb-record-context">
              <span className="wb-reading-kind">{kind(kindValue)}</span>
              <span className="wb-reading-id wb-mono">{stableId}</span>
              <StatusMark value={statusValue} />
            </div>
            <h1 tabIndex={-1} data-wb-page-heading>
              {title}
            </h1>
            {(owner || detail?.updated_at) && (
              <div className="wb-record-meta">
                {owner && (
                  <span>
                    {t('wbOwner')}: {owner}
                  </span>
                )}
                {detail?.updated_at && (
                  <span>
                    {t('updated')}: <time dateTime={detail.updated_at}>{formatTimestamp(detail.updated_at)}</time>
                  </span>
                )}
              </div>
            )}
          </div>
          {back && (
            <button
              className="btn btn-sm wb-back"
              type="button"
              data-wb-focus="back"
              onClick={back}
              title={t('wbBack')}
            >
              <Icon name="back" />
              {t('wbBack')}
            </button>
          )}
        </div>
      </header>
      <div className="wb-reading-grid">
        <div className="wb-reading-body">
          {kindValue === 'finding' && content && (
            <ReadingSection title={t('finding')}>
              <ReadableContent content={content} />
            </ReadingSection>
          )}
          {narrativeFields.map(([field, label]) =>
            isRecorded(detail?.[field]) ? (
              <ReadingSection key={field} title={t(label)}>
                <ReadableContent content={detail?.[field]} />
              </ReadingSection>
            ) : null
          )}
          {kindValue !== 'finding' && content && (
            <ReadingSection title={t('content')}>
              <ReadableContent content={content} />
            </ReadingSection>
          )}
          {!content && !hasNarrative && (
            <p className="wb-reading-empty">{t(detail ? 'notRecorded' : 'detailUnavailable')}</p>
          )}
          {!!detail?.depends_on?.length && (
            <ReadingSection title={t('dependencies')}>
              <ul className="wb-dependency-list">
                {detail.depends_on.map((id, index) => {
                  const dependency = items.find((candidate) => candidate.stable_id === id);
                  return (
                    <li key={`${id}-${index}`}>
                      {dependency ? (
                        <RecordLink item={dependency} sourceDb={sourceDb} send={send}>
                          {id}
                        </RecordLink>
                      ) : (
                        <span className="wb-mono">{id}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </ReadingSection>
          )}
          {!!uniqueRelated.length && (
            <section className="wb-related-records">
              <h2>{t('wbRelatedRecords')}</h2>
              {uniqueRelated.map((record) => {
                const children = (
                  <>
                    <span className="wb-reading-kind">{kind(record.kind)}</span>
                    <span className="wb-related-copy">
                      <span className="wb-mono">{record.stable_id}</span>
                      <strong>{record.title}</strong>
                    </span>
                    <StatusMark value={record.status} />
                    {typeof record.id === 'number' && <Icon name="arrow" />}
                  </>
                );
                return typeof record.id === 'number' ? (
                  <button
                    key={record.stable_id}
                    className="wb-related-record"
                    type="button"
                    data-wb-focus={`related-row:${record.id}`}
                    onClick={() =>
                      send({
                        command: 'openSearchResult',
                        itemId: record.id as number,
                        source_db: record.source_db ?? sourceDb
                      })
                    }
                  >
                    {children}
                  </button>
                ) : (
                  <div key={record.stable_id} className="wb-related-record">
                    {children}
                  </div>
                );
              })}
            </section>
          )}
          <div className="wb-record-disclosures">
            <ReadingDisclosure title={t('wbAdditionalFields')}>
              <JsonRows fields={additional} />
            </ReadingDisclosure>
            {!!detail?.custom_fields && Object.keys(detail.custom_fields).length > 0 && (
              <ReadingDisclosure title={t('customFields')}>
                <JsonRows fields={detail.custom_fields} />
              </ReadingDisclosure>
            )}
            {detail &&
              (detail.kind === 'task' ||
                [
                  'spec_id',
                  'execution_mode',
                  'executor_kind',
                  'parallel_group',
                  'owned_paths',
                  'depends_on',
                  'active_execution',
                  'execution_timing'
                ].some((key) => isRecorded((detail as unknown as Record<string, unknown>)[key]))) && (
                <ReadingDisclosure title={t('execution')}>
                  <ExecutionFields item={detail} />
                </ReadingDisclosure>
              )}
            {detail &&
              [
                detail.related_ids,
                detail.impact,
                detail.request_summary,
                detail.updated_at,
                detail.archive_created_at
              ].some(isRecorded) && (
                <ReadingDisclosure title={t('audit')}>
                  <PropertyRows
                    fields={[
                      [
                        t('relatedIds'),
                        detail.related_ids ? <JsonValue value={parseRelatedData(detail.related_ids)} /> : undefined
                      ],
                      [t('impact'), detail.impact],
                      [t('request'), detail.request_summary],
                      [t('updated'), detail.updated_at],
                      [t('archivedAt'), detail.archive_created_at]
                    ]}
                  />
                </ReadingDisclosure>
              )}
          </div>
        </div>
        <aside className="wb-record-properties">
          <h2>{t('wbProperties')}</h2>
          <PropertyRows fields={properties} />
          {detail?.archive_id && (
            <button
              type="button"
              className="wb-reading-archive"
              onClick={() =>
                send({ command: 'openArchive', archiveId: detail.archive_id as string, source_db: sourceDb })
              }
            >
              {t('openArchive')}
              <Icon name="arrow" />
            </button>
          )}
        </aside>
      </div>
    </article>
  );
}
