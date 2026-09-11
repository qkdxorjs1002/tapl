import * as vscode from 'vscode';
import {
  resolveLocale,
  translate,
  translateStatus,
  type SupportedLocale,
  type TranslationKey,
  type TranslationParams
} from './i18n';
import {
  TaplMcpClientPool,
  taplMcpCommandCandidates,
  type TaplMcpWorkspace
} from './taplMcpClient';

import type { DisplayLayout, AssociativeMemory, HostCapabilities, TaplStatus, TaplItem, TaplArchive, TaplEvent, TaplSearchResult, TaplSearchPayload, TaplArchiveDetail, TaplItemDetail, WebviewView, HostMessage as HostWebviewMessage } from './viewer/types';

type NodeKind = 'overview' | 'task' | 'archive' | 'empty';
type DisplayLanguage = 'auto' | SupportedLocale;

type PanelView =
  | { type: 'overview' | 'debug' }
  | { type: 'archive' | 'archiveEvents'; archiveId: string }
  | { type: 'search'; query: string }
  | { type: 'searchItem'; itemId: number }
  | { type: 'memories'; query: string; offset: number }
  | { type: 'memory' | 'memorySource'; memoryId: string };

const COMMAND_PREFIX = "taplWorkflow";
const TAPL_DB_WATCH_DEBOUNCE_MS = 2000;
const TAPL_MCP_PATH_SETTING = "taplMcpPath";
const LANGUAGE_SETTING = "language";
const LAYOUT_SETTING = "layout";
let taplMcpClients: TaplMcpClientPool | undefined;
let selectedWorkspacePath: string | undefined;

function localize(key: TranslationKey, params?: TranslationParams): string {
  return translate(displayLocale(), key, params);
}
const DEFAULT_STATUS: TaplStatus = {
  active_run: null,
  task_counts: {
    Pending: 0,
    'In Progress': 0,
    Completed: 0,
    Blocked: 0,
    Skipped: 0
  },
  incomplete_tasks: 0,
  plans: [],
  tasks: [],
  findings: [],
  recent_events: [],
  schema: {}
};
export function activate(context: vscode.ExtensionContext): void {
  taplMcpClients = new TaplMcpClientPool();
  const activeProvider = new ActiveProvider();
  const archiveProvider = new ArchiveProvider();
  const webviewManager = new WorkflowWebviewManager(context.extensionUri);

  const refreshTrees = () => {
    activeProvider.refresh();
    archiveProvider.refresh();
  };
  const refreshAll = () => {
    refreshTrees();
    void webviewManager.refresh();
  };
  const debouncedRefresh = createDebouncedRefresh(refreshAll, TAPL_DB_WATCH_DEBOUNCE_MS);

  context.subscriptions.push(
    debouncedRefresh,
    { dispose: () => taplMcpClients?.invalidate() },
    vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.active`, activeProvider),
    vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.archives`, archiveProvider),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.refresh`, refreshAll),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.openOverview`, async () => {
      await webviewManager.openOverview();
    }),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.openArchive`, async (node?: unknown) => {
      if (node instanceof WorkflowNode && node.archive) {
        await webviewManager.openArchive(node.archive);
      }
    }),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.search`, async () => {
      await webviewManager.searchFromCommand();
    }),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration(`${COMMAND_PREFIX}.${TAPL_MCP_PATH_SETTING}`)) {
        taplMcpClients?.invalidate();
        refreshAll();
        return;
      }
      if (
        !event.affectsConfiguration(`${COMMAND_PREFIX}.${LANGUAGE_SETTING}`)
        && !event.affectsConfiguration(`${COMMAND_PREFIX}.${LAYOUT_SETTING}`)
      ) {
        return;
      }
      refreshAll();
    })
  );

  const workspaceWatchers = new Map<string, vscode.Disposable[]>();
  const syncWatchers = () => {
    const roots = vscode.workspace.workspaceFolders ?? [];
    for (const [path, watchers] of workspaceWatchers) {
      if (!roots.some((root) => root.uri.fsPath === path)) {
        watchers.forEach((watcher) => watcher.dispose());
        workspaceWatchers.delete(path);
      }
    }
    for (const root of roots) {
      if (workspaceWatchers.has(root.uri.fsPath)) { continue; }
      const watchers: vscode.Disposable[] = [];
      for (const pattern of ['.tapl/tapl.db', '.tapl/tapl.db-wal', '.tapl/tapl.db-shm']) {
        const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, pattern));
        watchers.push(watcher, watcher.onDidChange(debouncedRefresh.schedule), watcher.onDidCreate(debouncedRefresh.schedule), watcher.onDidDelete(debouncedRefresh.schedule));
      }
      workspaceWatchers.set(root.uri.fsPath, watchers);
    }
  };
  syncWatchers();
  context.subscriptions.push(
    { dispose: () => { for (const watchers of workspaceWatchers.values()) { watchers.forEach((watcher) => watcher.dispose()); } } },
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      syncWatchers();
      webviewManager.resetWorkspace();
      refreshAll();
    })
  );
}

