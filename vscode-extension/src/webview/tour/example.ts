import type { SupportedLocale } from '../../i18n';
import type { TaplItemDetail, TaplRunSnapshot, TaplSearchResult, WebviewView } from '../types';

const examples = {
  en: {
    run: 'Export search results',
    archivedRun: 'Set up record filters',
    plan: 'Add a CSV export',
    done: 'Choose the CSV columns',
    running: 'Generate the CSV file',
    blocked: 'Verify the exported report',
    blocker: 'The sample report is waiting for approval.',
    nextAction: 'Verify the column order once the sample report is approved.',
    record: 'Keep the active filters in exports',
    note: 'Carry active filters over to the export so the file matches the results shown in the Viewer.',
    cues: ['CSV export', 'Record filters']
  },
  ko: {
    run: '검색 결과 내보내기',
    archivedRun: '기록 필터 추가',
    plan: 'CSV 내보내기 추가',
    done: 'CSV 열 정하기',
    running: 'CSV 파일 생성',
    blocked: '내보낸 보고서 검증',
    blocker: '샘플 보고서가 승인을 기다리고 있습니다.',
    nextAction: '샘플 보고서가 승인되면 열 순서를 확인합니다.',
    record: '내보낸 결과에 현재 필터 유지',
    note: '내보낸 파일과 Viewer의 검색 결과가 일치하도록 현재 필터를 내보내기에도 적용합니다.',
    cues: ['CSV 내보내기', '기록 필터']
  }
} satisfies Record<SupportedLocale, Record<string, string | string[]>>;

const source_db = 'tour-example.db';
const runId = 'tour-example-run';
const archiveId = 'tour-example-archive';
const memoryId = 'tour-example-memory';
const date = '2025-01-15T09:00:00Z';

export function tourExample(locale: SupportedLocale) {
  const example = examples[locale];
  const run = { source_db, id: runId, status: 'active', request_summary: example.run };
  const archived = { source_db, id: archiveId, status: 'archived', request_summary: example.archivedRun, writable: false };
  const plan = {
    id: 1, source_db, run_id: runId, stable_id: 'PLAN-001', kind: 'plan', title: example.plan, status: 'Finalized'
  };
  const task = { source_db, run_id: runId, spec_id: plan.stable_id, kind: 'task' };
  const blocked: TaplItemDetail = {
    ...task, id: 4, stable_id: 'TASK-003', title: example.blocked, status: 'Blocked',
    blocker: example.blocker, next_action: example.nextAction
  };
  const memorySource = { run_id: archiveId, item_id: 5, archive_id: archiveId, title: example.record, kind: 'item' as const };
  const current: TaplRunSnapshot = {
    run, plans: [plan], tasks: [
      { ...task, id: 2, stable_id: 'TASK-001', title: example.done, status: 'Completed' },
      { ...task, id: 3, stable_id: 'TASK-002', title: example.running, status: 'In Progress',
        executor_kind: 'subagent', custom_fields: { 'SubAgent Model': 'gpt-6.2-sol (high)' } },
      blocked
    ],
    findings: [], active_batches: [], active_executions: [],
    task_counts: { Completed: 1, 'In Progress': 1, Blocked: 1 }, readonly: true,
    references: [
      { source_db, run_id: archiveId, kind: 'memory', stage: 'used', target_type: 'memory', memory_id: memoryId,
        title: example.note, source: { ...memorySource, source_db } },
      { source_db, run_id: archiveId, kind: 'history', stage: 'opened', target_type: 'item', item_id: 5,
        title: example.record, stable_id: 'TASK-001', record_kind: 'task', source: { ...memorySource, source_db } }
    ]
  };
  const record = {
    source_db, run_id: archiveId, id: 5, stable_id: 'TASK-001', kind: 'task', title: example.record,
    status: 'Completed', snippet: example.note, search_source: 'full_text'
  } satisfies TaplSearchResult;
  const archive: TaplRunSnapshot = {
    ...current, run: archived, plans: [], tasks: [record], task_counts: { Completed: 1 }, references: []
  };
  const records: Extract<WebviewView, { type: 'records' }> = {
    type: 'records', query: 'CSV', scope: 'all', offset: 0, limit: 50, total: 1, runs: [archived], records: [record]
  };
  const memories: Extract<WebviewView, { type: 'memories' }> = {
    type: 'memories', query: '', offset: 0, total: 1, limit: 20,
    memories: [{
      source_db, id: memoryId, note: example.note, cue: example.cues,
      state: 'active', revision: 1, source: memorySource, created_at: date, updated_at: date,
      last_reinforced_at: null, half_life_days: 30, strength: 1, matched_cues: [], source_available: true
    }]
  };
  return { current, archive, records, memories, blocked };
}

export type TourExample = ReturnType<typeof tourExample>;
