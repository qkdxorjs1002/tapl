import * as childProcess from 'child_process';
import * as path from 'path';
import * as vscode from 'vscode';

type NodeKind = 'overview' | 'task' | 'archive' | 'empty';

interface TaplStatus {
  active_run: Record<string, unknown> | null;
  task_counts: Record<string, number>;
  incomplete_tasks: number;
  plans: TaplItem[];
  tasks: TaplItem[];
  findings: TaplItem[];
  recent_events: TaplEvent[];
  schema: Record<string, string>;
}

interface TaplItem {
  stable_id: string;
  kind: string;
  title: string;
  body?: string;
  status?: string;
  source?: string;
  updated_at?: string;
}

interface TaplArchive {
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

interface TaplEvent {
  event_type: string;
  tool_name?: string;
  mode: string;
  message?: string;
  created_at: string;
}

interface TaplSearchResult {
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

interface TaplSearchPayload {
  mode: string;
  query: string;
  results: TaplSearchResult[];
}

interface TaplArchiveDetail {
  archive: TaplArchive;
  items: TaplItem[];
  events: TaplEvent[];
}

interface TaplItemDetail extends TaplItem {
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

interface ExecResult {
  stdout: string;
  stderr: string;
}

interface WorkflowTab {
  id: string;
  label: string;
  count: number;
  selected: boolean;
  content: string;
}

type MarkdownLabelRun = {
  label: string;
  value: string;
};

type PanelView =
  | { type: 'overview' }
  | { type: 'archive'; archive: TaplArchive; detail?: TaplArchiveDetail }
  | { type: 'debug' }
  | { type: 'search'; search: TaplSearchPayload }
  | { type: 'searchItem'; result: TaplSearchResult; detail?: TaplItemDetail };

const COMMAND_PREFIX = "taplWorkflow";
const TAPL_DB_WATCH_DEBOUNCE_MS = 2000;
const TAPLCTL_PATH_SETTING = "taplctlPath";
const COMMON_TAPLCTL_COMMANDS = [
  "taplctl",
  "/opt/homebrew/bin/taplctl",
  "/usr/local/bin/taplctl"
];
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
const READABLE_BLOCK_KEY_LABELS = new Set([
  'action',
  'affected files',
  'affected files/interfaces',
  'affected interfaces',
  'approval needs',
  'blocker',
  'execution order',
  'goal',
  'impact',
  'next action',
  'objective',
  'related ids',
  'request',
  'required subagent',
  'requirements',
  'requirements trace',
  'result',
  'risks',
  'selected approach',
  'spec',
  'summary',
  'validation',
  'verification',
  '검증',
  '결과',
  '다음 작업',
  '목표',
  '선택한 접근',
  '승인 필요',
  '실행 순서',
  '영향 파일',
  '요구사항',
  '위험',
  '차단 사유'
]);
const READABLE_BLOCK_LABEL_PATTERN = new RegExp(
  `(?:^|\\s)(REQ-\\d+|${Array.from(READABLE_BLOCK_KEY_LABELS)
    .sort((left, right) => right.length - left.length)
    .map(escapeRegExp)
    .join('|')}):\\s*`,
  'gi'
);

export function activate(context: vscode.ExtensionContext): void {
  const activeProvider = new ActiveProvider();
  const archiveProvider = new ArchiveProvider();
  const webviewManager = new WorkflowWebviewManager();

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
    })
  );

  const root = getWorkspaceRoot();
  if (root) {
    for (const pattern of ['.tapl/tapl.db', '.tapl/tapl.db-wal', '.tapl/tapl.db-shm']) {
      const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, pattern));
      context.subscriptions.push(
        watcher,
        watcher.onDidChange(debouncedRefresh.schedule),
        watcher.onDidCreate(debouncedRefresh.schedule),
        watcher.onDidDelete(debouncedRefresh.schedule)
      );
    }
  }
}