export async function deactivate(): Promise<void> {
  const clients = taplMcpClients;
  taplMcpClients = undefined;
  await clients?.dispose();
}

class WorkflowNode extends vscode.TreeItem {
  readonly kind: NodeKind;
  readonly archive?: TaplArchive;

  constructor(options: {
    label: string;
    kind: NodeKind;
    description?: string;
    tooltip?: string;
    icon?: string;
    archive?: TaplArchive;
  }) {
    super(options.label, vscode.TreeItemCollapsibleState.None);
    this.kind = options.kind;
    this.archive = options.archive;
    this.description = options.description;
    this.tooltip = options.tooltip;
    this.contextValue = `tapl-${options.kind}`;
    if (options.icon) {
      this.iconPath = new vscode.ThemeIcon(options.icon);
    }
    if (options.kind === 'overview') {
      this.command = {
        command: `${COMMAND_PREFIX}.openOverview`,
        title: localize('openTaplDashboard'),
        arguments: [this]
      };
    }
    if (options.kind === 'archive') {
      this.command = {
        command: `${COMMAND_PREFIX}.openArchive`,
        title: localize('openTaplArchive'),
        arguments: [this]
      };
    }
  }
}

class ActiveProvider implements vscode.TreeDataProvider<WorkflowNode> {
  private readonly changedEmitter = new vscode.EventEmitter<WorkflowNode | undefined>();
  readonly onDidChangeTreeData = this.changedEmitter.event;

  refresh(): void {
    this.changedEmitter.fire(undefined);
  }

  getTreeItem(element: WorkflowNode): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: WorkflowNode): Promise<WorkflowNode[]> {
    if (element) {
      return [];
    }
    const root = getWorkspaceRoot();
    if (!root) {
      return [emptyNode(localize('openWorkspaceFolder'))];
    }
    const result = await safeStatus();
    if (!result.ok) {
      return [emptyNode(result.error)];
    }
    const status = result.value;
    const nodes: WorkflowNode[] = [
      new WorkflowNode({
        label: localize('dashboardLabel'),
        kind: 'overview',
        description: status.active_run ? localize('activeRun') : localize('noActiveRun'),
        tooltip: localize('openWorkflowDashboard'),
        icon: 'dashboard'
      })
    ];
    for (const task of status.tasks) {
      const description = task.status ? translateStatus(displayLocale(), task.status) : undefined;
      nodes.push(new WorkflowNode({
        label: `${task.stable_id} ${task.title}`,
        kind: 'task',
        description,
        tooltip: task.body || task.title,
        icon: iconForStatus(task.status)
      }));
    }
    return nodes;
  }
}

class ArchiveProvider implements vscode.TreeDataProvider<WorkflowNode> {
  private readonly changedEmitter = new vscode.EventEmitter<WorkflowNode | undefined>();
  readonly onDidChangeTreeData = this.changedEmitter.event;

  refresh(): void {
    this.changedEmitter.fire(undefined);
  }

  getTreeItem(element: WorkflowNode): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: WorkflowNode): Promise<WorkflowNode[]> {
    if (element) {
      return [];
    }
    const result = await safeArchives();
    if (!result.ok) {
      return [emptyNode(result.error)];
    }
    if (result.value.length === 0) {
      return [emptyNode(localize('noTaplArchives'))];
    }
    return result.value.map((archive) => new WorkflowNode({
      label: archive.slug,
      kind: 'archive',
      description: formatTimestamp(archive.created_at),
      tooltip: archive.summary || archive.id,
      icon: 'archive',
      archive
    }));
  }
}

