"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const childProcess = require("child_process");
const vscode = require("vscode");
const COMMAND_PREFIX = "taplWorkflow";
const TAPL_DB_WATCH_DEBOUNCE_MS = 2000;
const TAPLCTL_PATH_SETTING = "taplctlPath";
const COMMON_TAPLCTL_COMMANDS = [
    "taplctl",
    "/opt/homebrew/bin/taplctl",
    "/usr/local/bin/taplctl"
];
const DEFAULT_STATUS = {
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
    archives: [],
    recent_events: [],
    schema: {}
};
function activate(context) {
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
    context.subscriptions.push(debouncedRefresh, vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.active`, activeProvider), vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.archives`, archiveProvider), vscode.commands.registerCommand(`${COMMAND_PREFIX}.refresh`, refreshAll), vscode.commands.registerCommand(`${COMMAND_PREFIX}.openOverview`, async () => {
        await webviewManager.openOverview();
    }), vscode.commands.registerCommand(`${COMMAND_PREFIX}.openArchive`, async (node) => {
        if (node instanceof WorkflowNode && node.archive) {
            await webviewManager.openArchive(node.archive);
        }
    }), vscode.commands.registerCommand(`${COMMAND_PREFIX}.search`, async () => {
        await webviewManager.searchFromCommand();
    }));
    const root = getWorkspaceRoot();
    if (root) {
        for (const pattern of ['.tapl/tapl.db', '.tapl/tapl.db-wal', '.tapl/tapl.db-shm']) {
            const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, pattern));
            context.subscriptions.push(watcher, watcher.onDidChange(debouncedRefresh.schedule), watcher.onDidCreate(debouncedRefresh.schedule), watcher.onDidDelete(debouncedRefresh.schedule));
        }
    }
}
function deactivate() {
    // Disposables are owned by the extension context.
}
class WorkflowNode extends vscode.TreeItem {
    constructor(options) {
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
class ActiveProvider {
    constructor() {
        this.changedEmitter = new vscode.EventEmitter();
        this.onDidChangeTreeData = this.changedEmitter.event;
    }
    refresh() {
        this.changedEmitter.fire(undefined);
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
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
        const nodes = [
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
class ArchiveProvider {
    constructor() {
        this.changedEmitter = new vscode.EventEmitter();
        this.onDidChangeTreeData = this.changedEmitter.event;
    }
    refresh() {
        this.changedEmitter.fire(undefined);
    }
    getTreeItem(element) {
        return element;
    }
    async getChildren(element) {
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
    constructor() {
        this.currentView = { type: 'overview' };
        this.backStack = [];
    }
    async openOverview() {
        this.backStack.length = 0;
        await this.navigate({ type: 'overview' }, { reveal: true });
    }
    async openArchive(archive) {
        const detail = await safeArchiveDetail(archive.id);
        if (!detail.ok) {
            void vscode.window.showWarningMessage(detail.error);
        }
        await this.navigate({ type: 'archive', archive: detail.ok ? detail.value.archive : archive, detail: detail.ok ? detail.value : undefined }, { pushHistory: this.panel !== undefined, reveal: true });
    }
    async refresh() {
        if (this.panel) {
            await this.render(this.titleForView(this.currentView), { reveal: false });
        }
    }
    async searchFromCommand() {
        const query = await vscode.window.showInputBox({
            prompt: 'Search tapl workflow history',
            value: this.lastSearch?.query ?? ''
        });
        if (query === undefined) {
            return;
        }
        await this.runSearch(query, { reveal: true });
    }
    async navigate(view, options = {}) {
        if (options.pushHistory) {
            this.backStack.push(this.currentView);
        }
        this.currentView = view;
        await this.render(this.titleForView(view), { reveal: options.reveal ?? true });
    }
    async goBack() {
        const previous = this.backStack.pop() ?? { type: 'overview' };
        this.currentView = previous;
        await this.render(this.titleForView(previous), { reveal: false });
    }
    titleForView(view) {
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
    async render(title, options = {}) {
        const panel = this.ensurePanel(title, options.reveal ?? true);
        panel.title = title;
        panel.webview.html = await this.renderCurrentView(panel.webview);
    }
    ensurePanel(title, reveal) {
        if (this.panel) {
            if (reveal) {
                this.panel.reveal(vscode.ViewColumn.One);
            }
            return this.panel;
        }
        this.panel = vscode.window.createWebviewPanel('taplWorkflow.viewer', title, vscode.ViewColumn.One, {
            enableScripts: true,
            retainContextWhenHidden: false
        });
        this.panel.webview.onDidReceiveMessage((message) => {
            void this.handleMessage(message);
        });
        this.panel.onDidDispose(() => {
            this.panel = undefined;
        });
        return this.panel;
    }
    async renderCurrentView(webview) {
        if (this.currentView.type === 'archive') {
            return renderPage(webview, renderArchiveView(this.currentView.archive, this.currentView.detail), `archive:${this.currentView.archive.id}`);
        }
        if (this.currentView.type === 'search') {
            return renderPage(webview, renderSearchView(this.currentView.search), `search:${this.currentView.search.query}`);
        }
        if (this.currentView.type === 'searchItem') {
            return renderPage(webview, renderSearchItemView(this.currentView.result, this.currentView.detail), `search-item:${this.currentView.result.id ?? this.currentView.result.stable_id}`);
        }
        if (this.currentView.type === 'debug') {
            const status = await safeTapl(['status', '--json']);
            if (!status.ok) {
                return renderPage(webview, renderError(status.error), 'error');
            }
            return renderPage(webview, renderDebugView(status.value), 'debug');
        }
        const status = await safeTapl(['status', '--json']);
        if (!status.ok) {
            return renderPage(webview, renderError(status.error), 'error');
        }
        return renderPage(webview, renderOverview(status.value, this.lastSearch?.query ?? ''), 'overview');
    }
    async handleMessage(message) {
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
    async runSearch(query, options = {}) {
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
        await this.navigate({ type: 'search', search }, { pushHistory: options.pushHistory ?? this.currentView.type !== 'search', reveal: options.reveal ?? false });
    }
    async openSearchResult(rawItemId) {
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
    searchResultForItemId(itemId) {
        if (this.currentView.type === 'search') {
            return this.currentView.search.results.find((result) => result.id === itemId);
        }
        return this.lastSearch?.results.find((result) => result.id === itemId);
    }
    async openArchiveById(archiveId) {
        const detail = await safeArchiveDetail(archiveId);
        if (detail.ok) {
            await this.navigate({ type: 'archive', archive: detail.value.archive, detail: detail.value }, { pushHistory: true, reveal: false });
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
function renderOverview(status, searchQuery = '') {
    const taskCounts = status.task_counts || DEFAULT_STATUS.task_counts;
    const activeSummary = status.active_run
        ? String(status.active_run.request_summary || status.active_run.slug || 'active')
        : 'No active run';
    const workflowTabs = [
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
    <header class="topbar">
      <div>
        <p class="eyebrow">${escapeHtml(getWorkspaceRoot()?.name ?? 'workspace')}</p>
        <h1>tapl Workflow</h1>
      </div>
      <div class="top-actions">
        <button data-command="refresh">Refresh</button>
        <form id="search-form" class="top-search">
          <input id="search-query" value="${escapeAttribute(searchQuery)}" placeholder="Search workflow history" />
          <button type="submit">Search</button>
        </form>
      </div>
    </header>
    <section class="metrics">
      ${metric('Active', status.active_run ? 'Yes' : 'No', activeSummary)}
      ${metric('Tasks', String(status.tasks.length), `${status.incomplete_tasks} incomplete`)}
      ${metric('Archives', String(status.archives.length), 'stored in tapl DB')}
      ${metric('Search', status.schema.embedding_model ? 'Ready' : 'FTS', status.schema.embedding_model || 'keyword fallback')}
    </section>
    <section class="status-strip">
      ${pill('Pending', taskCounts.Pending)}
      ${pill('In Progress', taskCounts['In Progress'])}
      ${pill('Completed', taskCounts.Completed)}
      ${pill('Blocked', taskCounts.Blocked)}
      ${pill('Skipped', taskCounts.Skipped)}
    </section>
    <section class="workflow-tabs" role="tablist" aria-label="Workflow records">
      ${workflowTabs.map(renderWorkflowTabButton).join('')}
    </section>
    <main class="grid">
      ${workflowTabs.map(renderWorkflowTabPanel).join('')}
      <section class="panel">
        <h2>Archives</h2>
        ${status.archives.length ? status.archives.map(renderArchiveSummary).join('') : '<p class="muted">No archives.</p>'}
      </section>
    </main>
    <footer class="debug-footer">
      <button data-command="debug">Debug</button>
    </footer>
  `;
}
function renderWorkflowTabButton(tab) {
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
function renderWorkflowTabPanel(tab) {
    return `
    <section
      id="workflow-tab-panel-${escapeAttribute(tab.id)}"
      class="panel workflow-tab-panel"
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
function renderArchiveView(archive, detail) {
    const archiveMeta = detail?.archive ?? archive;
    const items = detail?.items ?? [];
    const plans = items.filter((item) => item.kind === 'plan');
    const tasks = items.filter((item) => item.kind === 'task');
    const findings = items.filter((item) => item.kind === 'finding');
    const otherItems = items.filter((item) => !['plan', 'task', 'finding'].includes(item.kind));
    const taskCounts = countTaskStatuses(tasks);
    const workflowTabs = [
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
      ${workflowTabs.map(renderWorkflowTabPanel).join('')}
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
function renderArchiveInfoPanel(archive) {
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
function renderArchiveOtherRecordsPanel(items) {
    return `
    <section class="panel">
      <h2>Other Records</h2>
      ${items.length ? items.map(renderItem).join('') : '<p class="muted">No other archived records.</p>'}
    </section>
  `;
}
function renderArchiveUnavailablePanel() {
    return `
    <section class="panel">
      <h2>Details</h2>
      <p class="muted">Detailed archive data unavailable.</p>
    </section>
  `;
}
function renderDebugView(status) {
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
function renderItem(item) {
    return `
    <article class="item">
      <div class="item-head">
        <strong>${escapeHtml(item.stable_id)}</strong>
        ${item.status ? `<span class="badge ${statusClass(item.status)}">${escapeHtml(item.status)}</span>` : ''}
      </div>
      <h3>${escapeHtml(item.title)}</h3>
      ${item.body ? `<pre>${escapeHtml(item.body)}</pre>` : ''}
    </article>
  `;
}
function renderEvent(event) {
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
function renderArchiveSummary(archive) {
    return `
    <button class="item item-button compact" data-command="openArchive" data-archive-id="${escapeAttribute(archive.id)}">
      <span class="item-head">
        <strong>${escapeHtml(archive.slug)}</strong>
      </span>
      <span class="archive-summary">${escapeHtml(archive.summary || 'No summary')}</span>
      <span class="archive-time">${escapeHtml(formatTimestamp(archive.created_at))}</span>
    </button>
  `;
}
function renderSearchView(payload) {
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
          <input id="search-query" value="${escapeAttribute(payload.query)}" placeholder="Search workflow history" />
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
function renderSearchResult(result) {
    const body = `
    <span class="item-head">
      <strong>${escapeHtml(result.stable_id)} ${escapeHtml(result.title)}</strong>
      <span class="badge">${escapeHtml(result.kind)}</span>
    </span>
    ${result.status ? `<span class="muted">${escapeHtml(result.status)}</span>` : ''}
    ${result.snippet ? `<span class="archive-summary">${escapeHtml(result.snippet)}</span>` : ''}
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
function renderSearchItemView(result, detail) {
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
          <pre>${escapeHtml(content)}</pre>
        </section>
      ` : ''}
      ${detail ? renderItemMetadata(detail) : ''}
    </main>
  `;
}
function renderItemMetadata(item) {
    const fields = [
        ['Spec', item.spec_id],
        ['Goal', item.goal],
        ['Action', item.action],
        ['Required Subagent', item.required_subagent],
        ['Verification', item.verification],
        ['Result', item.result],
        ['Blocker', item.blocker],
        ['Next Action', item.next_action],
        ['Related IDs', item.related_ids],
        ['Impact', item.impact],
        ['Request', item.request_summary],
        ['Updated', formatTimestamp(item.updated_at)],
        ['Archived at', formatTimestamp(item.archive_created_at)]
    ];
    const rows = fields.map(([label, value]) => renderDetailField(label, value)).join('');
    if (!rows) {
        return '';
    }
    return `
    <section class="panel">
      <h2>Metadata</h2>
      <div class="detail-list">${rows}</div>
    </section>
  `;
}
function renderDetailField(label, value) {
    if (value === undefined || value === null || value === '') {
        return '';
    }
    return `
    <div class="detail-row">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
    </div>
  `;
}
function renderError(message) {
    return `
    <main class="single">
      <section class="panel error">
        <h1>tapl unavailable</h1>
        <p>${escapeHtml(message)}</p>
      </section>
    </main>
  `;
}
function metric(label, value, detail) {
    return `
    <article class="metric">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </article>
  `;
}
function pill(label, value) {
    return `<span class="pill ${statusClass(label)}">${escapeHtml(label)} ${value ?? 0}</span>`;
}
function countTaskStatuses(tasks) {
    const counts = { ...DEFAULT_STATUS.task_counts };
    for (const task of tasks) {
        if (task.status) {
            counts[task.status] = (counts[task.status] ?? 0) + 1;
        }
    }
    return counts;
}
function iconForStatus(status) {
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
function statusClass(status) {
    return status.toLowerCase().replace(/\s+/g, '-');
}
function formatTimestamp(value) {
    const raw = String(value ?? '');
    if (!raw) {
        return '';
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) {
        return raw;
    }
    const twoDigits = (part) => String(part).padStart(2, '0');
    return [
        `${twoDigits(date.getFullYear() % 100)}-${twoDigits(date.getMonth() + 1)}-${twoDigits(date.getDate())}`,
        `${twoDigits(date.getHours())}:${twoDigits(date.getMinutes())}:${twoDigits(date.getSeconds())}`
    ].join(' ');
}
async function safeTapl(args) {
    const result = await runTapl(args);
    if (!result.ok) {
        return result;
    }
    try {
        return { ok: true, value: { ...DEFAULT_STATUS, ...JSON.parse(result.value.stdout) } };
    }
    catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse taplctl JSON.' };
    }
}
async function safeArchives() {
    const result = await runTapl(['archive', 'list', '--json']);
    if (!result.ok) {
        return result;
    }
    try {
        const payload = JSON.parse(result.value.stdout);
        return { ok: true, value: payload.archives ?? [] };
    }
    catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl archive JSON.' };
    }
}
async function safeArchiveDetail(archiveId) {
    const result = await runTapl(['archive', 'show', '--id', archiveId, '--json']);
    if (!result.ok) {
        return result;
    }
    try {
        const payload = JSON.parse(result.value.stdout);
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
    }
    catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl archive detail JSON.' };
    }
}
async function safeItemDetail(itemId) {
    const result = await runTapl(['item', 'show', '--id', String(itemId), '--json']);
    if (!result.ok) {
        return result;
    }
    try {
        const payload = JSON.parse(result.value.stdout);
        if (payload.ok === false) {
            return { ok: false, error: payload.error ?? 'Failed to load tapl item detail.' };
        }
        if (!payload.item) {
            return { ok: false, error: 'tapl item detail response did not include an item.' };
        }
        return { ok: true, value: payload.item };
    }
    catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl item detail JSON.' };
    }
}
async function searchTapl(query) {
    const result = await runTapl(['search', query, '--json']);
    if (!result.ok) {
        return result;
    }
    try {
        return { ok: true, value: JSON.parse(result.value.stdout) };
    }
    catch (error) {
        return { ok: false, error: error instanceof Error ? error.message : 'Failed to parse tapl search JSON.' };
    }
}
async function runTapl(args) {
    const root = getWorkspaceRoot();
    if (!root) {
        return { ok: false, error: 'Open a workspace folder to use tapl.' };
    }
    const commands = taplctlCommandCandidates();
    const failures = [];
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
function taplctlCommandCandidates() {
    const configured = vscode.workspace
        .getConfiguration(COMMAND_PREFIX)
        .get(TAPLCTL_PATH_SETTING, '')
        .trim();
    return uniqueStrings([
        configured || undefined,
        ...COMMON_TAPLCTL_COMMANDS
    ]);
}
function uniqueStrings(values) {
    const seen = new Set();
    const result = [];
    for (const value of values) {
        if (!value || seen.has(value)) {
            continue;
        }
        seen.add(value);
        result.push(value);
    }
    return result;
}
function taplctlExecutionEnv() {
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
function execFile(command, args, cwd) {
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
function isCommandNotFound(error) {
    return error.code === 'ENOENT';
}
function getWorkspaceRoot() {
    return vscode.workspace.workspaceFolders?.[0];
}
function emptyNode(label) {
    return new WorkflowNode({
        label,
        kind: 'empty',
        icon: 'info',
        tooltip: label
    });
}
function searchResultFromItem(item) {
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
function createDebouncedRefresh(callback, delayMs) {
    let timer;
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
function renderPage(webview, body, viewKey) {
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
      --accent: var(--vscode-focusBorder);
      --error: var(--vscode-errorForeground);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: var(--vscode-font-family);
      color: var(--fg);
      background: var(--bg);
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
    h1, h2, h3, p { margin-top: 0; }
    h1 { font-size: 28px; margin-bottom: 0; }
    h2 { font-size: 15px; }
    h3 { font-size: 13px; margin-bottom: 8px; }
    pre {
      white-space: pre-wrap;
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
      margin-bottom: 20px;
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
    .metric, .panel, .item {
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel);
    }
    .metric {
      padding: 12px;
      display: grid;
      gap: 4px;
    }
    .metric strong { font-size: 20px; }
    .status-strip {
      display: flex;
      flex-wrap: wrap;
    }
    .pill, .badge {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      border-radius: 999px;
      padding: 2px 8px;
      border: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
    }
    .completed { color: var(--vscode-testing-iconPassed, #4e9a06); }
    .blocked, .error { color: var(--error); }
    .in-progress { color: var(--accent); }
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
      padding: 14px;
      min-width: 0;
    }
    .item {
      padding: 10px;
      margin-top: 8px;
    }
    .item-button {
      display: block;
      width: 100%;
      text-align: left;
      background: var(--panel);
      color: var(--fg);
      border-color: var(--border);
      cursor: pointer;
    }
    .item-button:hover {
      border-color: var(--accent);
    }
    .archive-summary {
      display: block;
      margin-top: 4px;
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
      align-items: center;
      margin-bottom: 6px;
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
      grid-template-columns: 130px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }
    .detail-row span {
      color: var(--muted);
      font-size: 12px;
    }
    .detail-row strong {
      overflow-wrap: anywhere;
      font-weight: 600;
    }
    .debug-footer {
      display: flex;
      justify-content: flex-end;
      margin-top: 16px;
    }
    @media (max-width: 900px) {
      body { padding: 16px; }
      .grid { grid-template-columns: 1fr; }
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
function createNonce(seed) {
    let value = 0;
    for (let index = 0; index < seed.length; index += 1) {
        value = (value * 31 + seed.charCodeAt(index)) >>> 0;
    }
    return `tapl${value.toString(36)}${Date.now().toString(36)}`;
}
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
}
function isRecord(value) {
    return typeof value === 'object' && value !== null;
}
//# sourceMappingURL=extension.js.map