export function deactivate(): void {
  // Disposables are owned by the extension context.
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
        title: 'Open tapl Dashboard',
        arguments: [this]
      };
    }
    if (options.kind === 'archive') {
      this.command = {
        command: `${COMMAND_PREFIX}.openArchive`,
        title: 'Open tapl Archive',
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
      return [emptyNode('Open a workspace folder.')];
    }
    const result = await safeTapl(['status', '--json']);
    if (!result.ok) {
      return [emptyNode(result.error)];
    }
    const status = result.value;
    const nodes: WorkflowNode[] = [
      new WorkflowNode({
        label: 'tapl Dashboard',
        kind: 'overview',
        description: status.active_run ? 'active run' : 'no active run',
        tooltip: 'Open tapl workflow dashboard',
        icon: 'dashboard'
      })
    ];
    for (const task of status.tasks) {
      nodes.push(new WorkflowNode({
        label: `${task.stable_id} ${task.title}`,
        kind: 'task',
        description: task.status,
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
      return [emptyNode('No tapl archives found.')];
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
  private lastSearch: TaplSearchPayload | undefined;

  async openOverview(): Promise<void> {
    this.backStack.length = 0;
    await this.navigate({ type: 'overview' }, { reveal: true });
  }

  async openArchive(archive: TaplArchive): Promise<void> {
    const detail = await safeArchiveDetail(archive.id);
    if (!detail.ok) {
      void vscode.window.showWarningMessage(detail.error);
    }
    await this.navigate(
      { type: 'archive', archive: detail.ok ? detail.value.archive : archive, detail: detail.ok ? detail.value : undefined },
      { pushHistory: this.panel !== undefined, reveal: true }
    );
  }

  async refresh(): Promise<void> {
    if (this.panel) {
      await this.render(this.titleForView(this.currentView), { reveal: false });
    }
  }

  async searchFromCommand(): Promise<void> {
    const query = await vscode.window.showInputBox({
      prompt: 'Search tapl workflow history',
      value: this.lastSearch?.query ?? ''
    });
    if (query === undefined) {
      return;
    }
    await this.runSearch(query, { reveal: true });
  }

  private async navigate(view: PanelView, options: { pushHistory?: boolean; reveal?: boolean } = {}): Promise<void> {
    if (options.pushHistory) {
      this.backStack.push(this.currentView);
    }
    this.currentView = view;
    await this.render(this.titleForView(view), { reveal: options.reveal ?? true });
  }

  private async goBack(): Promise<void> {
    const previous = this.backStack.pop() ?? { type: 'overview' as const };
    this.currentView = previous;
    await this.render(this.titleForView(previous), { reveal: false });
  }

  private titleForView(view: PanelView): string {
    if (view.type === 'archive') {
      return view.archive.slug;
    }
    if (view.type === 'debug') {
      return 'tapl Debug';
    }
    if (view.type === 'search') {
      return 'tapl Search';
    }
    if (view.type === 'searchItem') {
      return view.result.title;
    }
    return 'tapl Workflow';
  }

  private async render(title: string, options: { reveal?: boolean } = {}): Promise<void> {
    const panel = this.ensurePanel(title, options.reveal ?? true);
    panel.title = title;
    panel.webview.html = await this.renderCurrentView(panel.webview);
  }

  private ensurePanel(title: string, reveal: boolean): vscode.WebviewPanel {
    if (this.panel) {
      if (reveal) {
        this.panel.reveal(vscode.ViewColumn.One);
      }
      return this.panel;
    }

    this.panel = vscode.window.createWebviewPanel(
      'taplWorkflow.viewer',
      title,
      vscode.ViewColumn.One,
      {
        enableScripts: true,
        retainContextWhenHidden: false
      }
    );
    this.panel.webview.onDidReceiveMessage((message: unknown) => {
      void this.handleMessage(message);
    });
    this.panel.onDidDispose(() => {
      this.panel = undefined;
    });
    return this.panel;
  }

  private async renderCurrentView(webview: vscode.Webview): Promise<string> {
    if (this.currentView.type === 'archive') {
      return renderPage(
        webview,
        renderArchiveView(this.currentView.archive, this.currentView.detail),
        `archive:${this.currentView.archive.id}`
      );
    }
    if (this.currentView.type === 'search') {
      return renderPage(
        webview,
        renderSearchView(this.currentView.search),
        `search:${this.currentView.search.query}`
      );
    }
    if (this.currentView.type === 'searchItem') {
      return renderPage(
        webview,
        renderSearchItemView(this.currentView.result, this.currentView.detail),
        `search-item:${this.currentView.result.id ?? this.currentView.result.stable_id}`
      );
    }
    if (this.currentView.type === 'debug') {
      const status = await safeTapl(['status', '--json', '--include-events']);
      if (!status.ok) {
        return renderPage(webview, renderError(status.error), 'error');
      }
      return renderPage(webview, renderDebugView(status.value), 'debug');
    }
    const status = await safeTapl(['status', '--json', '--full']);
    if (!status.ok) {
      return renderPage(webview, renderError(status.error), 'error');
    }
    const archives = await safeArchives(8);
    if (!archives.ok) {
      return renderPage(webview, renderError(archives.error), 'error');
    }
    return renderPage(webview, renderOverview(status.value, archives.value, this.lastSearch?.query ?? ''), 'overview');
  }

  private async handleMessage(message: unknown): Promise<void> {
    if (!isRecord(message) || typeof message.command !== 'string') {
      return;
    }
    if (message.command === 'refresh') {
      await this.refresh();
      return;
    }
    if (message.command === 'back') {
      await this.goBack();
      return;
    }
    if (message.command === 'debug') {
      await this.navigate({ type: 'debug' }, { pushHistory: true, reveal: false });
      return;
    }
    if (message.command === 'openArchive' && typeof message.archiveId === 'string') {
      await this.openArchiveById(message.archiveId);
      return;
    }
    if (message.command === 'search' && typeof message.query === 'string') {
      await this.runSearch(message.query, { reveal: false });
      return;
    }
    if (message.command === 'openSearchResult') {
      await this.openSearchResult(message.itemId);
    }
  }

  private async runSearch(query: string, options: { reveal?: boolean; pushHistory?: boolean } = {}): Promise<void> {
    const trimmed = query.trim();
    if (!trimmed) {
      return;
    }
    if (!this.panel && options.pushHistory !== false) {
      await this.navigate({ type: 'overview' }, { reveal: options.reveal ?? true });
    }
    const result = await searchTapl(trimmed);
    const search = result.ok
      ? result.value
      : {
          mode: 'error',
          query: trimmed,
          results: [{ stable_id: 'ERROR', kind: 'error', title: result.error, search_source: 'taplctl' }]
        };
    this.lastSearch = search;
    await this.navigate(
      { type: 'search', search },
      { pushHistory: options.pushHistory ?? this.currentView.type !== 'search', reveal: options.reveal ?? false }
    );
  }

  private async openSearchResult(rawItemId: unknown): Promise<void> {
    const itemId = typeof rawItemId === 'number' ? rawItemId : Number(rawItemId);
    if (!Number.isFinite(itemId)) {
      return;
    }
    const detail = await safeItemDetail(itemId);
    if (!detail.ok) {
      void vscode.window.showWarningMessage(detail.error);
      return;
    }
    const result = this.searchResultForItemId(itemId) ?? searchResultFromItem(detail.value);
    await this.navigate({ type: 'searchItem', result, detail: detail.value }, { pushHistory: true, reveal: false });
  }

  private searchResultForItemId(itemId: number): TaplSearchResult | undefined {
    if (this.currentView.type === 'search') {
      return this.currentView.search.results.find((result) => result.id === itemId);
    }
    return this.lastSearch?.results.find((result) => result.id === itemId);
  }

  private async openArchiveById(archiveId: string): Promise<void> {
    const detail = await safeArchiveDetail(archiveId);
    if (detail.ok) {
      await this.navigate(
        { type: 'archive', archive: detail.value.archive, detail: detail.value },
        { pushHistory: true, reveal: false }
      );
      return;
    }

    const archives = await safeArchives();
    if (!archives.ok) {
      void vscode.window.showWarningMessage(`${detail.error}\n${archives.error}`);
      return;
    }
    const archive = archives.value.find((item) => item.id === archiveId);
    if (archive) {
      await this.navigate({ type: 'archive', archive }, { pushHistory: true, reveal: false });
      return;
    }
    void vscode.window.showWarningMessage(detail.error);
  }
}

function renderOverview(status: TaplStatus, archives: TaplArchive[], searchQuery = ''): string {
  const taskCounts = status.task_counts || DEFAULT_STATUS.task_counts;
  const pendingTasks = taskCounts.Pending ?? 0;
  const inProgressTasks = taskCounts['In Progress'] ?? 0;
  const blockedTasks = taskCounts.Blocked ?? 0;
  const completedTasks = taskCounts.Completed ?? 0;
  const totalTasks = status.tasks.length;
  const completionPercent = totalTasks ? Math.round((completedTasks / totalTasks) * 100) : 0;
  const openTasks = pendingTasks + inProgressTasks + blockedTasks;
  const activeSummary = status.active_run
    ? String(status.active_run.request_summary || status.active_run.slug || 'active')
    : 'No active run';
  const activeRunSlug = status.active_run ? String(status.active_run.slug || 'active') : 'No active run';
  const workflowTabs: WorkflowTab[] = [
    {
      id: 'plan',
      label: 'Plan',
      count: status.plans.length,
      selected: false,
      content: status.plans.length ? status.plans.map(renderItem).join('') : '<p class="muted">No plan records.</p>'
    },
    {
      id: 'tasks',
      label: 'Tasks',
      count: status.tasks.length,
      selected: true,
      content: status.tasks.length ? status.tasks.map(renderItem).join('') : '<p class="muted">No task records.</p>'
    },
    {
      id: 'findings',
      label: 'Findings',
      count: status.findings.length,
      selected: false,
      content: status.findings.length ? status.findings.map(renderItem).join('') : '<p class="muted">No finding records.</p>'
    }
  ];

  return `
    <header class="workspace-hero">
      <div class="workspace-heading">
        <p class="eyebrow">${escapeHtml(getWorkspaceRoot()?.name ?? 'workspace')}</p>
        <h1>tapl Workflow</h1>
        <p class="workspace-summary">${escapeHtml(conciseText(activeSummary, 160))}</p>
        <div class="workspace-meta" aria-label="Workflow status summary">
          <span class="badge ${status.active_run ? 'in-progress' : ''}">${escapeHtml(activeRunSlug)}</span>
          ${pill('Pending', pendingTasks)}
          ${pill('In Progress', inProgressTasks)}
          ${pill('Blocked', blockedTasks)}
        </div>
      </div>
      <div class="top-actions">
        <button data-command="refresh">Refresh</button>
        <form id="search-form" class="top-search">
          <input id="search-query" value="${escapeAttribute(searchQuery)}" placeholder="Search workflow history" aria-label="Search workflow history" />
          <button type="submit">Search</button>
        </form>
      </div>
    </header>
    <section class="metrics insight-grid">
      ${metric('Run progress', `${completionPercent}%`, `${completedTasks} of ${totalTasks} work items completed`)}
      ${metric('Open work', String(openTasks), `${inProgressTasks} active / ${blockedTasks} blocked`)}
      ${metric('Plans', String(status.plans.length), 'execution specs in this run')}
      ${metric('Archives', String(archives.length), 'recent saved runs')}
    </section>
    <main class="dashboard-grid">
      <section class="dashboard-main">
        <section class="board-section" aria-labelledby="active-board-title">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Work items</p>
              <h2 id="active-board-title">Active board</h2>
            </div>
            <span class="muted">${escapeHtml(status.incomplete_tasks)} incomplete</span>
          </div>
          ${renderTaskBoard(status.tasks)}
        </section>
        <section class="panel saved-views">
          <div class="section-heading">
            <div>
              <p class="eyebrow">Views</p>
              <h2>Workflow records</h2>
            </div>
          </div>
          <section class="workflow-tabs" role="tablist" aria-label="Workflow records">
            ${workflowTabs.map(renderWorkflowTabButton).join('')}
          </section>
          ${workflowTabs.map((tab) => renderWorkflowTabPanel(tab, 'workflow-tab-panel saved-view-panel')).join('')}
        </section>
      </section>
      <aside class="dashboard-rail">
        ${renderRunFocusPanel(status, taskCounts)}
        <section class="panel rail-panel">
          <div class="section-heading compact-heading">
            <div>
              <p class="eyebrow">Activity</p>
              <h2>Recent archives</h2>
            </div>
          </div>
          ${archives.length ? archives.map(renderArchiveSummary).join('') : '<p class="muted">No archives.</p>'}
        </section>
      </aside>
    </main>
    <footer class="debug-footer">
      <button data-command="debug">Debug</button>
    </footer>
  `;
}

function renderWorkflowTabButton(tab: WorkflowTab): string {
  return `
    <button
      id="workflow-tab-${escapeAttribute(tab.id)}"
      class="workflow-tab"
      type="button"
      role="tab"
      data-workflow-tab="${escapeAttribute(tab.id)}"
      aria-controls="workflow-tab-panel-${escapeAttribute(tab.id)}"
      aria-selected="${tab.selected ? 'true' : 'false'}"
      tabindex="${tab.selected ? '0' : '-1'}"
    >
      <span>${escapeHtml(tab.label)}</span>
      <span class="workflow-tab-count">${escapeHtml(tab.count)}</span>
    </button>
  `;
}

function renderWorkflowTabPanel(tab: WorkflowTab, className = 'panel workflow-tab-panel'): string {
  return `
    <section
      id="workflow-tab-panel-${escapeAttribute(tab.id)}"
      class="${escapeAttribute(className)}"
      role="tabpanel"
      data-workflow-tab-panel="${escapeAttribute(tab.id)}"
      aria-labelledby="workflow-tab-${escapeAttribute(tab.id)}"
      ${tab.selected ? '' : 'hidden'}
    >
      <h2>${escapeHtml(tab.label)}</h2>
      ${tab.content}
    </section>
  `;
}

function renderArchiveView(archive: TaplArchive, detail?: TaplArchiveDetail): string {
  const archiveMeta = detail?.archive ?? archive;
  const items = detail?.items ?? [];
  const plans = items.filter((item) => item.kind === 'plan');
  const tasks = items.filter((item) => item.kind === 'task');
  const findings = items.filter((item) => item.kind === 'finding');
  const otherItems = items.filter((item) => !['plan', 'task', 'finding'].includes(item.kind));
  const taskCounts = countTaskStatuses(tasks);
  const workflowTabs: WorkflowTab[] = [
    {
      id: 'plan',
      label: 'Plan',
      count: plans.length,
      selected: false,
      content: detail && plans.length ? plans.map(renderItem).join('') : `<p class="muted">${detail ? 'No plan records.' : 'Archive details unavailable.'}</p>`
    },
    {
      id: 'tasks',
      label: 'Tasks',
      count: tasks.length,
      selected: true,
      content: detail && tasks.length ? tasks.map(renderItem).join('') : `<p class="muted">${detail ? 'No task records.' : 'Archive details unavailable.'}</p>`
    },
    {
      id: 'findings',
      label: 'Findings',
      count: findings.length,
      selected: false,
      content: detail && findings.length ? findings.map(renderItem).join('') : `<p class="muted">${detail ? 'No finding records.' : 'Archive details unavailable.'}</p>`
    }
  ];

  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">${escapeHtml(formatTimestamp(archiveMeta.created_at))}</p>
        <h1>${escapeHtml(archiveMeta.slug)}</h1>
      </div>
      <button data-command="back">Back</button>
    </header>
    <section class="metrics">
      ${metric('Archive', 'Saved', formatTimestamp(archiveMeta.created_at) || archiveMeta.slug)}
      ${metric('Tasks', String(tasks.length), `${taskCounts.Pending + taskCounts['In Progress'] + taskCounts.Blocked} incomplete`)}
      ${metric('Records', String(items.length), `${plans.length} plan / ${findings.length} findings`)}
      ${metric('Events', String(detail?.events.length ?? 0), detail ? 'archived hook events' : 'detail unavailable')}
    </section>
    <section class="status-strip">
      ${pill('Pending', taskCounts.Pending)}
      ${pill('In Progress', taskCounts['In Progress'])}
      ${pill('Completed', taskCounts.Completed)}
      ${pill('Blocked', taskCounts.Blocked)}
      ${pill('Skipped', taskCounts.Skipped)}
    </section>
    <section class="workflow-tabs" role="tablist" aria-label="Archived workflow records">
      ${workflowTabs.map(renderWorkflowTabButton).join('')}
    </section>
    <main class="grid">
      ${workflowTabs.map((tab) => renderWorkflowTabPanel(tab)).join('')}
      <aside class="side-stack">
        ${renderArchiveInfoPanel(archiveMeta)}
        ${detail ? renderArchiveOtherRecordsPanel(otherItems) : renderArchiveUnavailablePanel()}
        <section class="panel">
          <h2>Hook Events</h2>
          ${detail?.events.length ? detail.events.map(renderEvent).join('') : '<p class="muted">No archived hook events.</p>'}
        </section>
      </aside>
    </main>
  `;
}

function renderArchiveInfoPanel(archive: TaplArchive): string {
  return `
    <section class="panel">
      <h2>Summary</h2>
      <p>${escapeHtml(archive.summary || 'No summary recorded.')}</p>
      ${archive.request_summary ? `<p class="muted">${escapeHtml(archive.request_summary)}</p>` : ''}
      <div class="detail-list">
        ${renderDetailField('Run', archive.run_slug)}
        ${renderDetailField('Created', formatTimestamp(archive.run_created_at))}
        ${renderDetailField('Updated', formatTimestamp(archive.run_updated_at))}
        ${renderDetailField('Archived run', formatTimestamp(archive.run_archived_at))}
      </div>
    </section>
  `;
}

function renderArchiveOtherRecordsPanel(items: TaplItem[]): string {
  return `
    <section class="panel">
      <h2>Other Records</h2>
      ${items.length ? items.map(renderItem).join('') : '<p class="muted">No other archived records.</p>'}
    </section>
  `;
}

function renderArchiveUnavailablePanel(): string {
  return `
    <section class="panel">
      <h2>Details</h2>
      <p class="muted">Detailed archive data unavailable.</p>
    </section>
  `;
}

function renderDebugView(status: TaplStatus): string {
  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">Debug</p>
        <h1>Hook Events</h1>
      </div>
      <button data-command="back">Back</button>
    </header>
    <main class="single">
      <section class="panel">
        <h2>Recent Hook Events</h2>
        ${status.recent_events.length ? status.recent_events.map(renderEvent).join('') : '<p class="muted">No hook events.</p>'}
      </section>
    </main>
  `;
}

function renderTaskBoard(tasks: TaplItem[]): string {
  const statuses = ['Pending', 'In Progress', 'Blocked', 'Completed', 'Skipped'];
  return `
    <section class="task-board" aria-label="Tasks grouped by status">
      ${statuses.map((status) => renderTaskLane(status, tasks.filter((task) => task.status === status))).join('')}
    </section>
  `;
}

function renderTaskLane(status: string, tasks: TaplItem[]): string {
  const visibleTasks = tasks.slice(0, 5);
  const hiddenCount = Math.max(tasks.length - visibleTasks.length, 0);
  return `
    <section class="task-lane task-status-${statusClass(status)}">
      <div class="lane-head">
        <div>
          <span class="lane-label">${escapeHtml(status)}</span>
          <span class="lane-count">${escapeHtml(tasks.length)}</span>
        </div>
      </div>
      <div class="lane-list">
        ${visibleTasks.length ? visibleTasks.map(renderTaskCard).join('') : '<p class="muted lane-empty">No work items.</p>'}
        ${hiddenCount ? `<p class="muted lane-more">+${escapeHtml(hiddenCount)} more</p>` : ''}
      </div>
    </section>
  `;
}

function renderTaskCard(task: TaplItem): string {
  const summary = conciseText(task.body || task.title, 150);
  const meta = [
    formatTimestamp(task.updated_at),
    task.source
  ].filter(Boolean).join(' / ');

  return `
    <article class="work-item-card">
      <div class="work-item-top">
        <span class="item-id">${escapeHtml(task.stable_id)}</span>
        ${task.status ? `<span class="badge ${statusClass(task.status)}">${escapeHtml(task.status)}</span>` : ''}
      </div>
      <h3 class="work-item-title">${escapeHtml(task.title)}</h3>
      ${summary && summary !== task.title ? `<p class="work-item-summary">${escapeHtml(summary)}</p>` : ''}
      ${meta ? `<p class="muted work-item-meta">${escapeHtml(meta)}</p>` : ''}
    </article>
  `;
}

function renderRunFocusPanel(status: TaplStatus, taskCounts: Record<string, number>): string {
  const currentPlan = status.plans[0];
  const blockedTasks = status.tasks.filter((task) => task.status === 'Blocked');
  const latestFinding = status.findings[0];
  const nextTask = status.tasks.find((task) => task.status === 'In Progress')
    ?? status.tasks.find((task) => task.status === 'Pending');

  return `
    <section class="panel rail-panel">
      <div class="section-heading compact-heading">
        <div>
          <p class="eyebrow">Focus</p>
          <h2>Run health</h2>
        </div>
      </div>
      <div class="focus-list">
        ${renderFocusRow('Current plan', currentPlan ? currentPlan.title : 'No plan records', currentPlan?.stable_id)}
        ${renderFocusRow('Next work', nextTask ? nextTask.title : 'No active task', nextTask?.stable_id)}
        ${renderFocusRow('Blocked', `${taskCounts.Blocked ?? blockedTasks.length} work items`, blockedTasks[0]?.title)}
        ${renderFocusRow('Latest finding', latestFinding ? latestFinding.title : 'No findings', latestFinding?.stable_id)}
      </div>
    </section>
  `;
}

function renderFocusRow(label: string, value: string, detail?: string): string {
  return `
    <div class="focus-row">
      <span class="detail-label">${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${detail ? `<small>${escapeHtml(detail)}</small>` : ''}
    </div>
  `;
}

function renderItem(item: TaplItem): string {
  return `
    <article class="item">
      <div class="item-head">
        <span class="item-id">${escapeHtml(item.stable_id)}</span>
        ${item.status ? `<span class="badge ${statusClass(item.status)}">${escapeHtml(item.status)}</span>` : ''}
      </div>
      <h3 class="item-title">${escapeHtml(item.title)}</h3>
      ${item.body ? renderReadableBlock(item.body, 'item-body') : ''}
    </article>
  `;
}

function renderEvent(event: TaplEvent): string {
  const tool = event.tool_name ? ` ${event.tool_name}` : '';
  return `
    <article class="item compact">
      <div class="item-head">
        <strong>${escapeHtml(event.event_type)}${escapeHtml(tool)}</strong>
        <span class="badge">${escapeHtml(event.mode)}</span>
      </div>
      ${event.message ? `<p>${escapeHtml(event.message)}</p>` : '<p class="muted">recorded</p>'}
      <p class="muted">${escapeHtml(formatTimestamp(event.created_at))}</p>
    </article>
  `;
}

function renderArchiveSummary(archive: TaplArchive): string {
  const summary = conciseText(archive.summary || 'No summary', 140);
  return `
    <button class="item item-button compact" data-command="openArchive" data-archive-id="${escapeAttribute(archive.id)}">
      <span class="item-head">
        <strong>${escapeHtml(archive.slug)}</strong>
      </span>
      <span class="archive-summary">${escapeHtml(summary)}</span>
      <span class="archive-time">${escapeHtml(formatTimestamp(archive.created_at))}</span>
    </button>
  `;
}

function renderSearchView(payload: TaplSearchPayload): string {
  const results = payload.results.length
    ? payload.results.map(renderSearchResult).join('')
    : `<p class="muted">No results for ${escapeHtml(payload.query)}.</p>`;

  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">${escapeHtml(payload.mode)} search</p>
        <h1>Search Results</h1>
      </div>
      <div class="top-actions">
        <button data-command="back">Back</button>
        <form id="search-form" class="top-search">
          <input id="search-query" value="${escapeAttribute(payload.query)}" placeholder="Search workflow history" aria-label="Search workflow history" />
          <button type="submit">Search</button>
        </form>
      </div>
    </header>
    <main class="single">
      <section class="panel">
        <h2>${escapeHtml(payload.query)}</h2>
        ${results}
      </section>
    </main>
  `;
}

function renderSearchResult(result: TaplSearchResult): string {
  const body = `
    <span class="item-head">
      <strong class="search-title"><span class="item-id">${escapeHtml(result.stable_id)}</span> ${escapeHtml(result.title)}</strong>
      <span class="badge">${escapeHtml(result.kind)}</span>
    </span>
    ${result.status ? `<span class="muted">${escapeHtml(result.status)}</span>` : ''}
    ${result.snippet ? `<span class="snippet">${escapeHtml(conciseText(result.snippet, 180))}</span>` : ''}
    <span class="muted">${escapeHtml(result.search_source)}${result.source ? ` - ${escapeHtml(result.source)}` : ''}</span>
  `;

  if (typeof result.id !== 'number') {
    return `<article class="item compact">${body}</article>`;
  }

  return `
    <button class="item item-button compact" data-command="openSearchResult" data-item-id="${escapeAttribute(result.id)}">
      ${body}
    </button>
  `;
}

function renderSearchItemView(result: TaplSearchResult, detail?: TaplItemDetail): string {
  const title = detail?.title ?? result.title;
  const status = detail?.status ?? result.status;
  const content = detail?.body || detail?.raw_text || result.snippet || '';

  return `
    <header class="topbar">
      <div>
        <p class="eyebrow">${escapeHtml(detail?.kind ?? result.kind)} ${escapeHtml(detail?.stable_id ?? result.stable_id)}</p>
        <h1>${escapeHtml(title)}</h1>
      </div>
      <button data-command="back">Back</button>
    </header>
    <main class="single">
      <section class="panel">
        <h2>Details</h2>
        <div class="detail-list">
          ${renderDetailField('Status', status)}
          ${renderDetailField('Run', detail?.run_slug)}
          ${renderDetailField('Run status', detail?.run_status)}
          ${renderDetailField('Source', detail?.source ?? result.source)}
          ${renderDetailField('Archive', detail?.archive_slug)}
          ${renderDetailField('Search source', result.search_source)}
        </div>
        ${detail?.archive_id ? `<button data-command="openArchive" data-archive-id="${escapeAttribute(detail.archive_id)}">Open Archive</button>` : ''}
      </section>
      ${content ? `
        <section class="panel">
          <h2>Content</h2>
          ${renderReadableBlock(content, 'content-body')}
        </section>
      ` : ''}
      ${detail ? renderItemMetadata(detail) : ''}
    </main>
  `;
}

function renderItemMetadata(item: TaplItemDetail): string {
  const executionFields: [string, unknown][] = [
    ['Spec', item.spec_id],
    ['Goal', item.goal],
    ['Action', item.action],
    ['Required Subagent', item.required_subagent],
    ['Verification', item.verification],
    ['Result', item.result],
    ['Blocker', item.blocker],
    ['Next Action', item.next_action]
  ];
  const auditFields: [string, unknown][] = [
    ['Related IDs', item.related_ids],
    ['Impact', item.impact],
    ['Request', item.request_summary],
    ['Updated', formatTimestamp(item.updated_at)],
    ['Archived at', formatTimestamp(item.archive_created_at)]
  ];
  const executionRows = renderDetailRows(executionFields);
  const auditRows = renderDetailRows(auditFields);
  if (!executionRows && !auditRows) {
    return '';
  }
  return [
    executionRows ? `
    <section class="panel">
      <h2>Execution</h2>
      <div class="detail-list">${executionRows}</div>
    </section>
    ` : '',
    auditRows ? `
    <section class="panel">
      <h2>Audit</h2>
      <div class="detail-list">${auditRows}</div>
    </section>
    ` : ''
  ].join('');
}

function renderDetailRows(fields: [string, unknown][]): string {
  return fields.map(([label, value]) => renderDetailField(label, value)).join('');
}

function renderDetailField(label: string, value: unknown): string {
  if (value === undefined || value === null || value === '') {
    return '';
  }
  return `
    <div class="detail-row">
      <span class="detail-label">${escapeHtml(label)}</span>
      <div class="detail-value">${escapeHtml(value)}</div>
    </div>
  `;
}

function renderReadableBlock(content: unknown, extraClass = ''): string {
  const classes = ['reading-body', 'markdown-body', extraClass].filter(Boolean).join(' ');
  return `<div class="${classes}">${renderMarkdownBody(content)}</div>`;
}

function renderMarkdownBody(content: unknown): string {
  const html: string[] = [];
  let paragraph: string[] = [];
  let list: { kind: 'ul' | 'ol'; items: string[] } | undefined;
  let quote: string[] = [];
  let codeLines: string[] | undefined;

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    html.push(renderMarkdownParagraph(paragraph));
    paragraph = [];
  };
  const flushList = () => {
    if (!list) {
      return;
    }
    html.push(`<${list.kind}>${list.items.map((item) => `<li>${renderMarkdownLine(item)}</li>`).join('')}</${list.kind}>`);
    list = undefined;
  };
  const flushQuote = () => {
    if (!quote.length) {
      return;
    }
    html.push(`<blockquote>${quote.map((line) => `<p>${renderMarkdownLine(line)}</p>`).join('')}</blockquote>`);
    quote = [];
  };
  const flushFlow = () => {
    flushParagraph();
    flushList();
    flushQuote();
  };

  for (const rawLine of String(content ?? '').split(/\r\n|\n|\r/)) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (codeLines) {
      if (/^```/.test(trimmed)) {
        html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
        codeLines = undefined;
      } else {
        codeLines.push(rawLine);
      }
      continue;
    }

    if (/^```/.test(trimmed)) {
      flushFlow();
      codeLines = [];
      continue;
    }

    if (!trimmed) {
      flushFlow();
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (heading) {
      flushFlow();
      const level = Math.min(6, heading[1].length + 2);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2].trim())}</h${level}>`);
      continue;
    }

    const quoteMatch = trimmed.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      quote.push(quoteMatch[1].trim());
      continue;
    }

    const unordered = trimmed.match(/^[-*+]\s+(.+)$/);
    const ordered = trimmed.match(/^\d+[.)]\s+(.+)$/);
    if (unordered || ordered) {
      flushParagraph();
      flushQuote();
      const kind = unordered ? 'ul' : 'ol';
      if (list && list.kind !== kind) {
        flushList();
      }
      list ??= { kind, items: [] };
      list.items.push((unordered?.[1] ?? ordered?.[1] ?? '').trim());
      continue;
    }

    flushList();
    flushQuote();
    paragraph.push(trimmed);
  }

  if (codeLines) {
    html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
  }
  flushFlow();
  return html.join('') || '<p class="muted">Not recorded.</p>';
}