class WorkflowWebviewManager {
  private panel: vscode.WebviewPanel | undefined;
  private currentView: PanelView = { type: 'overview' };
  private readonly backStack: PanelView[] = [];
  private lastSearchQuery = '';
  private shellReady = false;
  private generation = 0;
  private capabilities: HostCapabilities = { associativeMemory: false };

  constructor(private readonly extensionUri: vscode.Uri) {}

  async openOverview(): Promise<void> {
    this.backStack.length = 0;
    await this.navigate({ type: 'overview' }, { reveal: true });
  }

  async openArchive(archive: TaplArchive): Promise<void> {
    await this.navigate({ type: 'archive', archiveId: archive.id }, { pushHistory: this.panel !== undefined, reveal: true });
  }

  resetWorkspace(): void {
    this.generation += 1;
    this.backStack.length = 0;
    this.currentView = { type: 'overview' };
    this.capabilities = { associativeMemory: false };
  }

  async refresh(): Promise<void> {
    if (this.panel) {
      await this.postCurrentView('view:update');
    }
  }

  async searchFromCommand(): Promise<void> {
    const query = await vscode.window.showInputBox({ prompt: localize('searchWorkflowHistory'), value: this.lastSearchQuery });
    if (query?.trim()) {
      await this.runSearch(query, true);
    }
  }

  private async navigate(view: PanelView, options: { pushHistory?: boolean; reveal?: boolean } = {}): Promise<void> {
    if (options.pushHistory) {
      this.backStack.push(this.currentView);
    }
    this.currentView = view;
    const panel = this.ensurePanel(options.reveal ?? false);
    panel.title = workspaceTaplTitle();
    if (!this.shellReady) {
      panel.webview.html = this.renderShell(panel.webview);
      this.shellReady = true;
    }
    await this.postCurrentView('view:update');
  }

