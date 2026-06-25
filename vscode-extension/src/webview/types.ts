export interface TaplStatus {
  active_run: Record<string, unknown> | null;
  task_counts: Record<string, number>;
  incomplete_tasks: number;
  plans: TaplItem[];
  tasks: TaplItem[];
  findings: TaplItem[];
  recent_events: TaplEvent[];
  schema: Record<string, string>;
}

export interface TaplItem {
  stable_id: string;
  kind: string;
  title: string;
  body?: string;
  status?: string;
  required_subagent?: string;
  source?: string;
  updated_at?: string;
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
  required_subagent?: string;
  verification?: string;
  result?: string;
  blocker?: string;
  next_action?: string;
  related_ids?: string;
  impact?: string;
}

export type WebviewView =
  | { type: 'overview'; status: TaplStatus; archives: TaplArchive[]; searchQuery: string }
  | { type: 'archive'; archive: TaplArchive; detail?: TaplArchiveDetail }
  | { type: 'archiveEvents'; archive: TaplArchive; detail?: TaplArchiveDetail }
  | { type: 'debug'; status: TaplStatus }
  | { type: 'search'; search: TaplSearchPayload }
  | { type: 'searchItem'; result: TaplSearchResult; detail?: TaplItemDetail }
  | { type: 'error'; message: string };

export type HostMessage =
  | { type: 'hydrate'; view: WebviewView }
  | { type: 'view:update'; view: WebviewView }
  | { type: 'error'; message: string };

export type WebviewCommand =
  | { command: 'ready' }
  | { command: 'refresh' }
  | { command: 'back' }
  | { command: 'debug' }
  | { command: 'archiveEvents'; archiveId: string }
  | { command: 'openArchive'; archiveId: string }
  | { command: 'search'; query: string }
  | { command: 'openSearchResult'; itemId: number };