function renderMarkdownParagraph(lines: string[]): string {
  const labeledRuns = lines.map(parseMarkdownLabelRuns);
  if (labeledRuns.every(Boolean)) {
    return renderMarkdownFieldList(labeledRuns.flatMap((runs) => runs ?? []));
  }
  return `<p>${lines.map(renderMarkdownLine).join('<br>')}</p>`;
}

function parseMarkdownLabelRuns(line: string): MarkdownLabelRun[] | undefined {
  READABLE_BLOCK_LABEL_PATTERN.lastIndex = 0;
  const matches = Array.from(line.matchAll(READABLE_BLOCK_LABEL_PATTERN));
  if (!matches.length) {
    return undefined;
  }

  const firstIndex = matches[0].index ?? 0;
  if (line.slice(0, firstIndex).trim()) {
    return undefined;
  }

  const runs = matches.map((match, index) => {
    const next = matches[index + 1];
    const valueStart = (match.index ?? 0) + match[0].length;
    const valueEnd = next?.index ?? line.length;
    return {
      label: normalizeMarkdownLabel(match[1]),
      value: line.slice(valueStart, valueEnd).trim()
    };
  });

  return runs.length ? runs : undefined;
}

function renderMarkdownFieldList(runs: MarkdownLabelRun[]): string {
  return `
    <div class="markdown-field-list">
      ${runs.map((run) => `
        <div class="markdown-field-row">
          <span class="markdown-label">${escapeHtml(run.label)}:</span>
          <span class="markdown-field-value">${run.value ? renderInlineMarkdown(run.value) : '<span class="muted">Not recorded.</span>'}</span>
        </div>
      `).join('')}
    </div>
  `;
}