  private ensurePanel(reveal: boolean): vscode.WebviewPanel {
    if (this.panel) {
      if (reveal) { this.panel.reveal(vscode.ViewColumn.One); }
      return this.panel;
    }
    this.panel = vscode.window.createWebviewPanel('taplWorkflow.viewer', workspaceTaplTitle(), vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, 'webview-dist')]
    });
    this.panel.webview.onDidReceiveMessage((message: unknown) => { void this.handleMessage(message); });
    this.panel.onDidDispose(() => {
      this.generation += 1;
      this.panel = undefined;
      this.shellReady = false;
    });
    return this.panel;
  }

  private renderShell(webview: vscode.Webview): string {
    const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'webview-dist', 'assets', 'index.js'));
    const styleUri = webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, 'webview-dist', 'assets', 'index.css'));
    return `<!doctype html>
<html lang="${displayLocale()}">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource}; script-src ${webview.cspSource}; font-src ${webview.cspSource};">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${styleUri}">
  <title>${localize('appTitle')}</title>
</head>
<body><div id="root"></div><script type="module" src="${scriptUri}"></script></body>
</html>`;
  }

  private async postCurrentView(type: 'hydrate' | 'view:update'): Promise<void> {
    const panel = this.panel;
    if (!panel) { return; }
    const generation = ++this.generation;
    const root = getWorkspaceRoot();
    const view = await this.buildCurrentView(this.currentView);
    // A slow read must not replace a newer navigation, workspace or closed panel.
    if (generation !== this.generation || panel !== this.panel || root !== getWorkspaceRoot()) { return; }
    if (view.type === 'overview' || view.type === 'debug') {
      this.capabilities = { associativeMemory: view.status.viewer_capabilities?.associativeMemory === true };
    }
    panel.title = workspaceTaplTitle();
    const message: HostWebviewMessage = {
      type, view, locale: displayLocale(), layout: displayLayout(),
      workspace: root?.uri.fsPath, capabilities: this.capabilities
    };
    await panel.webview.postMessage(message);
  }

  private async buildCurrentView(route: PanelView): Promise<WebviewView> {
    if (route.type === 'archive' || route.type === 'archiveEvents') {
      const detail = await safeArchiveDetail(route.archiveId);
      return detail.ok ? { type: route.type, archive: detail.value.archive, detail: detail.value } : { type: 'error', message: detail.error };
    }
    if (route.type === 'search') {
      const result = await searchTapl(route.query);
      return result.ok ? { type: 'search', search: result.value } : { type: 'error', message: result.error };
    }
    if (route.type === 'searchItem') {
      return this.itemView(route.itemId);
    }
    if (route.type === 'memories') {
      const result = await callTaplMcp('tapl_recall', { query: route.query, offset: route.offset, limit: 50 });
      if (!result.ok) { return { type: 'error', message: result.error }; }
      const payload = result.value;
      return { type: 'memories', query: route.query, offset: route.offset, limit: 50,
        total: Number(payload.total ?? 0), memories: (payload.memories ?? []) as AssociativeMemory[] };
    }
    if (route.type === 'memory' || route.type === 'memorySource') {
      const result = await callTaplMcp('tapl_get_memory', { memory_id: route.memoryId });
      if (!result.ok) { return { type: 'error', message: result.error }; }
      const memory = (result.value.memory ?? null) as AssociativeMemory | null;
      const source = memory?.source_record;
      if (route.type === 'memorySource' && memory?.source_available && source) {
        if (source.kind === 'item' && source.item) { return this.itemView(source.item.id); }
        if (source.kind === 'run' && source.run) { return { type: 'memorySource', memoryId: route.memoryId, run: source.run }; }
      }
      return { type: 'memory', memoryId: route.memoryId, memory };
    }
    const status = await safeStatus({ full: true, includeEvents: route.type === 'debug' });
    if (!status.ok) { return { type: 'error', message: status.error }; }
    if (route.type === 'debug') { return { type: 'debug', status: status.value }; }
    const archives = await safeArchives(8);
    return archives.ok
      ? { type: 'overview', status: status.value, archives: archives.value, searchQuery: this.lastSearchQuery, workspace: getWorkspaceRoot()?.uri.fsPath }
      : { type: 'error', message: archives.error };
  }

  private async itemView(itemId: number): Promise<WebviewView> {
    const detail = await safeItemDetail(itemId);
    if (!detail.ok) { return { type: 'error', message: detail.error }; }
    const item = await enrichTaskDetail(detail.value);
    return { type: 'searchItem', result: searchResultFromItem(item), detail: item };
  }

  private async runSearch(query: string, reveal = false): Promise<void> {
    const trimmed = query.trim();
    if (!trimmed) { return; }
    this.lastSearchQuery = trimmed;
    await this.navigate({ type: 'search', query: trimmed }, { pushHistory: this.currentView.type !== 'search', reveal });
  }

  private async handleMessage(message: unknown): Promise<void> {
    if (!isRecord(message) || typeof message.command !== 'string') { return; }
    switch (message.command) {
      case 'ready': await this.postCurrentView('hydrate'); return;
      case 'refresh': await this.refresh(); return;
      case 'back': await this.navigate(this.backStack.pop() ?? { type: 'overview' }); return;
      case 'chooseWorkspace': {
        const root = await vscode.window.showWorkspaceFolderPick();
        if (root) {
          selectedWorkspacePath = root.uri.fsPath;
          this.capabilities = { associativeMemory: false };
          await this.openOverview();
          await vscode.commands.executeCommand(`${COMMAND_PREFIX}.refresh`);
        }
        return;
      }
      case 'debug': await this.navigate({ type: 'debug' }, { pushHistory: true }); return;
      case 'archiveEvents':
      case 'openArchive':
        if (typeof message.archiveId === 'string' && message.archiveId) {
          await this.navigate({ type: message.command === 'archiveEvents' ? 'archiveEvents' : 'archive', archiveId: message.archiveId }, { pushHistory: true });
        }
        return;
      case 'search': if (typeof message.query === 'string') { await this.runSearch(message.query); } return;
      case 'openSearchResult':
        if (typeof message.itemId === 'number' && Number.isInteger(message.itemId) && message.itemId > 0) {
          await this.navigate({ type: 'searchItem', itemId: message.itemId }, { pushHistory: true });
        }
        return;
      case 'memories': {
        if (!this.capabilities.associativeMemory) { return; }
        const query = message.query ?? '';
        const offset = message.offset ?? 0;
        if (typeof query !== 'string' || query.length > 500 || typeof offset !== 'number' || !Number.isInteger(offset) || offset < 0 || offset > 1000000) { return; }
        await this.navigate({ type: 'memories', query, offset }, { pushHistory: this.currentView.type !== 'memories' });
        return;
      }
      case 'openMemory':
      case 'openMemorySource':
        if (this.capabilities.associativeMemory && typeof message.memoryId === 'string' && message.memoryId) {
          await this.navigate({ type: message.command === 'openMemory' ? 'memory' : 'memorySource', memoryId: message.memoryId }, { pushHistory: true });
        }
        return;
    }
  }
}

