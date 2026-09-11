import type { SupportedLocale } from '../i18n';

export type DisplayLayout = 'auto' | 'small' | 'medium' | 'large';

export type TaplJsonValue = string | number | boolean | null | TaplJsonValue[] | {
  [key: string]: TaplJsonValue;
};

export interface TaplWorkflowRun {
  id?: string;
  slug?: string;
  status?: string;
  request_summary?: string;
  result_summary?: string;
  work_type?: string;
  workflow_mode?: string;
  record_mode?: string;
}

export interface TaplStatus {
  active_run: TaplWorkflowRun | null;
  task_counts: Record<string, number>;
  incomplete_tasks: number;
  plans: TaplItem[];
  tasks: TaplItem[];
  findings: TaplItem[];
  active_batches?: TaplExecutionBatch[];
  active_executions?: TaplExecution[];
  recent_events: TaplEvent[];
  schema: Record<string, string>;
  viewer_capabilities?: HostCapabilities;
  counts?: { plans?: number; tasks?: number; findings?: number; archives?: number; active_batches?: number; active_executions?: number };
}

export interface TaplExecution {
  execution_id: string;
  task_id?: string;
  title?: string;
  execution_state?: string;
  batch_id?: string;
  batch_state?: string;
  execution_mode?: string;
  executor_kind?: string;
  parallel_group?: string;
  owned_paths?: string[];
  executor_ref?: string;
  model?: string;
  reasoning_effort?: string;
  started_at?: string;
  finished_at?: string;
}

export interface TaplExecutionBatch {
  batch: {
    batch_id?: string;
    id?: string;
    state?: string;
    parallel_group?: string;
    failure_policy?: string;
  };
  executions: TaplExecution[];
}

export interface TaplItem {
  stable_id: string;
  kind: string;
  title: string;
  body?: string;
  status?: string;
  source?: string;
  updated_at?: string;
  custom_fields?: Record<string, TaplJsonValue>;
  execution_mode?: string;
  executor_kind?: string;
  parallel_group?: string;
  owned_paths?: string[];
  depends_on?: string[];
  active_execution?: TaplExecution;
}

export interface TaplArchive {
  id: string;
  slug: string;
  summary: string;
  created_at: string;
  request_summary?: string;
  run_slug?: string;
  run_created_at?: string;
  run_updated_at?: string;
  run_archived_at?: string;
}

export interface TaplEvent {
  event_type: string;
  tool_name?: string;
  mode: string;
  message?: string;
  created_at: string;
}

export interface TaplSearchResult {
  id?: number;
  stable_id: string;
  kind: string;
  title: string;
  status?: string;
  source?: string;
  score?: number;
  snippet?: string;
  search_source: string;
}

export interface TaplSearchPayload {
  mode: string;
  query: string;
  results: TaplSearchResult[];
}

export interface TaplArchiveDetail {
  archive: TaplArchive;
  items: TaplItem[];
  events: TaplEvent[];
}

export interface TaplItemDetail extends TaplItem {
  id: number;
  raw_text?: string;
  archived?: number;
  run_slug?: string;
  run_status?: string;
  request_summary?: string;
  archive_id?: string;
  archive_slug?: string;
  archive_created_at?: string;
  spec_id?: string;
  goal?: string;
  action?: string;
  verification?: string;
  result?: string;
  blocker?: string;
  next_action?: string;
  related_ids?: string;
  impact?: string;
}

export interface AssociativeMemory {
  id: string;
  note: string;
  cue: string[];
  state: 'active' | 'superseded' | 'deleted';
  revision: number;
  source: { run_id: string; item_id: number | null; archive_id: string | null; title: string; kind: 'item' | 'run' };
  created_at: string;
  updated_at: string;
  last_reinforced_at: string | null;
  half_life_days: number;
  strength: number;
  matched_cues: string[];
  source_available: boolean;
  source_record?: { kind: 'item'; item: TaplItemDetail } | { kind: 'run'; run: TaplWorkflowRun };
}

export interface HostCapabilities {
  associativeMemory: boolean;
}

export type WebviewView =
  | { type: 'memories'; query: string; offset: number; total: number; limit: number; memories: AssociativeMemory[] }
  | { type: 'memory'; memoryId: string; memory: AssociativeMemory | null }
  | { type: 'memorySource'; memoryId: string; run: TaplWorkflowRun }
  | { type: 'workspace'; workspace: string; message?: string }
  | { type: 'overview'; status: TaplStatus; archives: TaplArchive[]; searchQuery: string; workspace?: string }
  | { type: 'archive'; archive: TaplArchive; detail?: TaplArchiveDetail }
  | { type: 'archiveEvents'; archive: TaplArchive; detail?: TaplArchiveDetail }
  | { type: 'debug'; status: TaplStatus }
  | { type: 'search'; search: TaplSearchPayload }
  | { type: 'searchItem'; result: TaplSearchResult; detail?: TaplItemDetail }
  | { type: 'error'; message: string };

export type HostMessage =
  | { type: 'hydrate'; view: WebviewView; locale: SupportedLocale; layout: DisplayLayout; workspace?: string; capabilities?: HostCapabilities }
  | { type: 'view:update'; view: WebviewView; locale: SupportedLocale; layout: DisplayLayout; workspace?: string; capabilities?: HostCapabilities }
  | { type: 'error'; message: string; locale: SupportedLocale; layout: DisplayLayout };

/** Lightweight standalone-viewer response used to detect workspace changes. */
export interface RevisionMessage {
  type: 'revision';
  revision: string;
  workspace: string;
  workspaceValid: boolean;
  message: string;
}

export type WebviewCommand =
  | { command: 'memories'; query?: string; offset?: number }
  | { command: 'openMemory'; memoryId: string }
  | { command: 'openMemorySource'; memoryId: string }
  | { command: 'ready' }
  | { command: 'chooseWorkspace' }
  | { command: 'selectWorkspace'; workspace: string }
  | { command: 'refresh' }
  | { command: 'back' }
  | { command: 'debug' }
  | { command: 'archiveEvents'; archiveId: string }
  | { command: 'openArchive'; archiveId: string }
  | { command: 'search'; query: string }
  | { command: 'openSearchResult'; itemId: number };

/** Browser-only request; the VS Code host deliberately never receives this command. */
export type BrowserApiCommand = WebviewCommand | { command: 'revision'; workspace?: string };