function renderMarkdownLine(line: string): string {
  const labeled = line.match(/^([A-Za-z가-힣][A-Za-z0-9가-힣 /_-]*|REQ-\d+):\s*(.*)$/i);
  if (!labeled || !isReadableBlockKey(labeled[1])) {
    return renderInlineMarkdown(line);
  }
  return `<span class="markdown-label">${escapeHtml(normalizeMarkdownLabel(labeled[1]))}:</span> ${renderInlineMarkdown(labeled[2])}`;
}

function renderInlineMarkdown(value: string): string {
  return value
    .split(/(`[^`]+`)/g)
    .map((segment) => {
      if (segment.startsWith('`') && segment.endsWith('`') && segment.length > 1) {
        return `<code>${escapeHtml(segment.slice(1, -1))}</code>`;
      }
      return escapeHtml(segment)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/__([^_]+)__/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>')
        .replace(/_([^_]+)_/g, '<em>$1</em>');
    })
    .join('');
}

function normalizeMarkdownLabel(label: string): string {
  return label.trim().replace(/\s+/g, ' ');
}

function isReadableBlockKey(label: string): boolean {
  if (/^REQ-\d+$/i.test(label)) {
    return true;
  }
  return READABLE_BLOCK_KEY_LABELS.has(label.trim().toLowerCase().replace(/\s+/g, ' '));
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function renderError(message: string): string {
  return `
    <main class="single">
      <section class="panel error">
        <h1>tapl unavailable</h1>
        <p>${escapeHtml(message)}</p>
      </section>
    </main>
  `;
}

function metric(label: string, value: string, detail: string): string {
  return `
    <article class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </article>
  `;
}

function pill(label: string, value: number | undefined): string {
  return `<span class="pill ${statusClass(label)}">${escapeHtml(label)} ${value ?? 0}</span>`;
}

function countTaskStatuses(tasks: TaplItem[]): Record<string, number> {
  const counts = { ...DEFAULT_STATUS.task_counts };
  for (const task of tasks) {
    if (task.status) {
      counts[task.status] = (counts[task.status] ?? 0) + 1;
    }
  }
  return counts;
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

function statusClass(status: string): string {
  return status.toLowerCase().replace(/\s+/g, '-');
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

async function safeTapl(args: string[]): Promise<{ ok: true; value: TaplStatus } | { ok: false; error: string }> {
  const result = await runTapl(args);
  if (!result.ok) {
    return result;
  }
  try {
    return { ok: true, value: { ...DEFAULT_STATUS, ...JSON.parse(result.value.stdout) } };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse taplctl JSON.' };
  }
}

async function safeArchives(limit?: number): Promise<{ ok: true; value: TaplArchive[] } | { ok: false; error: string }> {
  const args = ['archive', 'list', '--json'];
  if (limit !== undefined) {
    args.push('--limit', String(limit));
  }
  const result = await runTapl(args);
  if (!result.ok) {
    return result;
  }
  try {
    const payload = JSON.parse(result.value.stdout) as { archives?: TaplArchive[] };
    return { ok: true, value: payload.archives ?? [] };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl archive JSON.' };
  }
}

async function safeArchiveDetail(archiveId: string): Promise<{ ok: true; value: TaplArchiveDetail } | { ok: false; error: string }> {
  const result = await runTapl(['archive', 'show', '--id', archiveId, '--json']);
  if (!result.ok) {
    return result;
  }
  try {
    const payload = JSON.parse(result.value.stdout) as {
      ok?: boolean;
      error?: string;
      archive?: TaplArchive;
      items?: TaplItem[];
      events?: TaplEvent[];
    };
    if (payload.ok === false) {
      return { ok: false, error: payload.error ?? 'Failed to load tapl archive detail.' };
    }
    if (!payload.archive) {
      return { ok: false, error: 'tapl archive detail response did not include an archive.' };
    }
    return {
      ok: true,
      value: {
        archive: payload.archive,
        items: payload.items ?? [],
        events: payload.events ?? []
      }
    };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl archive detail JSON.' };
  }
}

async function safeItemDetail(itemId: number): Promise<{ ok: true; value: TaplItemDetail } | { ok: false; error: string }> {
  const result = await runTapl(['item', 'show', '--id', String(itemId), '--json']);
  if (!result.ok) {
    return result;
  }
  try {
    const payload = JSON.parse(result.value.stdout) as {
      ok?: boolean;
      error?: string;
      item?: TaplItemDetail;
    };
    if (payload.ok === false) {
      return { ok: false, error: payload.error ?? 'Failed to load tapl item detail.' };
    }
    if (!payload.item) {
      return { ok: false, error: 'tapl item detail response did not include an item.' };
    }
    return { ok: true, value: payload.item };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl item detail JSON.' };
  }
}

async function searchTapl(query: string): Promise<{ ok: true; value: TaplSearchPayload } | { ok: false; error: string }> {
  const result = await runTapl(['search', query, '--json']);
  if (!result.ok) {
    return result;
  }
  try {
    return { ok: true, value: JSON.parse(result.value.stdout) as TaplSearchPayload };
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl search JSON.' };
  }
}

async function runTapl(args: string[]): Promise<{ ok: true; value: ExecResult } | { ok: false; error: string }> {
  const root = getWorkspaceRoot();
  if (!root) {
    return { ok: false, error: 'Open a workspace folder to use tapl.' };
  }

  const commands = taplctlCommandCandidates();
  const failures: string[] = [];
  for (const command of commands) {
    const result = await execFile(command, args, root.uri.fsPath);
    if (result.ok) {
      return result;
    }
    failures.push(`${command}: ${result.error}`);
    if (!result.commandNotFound) {
      return { ok: false, error: `taplctl failed using ${command}: ${result.error}` };
    }
  }

  return {
    ok: false,
    error: [
      'Unable to execute taplctl.',
      `Tried: ${commands.join(', ')}.`,
      `Set ${COMMAND_PREFIX}.${TAPLCTL_PATH_SETTING} to the full taplctl path if it is installed elsewhere.`,
      failures.length ? `Last error: ${failures[failures.length - 1]}` : ''
    ].filter(Boolean).join(' ')
  };
}

function taplctlCommandCandidates(): string[] {
  const configured = vscode.workspace
    .getConfiguration(COMMAND_PREFIX)
    .get<string>(TAPLCTL_PATH_SETTING, '')
    .trim();
  return uniqueStrings([
    configured || undefined,
    ...COMMON_TAPLCTL_COMMANDS
  ]);
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    if (!value || seen.has(value)) {
      continue;
    }
    seen.add(value);
    result.push(value);
  }
  return result;
}

function taplctlExecutionEnv(): Record<string, string | undefined> {
  const delimiter = process.platform === 'win32' ? ';' : ':';
  const pathValue = [
    process.env.PATH,
    '/opt/homebrew/bin',
    '/usr/local/bin'
  ].filter(Boolean).join(delimiter);
  return {
    ...process.env,
    PATH: pathValue
  };
}

function execFile(command: string, args: string[], cwd: string): Promise<{ ok: true; value: ExecResult } | { ok: false; error: string; commandNotFound: boolean }> {
  return new Promise((resolve) => {
    childProcess.execFile(command, args, { cwd, timeout: 10000, env: taplctlExecutionEnv() }, (error, stdout, stderr) => {
      if (error) {
        resolve({ ok: false, error: stderr || error.message, commandNotFound: isCommandNotFound(error) });
        return;
      }
      resolve({ ok: true, value: { stdout, stderr } });
    });
  });
}

function isCommandNotFound(error: Error): boolean {
  return (error as Error & { code?: string }).code === 'ENOENT';
}

function getWorkspaceRoot(): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.workspaceFolders?.[0];
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

function renderPage(webview: vscode.Webview, body: string, viewKey: string): string {
  const nonce = createNonce(viewKey);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'unsafe-inline'; script-src 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    :root {
      color-scheme: light dark;
      --bg: var(--vscode-editor-background);
      --fg: var(--vscode-editor-foreground);
      --muted: var(--vscode-descriptionForeground);
      --border: var(--vscode-panel-border);
      --panel: var(--vscode-sideBar-background);
      --surface: var(--vscode-editorWidget-background, var(--panel));
      --surface-muted: var(--vscode-input-background, var(--surface));
      --accent: var(--vscode-focusBorder);
      --error: var(--vscode-errorForeground);
      --success: var(--vscode-testing-iconPassed, #4e9a06);
      --warning: var(--vscode-editorWarning-foreground, #cca700);
      --info: var(--vscode-symbolIcon-eventForeground, var(--accent));
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: var(--vscode-font-family);
      color: var(--fg);
      background: var(--bg);
      line-height: 1.5;
    }
    button, input {
      font: inherit;
      color: inherit;
      background: var(--vscode-input-background);
      border: 1px solid var(--vscode-input-border, var(--border));
      border-radius: 4px;
      padding: 7px 10px;
    }
    button {
      cursor: pointer;
      background: var(--vscode-button-background);
      color: var(--vscode-button-foreground);
      border-color: transparent;
    }
    button:focus-visible, input:focus-visible, .workflow-tab:focus-visible, .item-button:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 {
      font-size: 26px;
      line-height: 1.2;
      margin-bottom: 0;
    }
    h2 {
      font-size: 14px;
      line-height: 1.35;
      margin-bottom: 12px;
    }
    h3 {
      font-size: 14px;
      line-height: 1.4;
      margin-bottom: 8px;
    }
    h4, h5, h6 {
      font-size: 13px;
      line-height: 1.4;
      margin: 0;
    }
    h1, h2, h3, h4, h5, h6, p, small, pre, code, li, .archive-summary, .archive-time, .item-head strong, .item-id, .snippet, .detail-value, .work-item-title, .work-item-summary, .focus-row strong, .markdown-label {
      min-width: 0;
      max-width: 100%;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    pre {
      white-space: pre-wrap;
      margin: 0;
      color: var(--fg);
      font-family: var(--vscode-font-family);
      font-size: 13px;
      line-height: 1.65;
      tab-size: 2;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 20px;
    }
    .workspace-hero {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 420px);
      gap: 20px;
      align-items: start;
      margin-bottom: 18px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
    .workspace-heading {
      min-width: 0;
    }
    .workspace-summary {
      max-width: 82ch;
      margin: 10px 0 12px;
      color: var(--muted);
    }
    .workspace-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-width: 0;
    }
    .top-actions {
      display: grid;
      justify-items: end;
      gap: 8px;
      min-width: min(420px, 100%);
    }
    .eyebrow, .muted, small {
      color: var(--muted);
      font-size: 12px;
    }
    .metrics, .status-strip {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .insight-grid {
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      margin-bottom: 18px;
    }
    .metric, .panel {
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--surface);
      min-width: 0;
    }
    .metric {
      padding: 12px;
      display: grid;
      gap: 4px;
    }
    .metric strong {
      font-size: 20px;
      line-height: 1.2;
    }
    .status-strip {
      display: flex;
      flex-wrap: wrap;
    }
    .pill, .badge {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      min-height: 22px;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
    }
    .completed { color: var(--success); }
    .blocked, .error { color: var(--error); }
    .in-progress { color: var(--accent); }
    .pending { color: var(--warning); }
    .skipped { color: var(--muted); }
    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
      gap: 14px;
      align-items: start;
    }
    .dashboard-main, .dashboard-rail {
      display: grid;
      gap: 14px;
      min-width: 0;
    }
    .board-section {
      min-width: 0;
    }
    .section-heading {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 12px;
      min-width: 0;
      margin-bottom: 10px;
    }
    .section-heading h2 {
      margin-bottom: 0;
    }
    .compact-heading {
      margin-bottom: 12px;
    }
    .task-board {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      align-items: start;
      min-width: 0;
    }
    .task-lane {
      --lane-accent: var(--border);
      display: grid;
      align-content: start;
      min-width: 0;
      min-height: 180px;
      border: 1px solid var(--border);
      border-top: 2px solid var(--lane-accent);
      border-radius: 6px;
      background: var(--surface);
    }
    .task-status-pending { --lane-accent: var(--warning); }
    .task-status-in-progress { --lane-accent: var(--accent); }
    .task-status-blocked { --lane-accent: var(--error); }
    .task-status-completed { --lane-accent: var(--success); }
    .task-status-skipped { --lane-accent: var(--muted); }
    .lane-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 10px 8px;
      border-bottom: 1px solid var(--border);
      min-width: 0;
    }
    .lane-label {
      font-size: 12px;
      font-weight: 700;
    }
    .lane-count {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 20px;
      min-height: 20px;
      margin-left: 6px;
      padding: 0 6px;
      border-radius: 999px;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      font-size: 11px;
    }
    .lane-list {
      display: grid;
      gap: 8px;
      padding: 10px;
      min-width: 0;
    }
    .lane-empty, .lane-more {
      margin: 0;
    }
    .work-item-card {
      display: grid;
      gap: 6px;
      min-width: 0;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--bg);
    }
    .work-item-top {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: flex-start;
      min-width: 0;
    }
    .work-item-title {
      margin: 0;
      font-size: 13px;
      line-height: 1.35;
    }
    .work-item-summary {
      margin: 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .work-item-meta {
      margin: 0;
    }
    .saved-views, .rail-panel {
      min-width: 0;
    }
    .saved-view-panel {
      min-width: 0;
      padding-top: 4px;
    }
    .saved-view-panel[hidden] {
      display: none;
    }
    .focus-list {
      display: grid;
      gap: 10px;
    }
    .focus-row {
      display: grid;
      gap: 2px;
      min-width: 0;
      padding-top: 10px;
      border-top: 1px solid var(--border);
    }
    .focus-row:first-child {
      padding-top: 0;
      border-top: 0;
    }
    .focus-row strong {
      min-width: 0;
      overflow-wrap: anywhere;
      font-size: 13px;
      line-height: 1.35;
    }
    .workflow-tabs {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 0 0 12px;
    }
    .workflow-tab {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      background: var(--vscode-button-secondaryBackground, var(--panel));
      color: var(--vscode-button-secondaryForeground, var(--fg));
      border: 1px solid var(--border);
    }
    .workflow-tab[aria-selected="true"] {
      border-color: var(--accent);
      background: var(--panel);
      box-shadow: inset 0 -2px 0 var(--accent);
    }
    .workflow-tab-count {
      display: inline-flex;
      align-items: center;
      min-height: 18px;
      padding: 0 6px;
      border-radius: 999px;
      background: var(--vscode-badge-background);
      color: var(--vscode-badge-foreground);
      font-size: 11px;
    }
    .workflow-tab-panel[hidden] {
      display: none;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(320px, 0.7fr);
      gap: 12px;
    }
    .side-stack {
      display: grid;
      align-content: start;
      gap: 12px;
    }
    .single { max-width: 900px; }
    .panel {
      padding: 16px;
      min-width: 0;
    }
    .item {
      padding: 14px 0 0;
      margin-top: 14px;
      border-top: 1px solid var(--border);
      background: transparent;
      min-width: 0;
    }
    .panel > h2 + .item {
      padding-top: 0;
      margin-top: 0;
      border-top: 0;
    }
    .item-button {
      display: block;
      width: 100%;
      text-align: left;
      background: transparent;
      color: var(--fg);
      border: 1px solid transparent;
      border-top-color: var(--border);
      border-radius: 4px;
      cursor: pointer;
      padding: 12px 10px;
    }
    .item-button:hover, .item-button:focus-visible {
      border-color: var(--accent);
      background: var(--vscode-list-hoverBackground, transparent);
    }
    .archive-summary {
      display: block;
      margin-top: 4px;
      min-width: 0;
      line-height: 1.5;
    }
    .archive-time {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 12px;
    }
    .item.compact p { margin-bottom: 4px; }
    .item-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 8px;
      min-width: 0;
    }
    .item-id {
      color: var(--muted);
      font-family: var(--vscode-editor-font-family, var(--vscode-font-family));
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0;
    }
    .item-title {
      color: var(--fg);
      font-weight: 600;
    }
    .search-title {
      line-height: 1.4;
      font-weight: 600;
    }
    .snippet {
      display: block;
      margin-top: 6px;
      max-width: 78ch;
      color: var(--fg);
      line-height: 1.55;
    }
    .markdown-body {
      display: grid;
      gap: 8px;
      max-width: 82ch;
      margin-top: 10px;
      min-width: 0;
    }
    .markdown-body h3,
    .markdown-body h4,
    .markdown-body h5,
    .markdown-body h6 {
      color: var(--fg);
      font-weight: 700;
      margin-top: 6px;
      padding-top: 8px;
      border-top: 1px solid var(--border);
    }
    .markdown-body h3:first-child,
    .markdown-body h4:first-child,
    .markdown-body h5:first-child,
    .markdown-body h6:first-child {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }
    .markdown-body p,
    .markdown-body ul,
    .markdown-body ol,
    .markdown-body blockquote,
    .markdown-body pre {
      margin: 0;
    }
    .markdown-body p,
    .markdown-body li {
      line-height: 1.55;
    }
    .markdown-body ul,
    .markdown-body ol {
      display: grid;
      gap: 4px;
      padding-left: 20px;
    }
    .markdown-body blockquote {
      display: grid;
      gap: 4px;
      padding: 8px 10px;
      border-left: 2px solid var(--border);
      color: var(--muted);
      background: var(--surface);
      border-radius: 4px;
    }
    .markdown-body pre {
      padding: 10px 12px;
      border: 1px solid var(--border);
      background: var(--surface-muted);
      border-radius: 4px;
      overflow-x: auto;
      font-family: var(--vscode-editor-font-family, var(--vscode-font-family));
      font-size: 12px;
      line-height: 1.55;
    }
    .markdown-body code {
      font-family: var(--vscode-editor-font-family, var(--vscode-font-family));
      font-size: 12px;
      padding: 1px 4px;
      border-radius: 3px;
      background: var(--vscode-textCodeBlock-background, var(--surface));
    }
    .markdown-body pre code {
      padding: 0;
      background: transparent;
      border-radius: 0;
    }
    .markdown-field-list {
      display: grid;
      gap: 0;
      min-width: 0;
    }
    .markdown-field-row {
      display: grid;
      grid-template-columns: minmax(86px, max-content) minmax(0, 1fr);
      gap: 10px;
      align-items: start;
      padding: 6px 0;
      border-top: 1px solid var(--border);
    }
    .markdown-field-row:first-child {
      padding-top: 0;
      border-top: 0;
    }
    .markdown-field-row:last-child {
      padding-bottom: 0;
    }
    .markdown-field-value {
      min-width: 0;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .reading-body {
      max-width: 78ch;
      margin-top: 10px;
      padding: 10px 12px;
      border-left: 2px solid var(--accent);
      border-radius: 4px;
      background: var(--surface-muted);
    }
    .content-body {
      max-width: 82ch;
      margin-top: 0;
    }
    .markdown-label {
      color: var(--vscode-symbolIcon-keywordForeground, var(--accent));
      font-weight: 700;
    }
    form {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
    }
    .top-search {
      width: min(420px, 100%);
      margin-bottom: 0;
    }
    input {
      flex: 1;
      min-width: 0;
    }
    .detail-list {
      display: grid;
      gap: 8px;
      margin-bottom: 12px;
    }
    .detail-row {
      display: grid;
      grid-template-columns: minmax(110px, 140px) minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }
    .detail-label {
      color: var(--vscode-symbolIcon-keywordForeground, var(--accent));
      font-size: 12px;
      font-weight: 700;
    }
    .detail-value {
      overflow-wrap: anywhere;
      min-width: 0;
      word-break: break-word;
      white-space: pre-wrap;
      line-height: 1.55;
      font-weight: 400;
    }
    .debug-footer {
      display: flex;
      justify-content: flex-end;
      margin-top: 16px;
    }
    @media (max-width: 900px) {
      body { padding: 16px; }
      .grid, .dashboard-grid, .workspace-hero { grid-template-columns: 1fr; }
      .task-board, .insight-grid { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
      .topbar { display: block; }
      .top-actions {
        justify-items: stretch;
        margin-top: 12px;
      }
      .top-search {
        width: 100%;
      }
      .detail-row {
        grid-template-columns: 1fr;
        gap: 2px;
      }
      .markdown-field-row {
        grid-template-columns: 1fr;
        gap: 2px;
      }
    }
    @media (max-width: 560px) {
      body { padding: 12px; }
      .task-board, .metrics, .insight-grid { grid-template-columns: 1fr; }
      form { display: grid; }
      .section-heading, .work-item-top {
        display: grid;
        justify-content: stretch;
      }
    }
  </style>
</head>
<body>
${body}
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  document.querySelectorAll('[data-command]').forEach((element) => {
    element.addEventListener('click', () => vscode.postMessage({
      command: element.dataset.command,
      archiveId: element.dataset.archiveId,
      itemId: element.dataset.itemId
    }));
  });
  const form = document.getElementById('search-form');
  if (form) {
    const input = document.getElementById('search-query');
    let searchResetTimer;
    const postSearch = () => {
      if (form.dataset.searchPosting === 'true') {
        return;
      }
      form.dataset.searchPosting = 'true';
      window.clearTimeout(searchResetTimer);
      searchResetTimer = window.setTimeout(() => {
        form.dataset.searchPosting = 'false';
      }, 300);
      vscode.postMessage({ command: 'search', query: input ? input.value : '' });
    };
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      postSearch();
    });
    if (input) {
      input.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' || event.isComposing) {
          return;
        }
        event.preventDefault();
        postSearch();
      });
    }
  }
  const workflowTabs = Array.from(document.querySelectorAll('[data-workflow-tab]'));
  const workflowPanels = Array.from(document.querySelectorAll('[data-workflow-tab-panel]'));
  const hasWorkflowTab = (tabId) => workflowTabs.some((tab) => tab.dataset.workflowTab === tabId);
  const saveWorkflowTab = (tabId) => {
    const currentState = vscode.getState();
    vscode.setState({
      ...(currentState && typeof currentState === 'object' ? currentState : {}),
      workflowTab: tabId
    });
  };
  const getStoredWorkflowTab = () => {
    const currentState = vscode.getState();
    const tabId = currentState && typeof currentState.workflowTab === 'string' ? currentState.workflowTab : '';
    return hasWorkflowTab(tabId) ? tabId : '';
  };
  const selectWorkflowTab = (tabId, options = {}) => {
    if (!hasWorkflowTab(tabId)) {
      return;
    }
    workflowTabs.forEach((tab) => {
      const selected = tab.dataset.workflowTab === tabId;
      tab.setAttribute('aria-selected', selected ? 'true' : 'false');
      tab.setAttribute('tabindex', selected ? '0' : '-1');
    });
    workflowPanels.forEach((panel) => {
      panel.hidden = panel.dataset.workflowTabPanel !== tabId;
    });
    if (options.persist !== false) {
      saveWorkflowTab(tabId);
    }
  };
  workflowTabs.forEach((tab, index) => {
    tab.addEventListener('click', () => selectWorkflowTab(tab.dataset.workflowTab));
    tab.addEventListener('keydown', (event) => {
      if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
        return;
      }
      event.preventDefault();
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const next = workflowTabs[(index + direction + workflowTabs.length) % workflowTabs.length];
      selectWorkflowTab(next.dataset.workflowTab);
      next.focus();
    });
  });
  const renderedSelectedWorkflowTab = workflowTabs.find((tab) => tab.getAttribute('aria-selected') === 'true')?.dataset.workflowTab || 'tasks';
  selectWorkflowTab(getStoredWorkflowTab() || renderedSelectedWorkflowTab, { persist: false });
</script>
</body>
</html>`;
}

function createNonce(seed: string): string {
  let value = 0;
  for (let index = 0; index < seed.length; index += 1) {
    value = (value * 31 + seed.charCodeAt(index)) >>> 0;
  }
  return `tapl${value.toString(36)}${Date.now().toString(36)}`;
}

function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttribute(value: unknown): string {
  return escapeHtml(value).replace(/`/g, '&#96;');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