function iconForStatus(status?: string): string {
  switch (status) {
    case 'Completed':
      return 'pass-filled';
    case 'Blocked':
      return 'error';
    case 'In Progress':
      return 'sync';
    case 'Skipped':
      return 'circle-slash';
    default:
      return 'circle-outline';
  }
}

function conciseText(value: unknown, maxLength: number): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) {
    return text;
  }
  return `${text.slice(0, Math.max(0, maxLength - 3)).trimEnd()}...`;
}

function formatTimestamp(value: unknown): string {
  const raw = String(value ?? '');
  if (!raw) {
    return '';
  }
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) {
    return raw;
  }
  const twoDigits = (part: number) => String(part).padStart(2, '0');
  return [
    `${twoDigits(date.getFullYear() % 100)}-${twoDigits(date.getMonth() + 1)}-${twoDigits(date.getDate())}`,
    `${twoDigits(date.getHours())}:${twoDigits(date.getMinutes())}:${twoDigits(date.getSeconds())}`
  ].join(' ');
}

async function safeStatus(
  options: { full?: boolean; includeEvents?: boolean; eventsLimit?: number } = {},
  root = getWorkspaceRoot()
): Promise<{ ok: true; value: TaplStatus } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_get_status', {
    full: options.full ?? false,
    include_events: options.includeEvents ?? false,
    events_limit: options.eventsLimit ?? 12
  }, root);
  if (!result.ok) {
    return result;
  }
  return {
    ok: true,
    value: {
      ...DEFAULT_STATUS,
      ...(result.value as unknown as TaplStatus)
    }
  };
}

async function safeArchives(limit?: number): Promise<{ ok: true; value: TaplArchive[] } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_list_archives', limit === undefined ? {} : { limit });
  if (!result.ok) {
    return result;
  }
  const payload = result.value as { ok?: boolean; error?: string; archives?: TaplArchive[] };
  if (payload.ok === false) {
    return { ok: false, error: payload.error ?? localize('failedLoadArchiveDetail') };
  }
  return { ok: true, value: Array.isArray(payload.archives) ? payload.archives : [] };
}

async function safeArchiveDetail(archiveId: string): Promise<{ ok: true; value: TaplArchiveDetail } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_get_archive', { archive_id: archiveId });
  if (!result.ok) {
    return result;
  }
  const payload = result.value as {
    ok?: boolean;
    error?: string;
    archive?: TaplArchive;
    items?: TaplItem[];
    events?: TaplEvent[];
  };
  if (payload.ok === false) {
    return { ok: false, error: payload.error ?? localize('failedLoadArchiveDetail') };
  }
  if (!payload.archive) {
    return { ok: false, error: localize('missingArchiveDetail') };
  }
  return {
    ok: true,
    value: {
      archive: payload.archive,
      items: Array.isArray(payload.items) ? payload.items : [],
      events: Array.isArray(payload.events) ? payload.events : []
    }
  };
}

async function safeItemDetail(itemId: number): Promise<{ ok: true; value: TaplItemDetail } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_get_item', { item_id: itemId });
  if (!result.ok) {
    return result;
  }
  const payload = result.value as { ok?: boolean; error?: string; item?: TaplItemDetail };
  if (payload.ok === false) {
    return { ok: false, error: payload.error ?? localize('failedLoadItemDetail') };
  }
  if (!payload.item) {
    return { ok: false, error: localize('missingItemDetail') };
  }
  return { ok: true, value: payload.item };
}

