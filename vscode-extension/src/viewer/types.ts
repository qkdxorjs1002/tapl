import type { SupportedLocale } from '../i18n';

export type DisplayLayout = 'auto' | 'small' | 'medium' | 'large';

export interface ViewerPreferences {
  language: 'auto' | SupportedLocale;
  layout: DisplayLayout;
  mcp_path: string;
}

export type TaplJsonValue = string | number | boolean | null | TaplJsonValue[] | {
  [key: string]: TaplJsonValue;
};

export interface TaplWorkflowRun {
  writable?: boolean;
  source_db?: string;
  id?: string;
  session_id?: string;
  slug?: string;
  status?: string;
  request_summary?: string;
  result_summary?: string;
  work_type?: string;
  workflow_mode?: string;
  record_mode?: string;
  record_count?: number;
}

/** Agent reads observed during this RUN; Viewer navigation never records references. */
export interface TaplRunReference {
  kind: 'memory' | 'history';
  stage: 'retrieved' | 'opened';
  source_db: string;
  target_type: 'memory' | 'item' | 'run';
  run_id: string;
  title: string;
  memory_id?: string;
  item_id?: number;
  stable_id?: string;
  record_kind?: string;
  source?: { source_db: string; run_id: string; item_id?: number | null; archive_id?: string | null };
}

export interface TaplRunSnapshot {
  run: TaplWorkflowRun;
  plans: TaplItem[];
  tasks: TaplItem[];
  findings: TaplItem[];
  task_counts: Record<string, number>;
  active_batches: TaplExecutionBatch[];
  active_executions: TaplExecution[];
  readonly: boolean;
  active_runs?: TaplWorkflowRun[];
  references?: TaplRunReference[];
}

export interface TaplStatus {
  references?: TaplRunReference[];
  source_db?: string;
  active_run: TaplWorkflowRun | null;
  session_id?: string;
  active_runs?: TaplWorkflowRun[];
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
  run_id?: string;
  source_db?: string;
  id?: number;
  stable_id: string;
  kind: string;
  title: string;
  body?: string;
  status?: string;
  source?: string;
  updated_at?: string;
  custom_fields?: Record<string, TaplJsonValue>;
  summary?: string | null;
  objective?: string | null;
  selected_approach?: string | null;
  validation?: string | null;
  spec_id?: string;
  goal?: string;
  action?: string;
  verification?: string;
  execution_mode?: string;
  executor_kind?: string;
  parallel_group?: string;
  owned_paths?: string[];
  depends_on?: string[];
  active_execution?: TaplExecution;
  execution_timing?: TaplExecutionTiming | null;
}

/** Accumulated In Progress time as of the server snapshot. */
export interface TaplExecutionTiming {
  started_at: string;
  finished_at: string | null;
  elapsed_seconds: number;
  running_since: string | null;
  as_of: string;
}

export interface TaplArchive {
  run_id?: string;
  source_db?: string;
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
  source_db?: string;
  event_type: string;
  tool_name?: string;
  mode: string;
  message?: string;
  created_at: string;
}

export interface TaplSearchResult {
  run_id?: string;
  source_db?: string;
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
  created_at?: string;
  plan_id?: string | null;
  requirements_trace?: string | null;
  affected_files?: string | null;
  execution_order?: string | null;
  risks?: string | null;
  approval_needs?: string | null;
  notes?: string | null;

  id: number;
  raw_text?: string;
  archived?: number;
  run_slug?: string;
  run_status?: string;
  request_summary?: string;
  archive_id?: string;
  archive_slug?: string;
  archive_created_at?: string;
  result?: string;
  blocker?: string;
  next_action?: string;
  related_ids?: string;
  impact?: string;
}

export interface AssociativeMemory {
  source_db?: string;
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
  discardRun?: boolean;
}

export interface RunDiscardResult {
  runId: string;
  ok: boolean;
  message?: string;
}

/** Read-only counts and the most recent persisted capture failure. */
export interface MemoryDiagnostics {
  stored_count: number;
  matched_count: number;
  injected_count?: number;
  last_capture_error: { run_id: string; slot?: number; code: string; message: string; created_at: string } | null;
}