async function enrichTaskDetail(detail: TaplItemDetail): Promise<TaplItemDetail> {
  if (detail.kind !== 'task' || detail.archived || detail.run_status === 'archived') {
    return detail;
  }
  const status = await safeStatus({ full: true });
  if (!status.ok) {
    return detail;
  }
  const task = status.value.tasks.find((candidate) => candidate.stable_id === detail.stable_id);
  if (!task) {
    return detail;
  }
  return {
    ...detail,
    execution_mode: detail.execution_mode ?? task.execution_mode,
    executor_kind: detail.executor_kind ?? task.executor_kind,
    parallel_group: detail.parallel_group ?? task.parallel_group,
    owned_paths: detail.owned_paths ?? task.owned_paths,
    depends_on: detail.depends_on ?? task.depends_on,
    active_execution: task.active_execution
  };
}

async function searchTapl(query: string): Promise<{ ok: true; value: TaplSearchPayload } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_search_history', { query });
  if (!result.ok) {
    return result;
  }
  return { ok: true, value: result.value as unknown as TaplSearchPayload };
}

async function callTaplMcp(
  tool: 'tapl_get_status' | 'tapl_get_item' | 'tapl_search_history' | 'tapl_list_archives' | 'tapl_get_archive' | 'tapl_recall' | 'tapl_get_memory',
  args: Record<string, unknown>,
  root: vscode.WorkspaceFolder | undefined = getWorkspaceRoot()
): Promise<{ ok: true; value: Record<string, unknown> } | { ok: false; error: string }> {
  if (!root) {
    return { ok: false, error: localize('openWorkspaceToUseTapl') };
  }
  try {
    const clients = taplMcpClients ??= new TaplMcpClientPool();
    return { ok: true, value: await clients.callTool(taplMcpWorkspace(root), tool, args) };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      ok: false,
      error: `${message} Configure ${COMMAND_PREFIX}.${TAPL_MCP_PATH_SETTING} with the tapl-mcp executable path if it is not on PATH.`
    };
  }
}

function taplMcpWorkspace(root: vscode.WorkspaceFolder): TaplMcpWorkspace {
  const configuration = vscode.workspace.getConfiguration(COMMAND_PREFIX, root.uri);
  return {
    key: root.uri.fsPath,
    cwd: root.uri.fsPath,
    commands: taplMcpCommandCandidates(configuration.get<string>(TAPL_MCP_PATH_SETTING, ''))
  };
}

function displayLocale(): SupportedLocale {
  const configured = vscode.workspace
    .getConfiguration(COMMAND_PREFIX)
    .get<unknown>(LANGUAGE_SETTING, 'auto');
  const language: DisplayLanguage = configured === 'ko' || configured === 'en'
    ? configured
    : 'auto';
  return resolveLocale(language === 'auto' ? vscode.env.language : language);
}

function displayLayout(): DisplayLayout {
  const configured = vscode.workspace
    .getConfiguration(COMMAND_PREFIX)
    .get<unknown>(LAYOUT_SETTING, 'auto');
  return configured === 'small' || configured === 'medium' || configured === 'large'
    ? configured
    : 'auto';
}

function getWorkspaceRoot(): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.workspaceFolders?.find((root) => root.uri.fsPath === selectedWorkspacePath) ?? vscode.workspace.workspaceFolders?.[0];
}

function workspaceTaplTitle(): string {
  const rootName = getWorkspaceRoot()?.name.trim();
  return rootName ? `${rootName} tapl` : 'tapl';
}

function emptyNode(label: string): WorkflowNode {
  return new WorkflowNode({
    label,
    kind: 'empty',
    icon: 'info',
    tooltip: label
  });
}

function searchResultFromItem(item: TaplItemDetail): TaplSearchResult {
  return {
    id: item.id,
    stable_id: item.stable_id,
    kind: item.kind,
    title: item.title,
    status: item.status,
    source: item.source,
    snippet: item.body || item.raw_text,
    search_source: 'item'
  };
}

function createDebouncedRefresh(callback: () => void, delayMs: number): vscode.Disposable & { schedule: () => void } {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    schedule: () => {
      if (timer) {
        clearTimeout(timer);
      }
      timer = setTimeout(() => {
        timer = undefined;
        callback();
      }, delayMs);
    },
    dispose: () => {
      if (timer) {
        clearTimeout(timer);
        timer = undefined;
      }
    }
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