export type WebviewView =
  | { type: 'run'; snapshot: TaplRunSnapshot; workspace?: string }
  | { type: 'records'; query: string; scope: 'all' | 'run'; runId?: string; source_db?: string; offset: number; limit: number; total: number; records: Array<TaplSearchResult & { run_id: string }>; runs: TaplWorkflowRun[]; source_errors?: Array<{ source_db: string; error: string }>; context?: TaplRunSnapshot; active_runs?: TaplWorkflowRun[] }
  | { type: 'memories'; query: string; offset: number; total: number; limit: number; memories: AssociativeMemory[]; diagnostics?: MemoryDiagnostics }
  | { type: 'memory'; source_db?: string; memoryId: string; memory: AssociativeMemory | null }
  | { type: 'memorySource'; source_db?: string; memoryId: string; run: TaplWorkflowRun; context?: TaplRunSnapshot }
  | { type: 'workspace'; workspace: string; message?: string }
  | { type: 'overview'; status: TaplStatus; archives: TaplArchive[]; searchQuery: string; workspace?: string }
  | { type: 'archive'; archive: TaplArchive; detail?: TaplArchiveDetail; context?: TaplRunSnapshot }
  | { type: 'archiveEvents'; archive: TaplArchive; detail?: TaplArchiveDetail; context?: TaplRunSnapshot }
  | { type: 'debug'; status: TaplStatus }
  | { type: 'search'; search: TaplSearchPayload }
  | { type: 'searchItem'; result: TaplSearchResult; detail?: TaplItemDetail; context?: TaplRunSnapshot }
  | { type: 'error'; message: string };

export interface SettingsField {
  key: string;
  section: string;
  type: 'boolean' | 'integer' | 'number' | 'string' | 'select' | 'string-list' | 'models' | 'profiles';
  description: string;
  allowed?: string[];
  min?: number;
  max?: number;
}
export interface SettingsDocument {
  path: string;
  exists: boolean;
  revision: string;
  fields: SettingsField[];
  values: Record<string, unknown>;
  defaults: Record<string, unknown>;
  overrides: string[];
  restart_required?: string[];
}
export interface SettingsResult {
  type: 'settings:result';
  requestId: string;
  workspace: string;
  ok: boolean;
  settings?: SettingsDocument;
  message?: string;
  code?: string;
  changed?: boolean;
  action?: 'get' | 'save' | 'reset';
  locale?: SupportedLocale;
  layout?: DisplayLayout;
  preferences?: ViewerPreferences;
}

export type WorkspaceSelectionResult = { type: 'workspace:result'; ok: boolean; message?: string; workspace?: string };
export interface WorkspaceDirectoryResult {
  type: 'workspace:directory';
  requestId: string;
  ok: boolean;
  path?: string;
  parent?: string | null;
  directories?: { name: string; path: string }[];
  message?: string;
}

export type HostMessage =
  | WorkspaceDirectoryResult
  | WorkspaceSelectionResult
  | SettingsResult
  | { type: 'hydrate'; view: WebviewView; locale: SupportedLocale; layout: DisplayLayout; workspace?: string; capabilities?: HostCapabilities; preferences?: ViewerPreferences; discardResult?: RunDiscardResult }
  | { type: 'view:update'; view: WebviewView; locale: SupportedLocale; layout: DisplayLayout; workspace?: string; capabilities?: HostCapabilities; preferences?: ViewerPreferences; discardResult?: RunDiscardResult }
  | { type: 'error'; message: string; locale: SupportedLocale; layout: DisplayLayout; discardResult?: RunDiscardResult };

/** Lightweight standalone-viewer response used to detect workspace changes. */
export interface RevisionMessage {
  type: 'revision';
  revision: string;
  workspace: string;
  workspaceValid: boolean;
  message: string;
}

export type WebviewCommand = (
  | { command: 'openRun'; runId: string }
  | { command: 'records'; query?: string; scope?: 'all' | 'run'; runId?: string; offset?: number; limit?: number }
  | { command: 'memories'; query?: string; offset?: number }
  | { command: 'openMemory'; memoryId: string }
  | { command: 'openMemorySource'; memoryId: string }
  | { command: 'getSettings'; requestId: string; workspace?: string }
  | { command: 'saveSettings'; requestId: string; workspace: string; revision: string; values: Record<string, unknown> }
  | { command: 'resetSettings'; requestId: string; workspace: string; revision: string; confirmed: true }
  | { command: 'ready' }
  | { command: 'chooseWorkspace' }
  | { command: 'selectWorkspace'; workspace: string }
  | { command: 'browseWorkspace'; requestId: string; path?: string }
  | { command: 'selectRun'; sessionId: string }
  | { command: 'discardRun'; runId: string; targetSessionId: string; workspace: string; confirmed: true; confirmationRunId: string }
  | { command: 'refresh' }
  | { command: 'back' }
  | { command: 'debug' }
  | { command: 'archiveEvents'; archiveId: string }
  | { command: 'openArchive'; archiveId: string }
  | { command: 'search'; query: string }
  | { command: 'openSearchResult'; itemId: number }) & { source_db?: string };

/** Browser-only request; the VS Code host deliberately never receives this command. */
export type BrowserApiCommand = WebviewCommand | { command: 'revision'; workspace?: string };
