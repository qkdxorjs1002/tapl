"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const vscode = require("vscode");
const WORKFLOW_DIR = '.agent-workflow';
const ARCHIVE_DIR = 'archive';
const ACTIVE_DOCUMENTS = [
    { filename: 'task.md', label: 'Tasks', description: 'Current executable tasks', icon: 'checklist' },
    { filename: 'request.md', label: 'Request', description: 'Requirements and assumptions', icon: 'symbol-property' },
    { filename: 'plan.md', label: 'Plan', description: 'Approved implementation plan', icon: 'list-ordered' },
    { filename: 'speedwagon.md', label: 'External Findings', description: 'Decision-relevant findings', icon: 'references' },
    { filename: 'index.md', label: 'Archive Index', description: 'Archived workflow lookup', icon: 'book' }
];
const ARCHIVE_DOCUMENT_ORDER = [
    'summary.md',
    'task.md',
    'request.md',
    'plan.md',
    'speedwagon.md',
    'index.md'
];
function activate(context) {
    const activeProvider = new ActiveWorkflowProvider();
    const archiveProvider = new ArchiveWorkflowProvider();
    const webviewManager = new WorkflowWebviewManager();
    context.subscriptions.push(vscode.window.registerTreeDataProvider('repltaWorkflow.active', activeProvider), vscode.window.registerTreeDataProvider('repltaWorkflow.archives', archiveProvider), vscode.commands.registerCommand('repltaWorkflow.refresh', () => {
        activeProvider.refresh();
        archiveProvider.refresh();
        void webviewManager.refresh();
    }), vscode.commands.registerCommand('repltaWorkflow.openOverview', async () => {
        await webviewManager.openOverview();
    }), vscode.commands.registerCommand('repltaWorkflow.openDocument', async (node) => {
        const uri = node instanceof WorkflowNode ? node.fileUri : undefined;
        const title = node instanceof WorkflowNode ? String(node.label ?? 'Workflow Document') : 'Workflow Document';
        if (!uri) {
            await vscode.window.showWarningMessage('Select a workflow Markdown file to view.');
            return;
        }
        await webviewManager.openDocument(uri, title);
    }), vscode.commands.registerCommand('repltaWorkflow.openArchive', async (node) => {
        const uri = node instanceof WorkflowNode ? node.archiveUri : undefined;
        const title = node instanceof WorkflowNode ? String(node.label ?? 'Workflow Archive') : 'Workflow Archive';
        if (!uri) {
            await vscode.window.showWarningMessage('Select a workflow archive to view.');
            return;
        }
        await webviewManager.openArchive(uri, title);
    }));
    const root = getWorkspaceRoot();
    if (root) {
        const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, `${WORKFLOW_DIR}/**/*.md`));
        const refresh = () => {
            activeProvider.refresh();
            archiveProvider.refresh();
            void webviewManager.refresh();
        };
        context.subscriptions.push(watcher, watcher.onDidChange(refresh), watcher.onDidCreate(refresh), watcher.onDidDelete(refresh));
    }
}
function deactivate() {
    // Nothing to dispose manually. VSCode owns registered disposables through subscriptions.
}
class WorkflowNode extends vscode.TreeItem {
    constructor(options) {
        super(options.label, options.collapsibleState ?? vscode.TreeItemCollapsibleState.None);
        this.kind = options.kind;
        this.fileUri = options.fileUri;
        this.archiveUri = options.archiveUri;
        this.description = options.description;
        this.tooltip = options.tooltip;
        if (options.icon) {
            this.iconPath = new vscode.ThemeIcon(options.icon);
        }
        if (options.fileUri) {
            this.resourceUri = options.fileUri;
            this.contextValue = 'workflowFile';
            this.command = {
                command: 'repltaWorkflow.openDocument',
                title: 'Open Workflow Document',
                arguments: [this]
            };
        }
        if (options.kind === 'overview') {
            this.contextValue = 'workflowOverview';
            this.command = {
                command: 'repltaWorkflow.openOverview',
                title: 'Open Workflow Dashboard'
            };
        }
        if (options.kind === 'archive' && options.archiveUri) {
            this.resourceUri = options.archiveUri;
            this.contextValue = 'workflowArchive';
            this.command = {
                command: 'repltaWorkflow.openArchive',
                title: 'Open Workflow Archive',
                arguments: [this]
            };
        }
    }
}
class ActiveWorkflowProvider {
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
            return [emptyNode('Open a workspace folder to view workflow documents.')];
        }
        const workflowUri = vscode.Uri.joinPath(root.uri, WORKFLOW_DIR);
        if (!(await exists(workflowUri))) {
            return [emptyNode('No .agent-workflow folder found.')];
        }
        const nodes = [new WorkflowNode({
                label: 'Workflow Dashboard',
                kind: 'overview',
                description: 'active workflow',
                tooltip: 'View active workflow documents together',
                icon: 'dashboard'
            })];
        for (const document of ACTIVE_DOCUMENTS) {
            const uri = vscode.Uri.joinPath(workflowUri, document.filename);
            if (!(await exists(uri))) {
                continue;
            }
            nodes.push(new WorkflowNode({
                label: document.label,
                kind: 'file',
                description: document.filename,
                tooltip: document.description,
                icon: document.icon,
                fileUri: uri
            }));
        }
        return nodes;
    }
}
class ArchiveWorkflowProvider {
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
        const root = getWorkspaceRoot();
        if (!root) {
            return [emptyNode('Open a workspace folder to view workflow archives.')];
        }
        if (element?.kind === 'archive' && element.archiveUri) {
            return this.getArchiveDocuments(element.archiveUri);
        }
        if (element) {
            return [];
        }
        const archiveRootUri = vscode.Uri.joinPath(root.uri, WORKFLOW_DIR, ARCHIVE_DIR);
        if (!(await exists(archiveRootUri))) {
            return [emptyNode('No workflow archives found.')];
        }
        const entries = await safeReadDirectory(archiveRootUri);
        const archiveFolders = entries
            .filter(([, type]) => (type & vscode.FileType.Directory) !== 0)
            .map(([name]) => name)
            .sort((left, right) => right.localeCompare(left));
        if (archiveFolders.length === 0) {
            return [emptyNode('No workflow archives found.')];
        }
        return archiveFolders.map((folderName) => new WorkflowNode({
            label: folderName,
            kind: 'archive',
            collapsibleState: vscode.TreeItemCollapsibleState.Collapsed,
            description: 'archive',
            tooltip: `${WORKFLOW_DIR}/${ARCHIVE_DIR}/${folderName}`,
            icon: 'archive',
            archiveUri: vscode.Uri.joinPath(archiveRootUri, folderName)
        }));
    }
    async getArchiveDocuments(archiveUri) {
        const entries = await safeReadDirectory(archiveUri);
        const markdownFiles = entries
            .filter(([name, type]) => (type & vscode.FileType.File) !== 0 && name.endsWith('.md'))
            .map(([name]) => name)
            .sort(compareArchiveDocuments);
        if (markdownFiles.length === 0) {
            return [emptyNode('No Markdown files in this archive.')];
        }
        return markdownFiles.map((filename) => new WorkflowNode({
            label: archiveDocumentLabel(filename),
            kind: 'file',
            description: filename,
            tooltip: filename,
            icon: filename === 'summary.md' ? 'book' : 'markdown',
            fileUri: vscode.Uri.joinPath(archiveUri, filename)
        }));
    }
}
class WorkflowWebviewManager {
    constructor() {
        this.currentView = { type: 'overview' };
    }
    async openOverview() {
        this.currentView = { type: 'overview' };
        await this.render('Workflow Dashboard');
    }
    async openDocument(uri, title) {
        this.currentView = { type: 'document', uri, title };
        await this.render(title);
    }
    async openArchive(uri, title) {
        this.currentView = { type: 'archive', uri, title };
        await this.render(title);
    }
    async refresh() {
        if (!this.panel) {
            return;
        }
        await this.render(this.panel.title);
    }
    async render(title) {
        const panel = this.ensurePanel(title);
        panel.title = title;
        panel.webview.html = await this.renderCurrentView(panel.webview);
    }
    ensurePanel(title) {
        if (this.panel) {
            this.panel.reveal(vscode.ViewColumn.One);
            return this.panel;
        }
        this.panel = vscode.window.createWebviewPanel('repltaWorkflow.viewer', title, vscode.ViewColumn.One, {
            enableScripts: false,
            retainContextWhenHidden: false
        });
        this.panel.onDidDispose(() => {
            this.panel = undefined;
        });
        return this.panel;
    }
    async renderCurrentView(webview) {
        switch (this.currentView.type) {
            case 'document':
                return renderPage(webview, await renderDocumentView(this.currentView.uri, this.currentView.title));
            case 'archive':
                return renderPage(webview, await renderArchiveView(this.currentView.uri, this.currentView.title));
            case 'overview':
            default:
                return renderPage(webview, await renderOverviewView());
        }
    }
}
async function renderOverviewView() {
    const root = getWorkspaceRoot();
    if (!root) {
        return renderEmptyView('Workflow Dashboard', 'Open a workspace folder to view workflow documents.');
    }
    const workflowUri = vscode.Uri.joinPath(root.uri, WORKFLOW_DIR);
    if (!(await exists(workflowUri))) {
        return renderEmptyView('Workflow Dashboard', `No ${WORKFLOW_DIR} folder found in ${root.name}.`);
    }
    const documents = await loadActiveDocuments(workflowUri);
    const presentDocuments = documents.filter(({ content }) => content !== undefined);
    const taskDocument = documents.find(({ document }) => document.filename === 'task.md');
    const taskSummary = summarizeTasks(taskDocument?.content);
    const archiveFolders = await listArchiveFolders(vscode.Uri.joinPath(workflowUri, ARCHIVE_DIR));
    const sections = documents.map(({ document, uri, content }) => renderDocumentCard({
        title: document.label,
        source: relativePath(uri),
        content,
        missingText: `${document.filename} does not exist.`
    })).join('');
    const archiveItems = archiveFolders.length > 0
        ? `<ul class="archive-list">${archiveFolders.slice(0, 8).map((folder) => `<li><span>${escapeHtml(folder)}</span><code>${escapeHtml(`${WORKFLOW_DIR}/${ARCHIVE_DIR}/${folder}`)}</code></li>`).join('')}</ul>`
        : '<p class="muted">No workflow archives found.</p>';
    return `
    <header class="hero">
      <p class="eyebrow">${escapeHtml(root.name)}</p>
      <h1>Workflow Dashboard</h1>
      <p class="lede">${escapeHtml(WORKFLOW_DIR)} current state</p>
    </header>
    <section class="summary-grid" aria-label="Workflow checks">
      ${renderMetric('Documents', `${presentDocuments.length}/${ACTIVE_DOCUMENTS.length}`, 'active Markdown files')}
      ${renderMetric('Tasks', String(taskSummary.total), taskStatusLabel(taskSummary))}
      ${renderMetric('Archives', String(archiveFolders.length), 'stored workflow snapshots')}
      ${renderMetric('Last Refresh', new Date().toLocaleTimeString(), 'open panel auto-refreshes')}
    </section>
    <section class="status-strip" aria-label="Task status">
      ${renderStatusPill('Pending', taskSummary.pending)}
      ${renderStatusPill('In Progress', taskSummary.inProgress)}
      ${renderStatusPill('Completed', taskSummary.completed)}
      ${renderStatusPill('Blocked', taskSummary.blocked)}
      ${renderStatusPill('Skipped', taskSummary.skipped)}
    </section>
    <main class="layout">
      <section class="document-stack">
        ${sections}
      </section>
      <aside class="side-panel">
        <h2>Archives</h2>
        ${archiveItems}
      </aside>
    </main>
  `;
}
async function renderDocumentView(uri, title) {
    const content = await readMarkdownFile(uri);
    return `
    <header class="hero compact">
      <p class="eyebrow">${escapeHtml(relativePath(uri))}</p>
      <h1>${escapeHtml(title)}</h1>
    </header>
    <main class="single-document">
      ${renderDocumentCard({
        title,
        source: relativePath(uri),
        content,
        missingText: 'This workflow document no longer exists.'
    })}
    </main>
  `;
}
async function renderArchiveView(archiveUri, title) {
    const entries = await safeReadDirectory(archiveUri);
    const markdownFiles = entries
        .filter(([name, type]) => (type & vscode.FileType.File) !== 0 && name.endsWith('.md'))
        .map(([name]) => name)
        .sort(compareArchiveDocuments);
    const cards = markdownFiles.length > 0
        ? (await Promise.all(markdownFiles.map(async (filename) => {
            const uri = vscode.Uri.joinPath(archiveUri, filename);
            return renderDocumentCard({
                title: archiveDocumentLabel(filename),
                source: relativePath(uri),
                content: await readMarkdownFile(uri),
                missingText: `${filename} does not exist.`
            });
        }))).join('')
        : '<section class="doc-card"><p class="muted">No Markdown files in this archive.</p></section>';
    return `
    <header class="hero compact">
      <p class="eyebrow">${escapeHtml(relativePath(archiveUri))}</p>
      <h1>${escapeHtml(title)}</h1>
      <p class="lede">${markdownFiles.length} Markdown document${markdownFiles.length === 1 ? '' : 's'}</p>
    </header>
    <main class="single-document">
      ${cards}
    </main>
  `;
}
async function loadActiveDocuments(workflowUri) {
    return Promise.all(ACTIVE_DOCUMENTS.map(async (document) => {
        const uri = vscode.Uri.joinPath(workflowUri, document.filename);
        return {
            document,
            uri,
            content: await readMarkdownFile(uri)
        };
    }));
}
async function listArchiveFolders(archiveRootUri) {
    const entries = await safeReadDirectory(archiveRootUri);
    return entries
        .filter(([, type]) => (type & vscode.FileType.Directory) !== 0)
        .map(([name]) => name)
        .sort((left, right) => right.localeCompare(left));
}
function renderDocumentCard(options) {
    const body = options.content === undefined
        ? `<p class="muted">${escapeHtml(options.missingText)}</p>`
        : renderMarkdown(options.content);
    return `
    <article class="doc-card">
      <header class="doc-header">
        <div>
          <h2>${escapeHtml(options.title)}</h2>
          <p>${escapeHtml(options.source)}</p>
        </div>
      </header>
      <div class="markdown-body">
        ${body}
      </div>
    </article>
  `;
}
function renderEmptyView(title, message) {
    return `
    <header class="hero compact">
      <h1>${escapeHtml(title)}</h1>
    </header>
    <main class="single-document">
      <section class="doc-card empty-state">
        <p>${escapeHtml(message)}</p>
      </section>
    </main>
  `;
}
function renderMetric(label, value, detail) {
    return `
    <article class="metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </article>
  `;
}
function renderStatusPill(label, count) {
    return `<span class="status-pill"><strong>${count}</strong>${escapeHtml(label)}</span>`;
}
function taskStatusLabel(summary) {
    if (summary.total === 0) {
        return 'no task entries';
    }
    return `${summary.completed} completed, ${summary.pending + summary.inProgress + summary.blocked} active`;
}
function summarizeTasks(content) {
    const summary = {
        total: 0,
        pending: 0,
        inProgress: 0,
        completed: 0,
        blocked: 0,
        skipped: 0
    };
    if (!content) {
        return summary;
    }
    const matches = content.matchAll(/^- TASK-\d+\s+\[([^\]]+)\]/gm);
    for (const match of matches) {
        const status = match[1].trim().toLowerCase();
        summary.total += 1;
        switch (status) {
            case 'pending':
                summary.pending += 1;
                break;
            case 'in progress':
                summary.inProgress += 1;
                break;
            case 'completed':
                summary.completed += 1;
                break;
            case 'blocked':
                summary.blocked += 1;
                break;
            case 'skipped':
                summary.skipped += 1;
                break;
            default:
                break;
        }
    }
    return summary;
}
function renderMarkdown(markdown) {
    const lines = markdown.replace(/\r\n/g, '\n').split('\n');
    const html = [];
    let listType;
    let inCodeBlock = false;
    let codeLines = [];
    const closeList = () => {
        if (!listType) {
            return;
        }
        html.push(`</${listType}>`);
        listType = undefined;
    };
    const openList = (type) => {
        if (listType === type) {
            return;
        }
        closeList();
        html.push(`<${type}>`);
        listType = type;
    };
    const closeCodeBlock = () => {
        html.push(`<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`);
        codeLines = [];
        inCodeBlock = false;
    };
    for (const line of lines) {
        if (line.startsWith('```')) {
            if (inCodeBlock) {
                closeCodeBlock();
            }
            else {
                closeList();
                inCodeBlock = true;
                codeLines = [];
            }
            continue;
        }
        if (inCodeBlock) {
            codeLines.push(line);
            continue;
        }
        if (line.trim().length === 0) {
            closeList();
            continue;
        }
        const heading = /^(#{1,4})\s+(.+)$/.exec(line);
        if (heading) {
            closeList();
            const level = heading[1].length;
            html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
            continue;
        }
        const unordered = /^-\s+(.+)$/.exec(line);
        if (unordered) {
            openList('ul');
            html.push(`<li>${renderInlineMarkdown(unordered[1])}</li>`);
            continue;
        }
        const ordered = /^\d+\.\s+(.+)$/.exec(line);
        if (ordered) {
            openList('ol');
            html.push(`<li>${renderInlineMarkdown(ordered[1])}</li>`);
            continue;
        }
        const quote = /^>\s?(.+)$/.exec(line);
        if (quote) {
            closeList();
            html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`);
            continue;
        }
        closeList();
        html.push(`<p>${renderInlineMarkdown(line.trim())}</p>`);
    }
    closeList();
    if (inCodeBlock) {
        closeCodeBlock();
    }
    return html.join('\n');
}
function renderInlineMarkdown(value) {
    return renderStatusTokensOutsideCode(escapeHtml(value)
        .replace(/`([^`]+)`/g, (_match, code) => {
        return `<code>${code}</code>`;
    })
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="link-like">$1</span>'));
}
function renderStatusTokensOutsideCode(value) {
    return value
        .split(/(<code>[\s\S]*?<\/code>)/g)
        .map((segment) => segment.startsWith('<code>')
        ? segment
        : segment.replace(/\[(Pending|In Progress|Completed|Blocked|Skipped)\]/g, (_match, status) => renderStatusBadge(status)))
        .join('');
}
function renderStatusBadge(status) {
    const className = status.toLowerCase().replace(/\s+/g, '-');
    return `<span class="task-status-badge task-status-${className}">${status}</span>`;
}
function renderPage(webview, body) {
    const nonce = String(Date.now());
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${nonce}';">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>REPLTA Workflow</title>
  <style nonce="${nonce}">
    :root {
      color-scheme: light dark;
      --page-bg: var(--vscode-editor-background);
      --text: var(--vscode-editor-foreground);
      --muted: var(--vscode-descriptionForeground);
      --border: var(--vscode-panel-border);
      --panel: var(--vscode-sideBar-background);
      --panel-alt: var(--vscode-editorWidget-background);
      --accent: var(--vscode-focusBorder);
      --code-bg: var(--vscode-textCodeBlock-background);
      --link: var(--vscode-textLink-foreground);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      background: var(--page-bg);
      color: var(--text);
      font-family: var(--vscode-font-family);
      font-size: var(--vscode-font-size);
      line-height: 1.55;
    }

    .hero {
      padding: 32px 36px 24px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }

    .hero.compact {
      padding-bottom: 20px;
    }

    .hero h1 {
      margin: 0;
      font-size: 30px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .eyebrow,
    .lede,
    .muted,
    .doc-header p,
    .metric-card p {
      color: var(--muted);
    }

    .eyebrow {
      margin: 0 0 6px;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }

    .lede {
      margin: 8px 0 0;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      padding: 18px 36px;
      border-bottom: 1px solid var(--border);
    }

    .metric-card,
    .doc-card,
    .side-panel {
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel-alt);
    }

    .metric-card {
      min-height: 112px;
      padding: 14px;
    }

    .metric-card span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }

    .metric-card strong {
      display: block;
      margin-top: 8px;
      font-size: 26px;
      line-height: 1.1;
    }

    .metric-card p {
      margin: 8px 0 0;
    }

    .status-strip {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 14px 36px 18px;
      border-bottom: 1px solid var(--border);
    }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-height: 28px;
      padding: 3px 10px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--panel);
      color: var(--muted);
      white-space: nowrap;
    }

    .status-pill strong {
      color: var(--text);
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(240px, 320px);
      gap: 18px;
      padding: 24px 36px 40px;
    }

    .document-stack,
    .single-document {
      display: grid;
      gap: 16px;
    }

    .single-document {
      padding: 24px 36px 40px;
    }

    .doc-card {
      overflow: hidden;
    }

    .doc-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      background: var(--panel);
    }

    .doc-header h2,
    .side-panel h2 {
      margin: 0;
      font-size: 17px;
      letter-spacing: 0;
    }

    .doc-header p {
      margin: 4px 0 0;
      overflow-wrap: anywhere;
      font-family: var(--vscode-editor-font-family);
      font-size: 12px;
    }

    .markdown-body {
      padding: 16px 18px 20px;
    }

    .markdown-body h1,
    .markdown-body h2,
    .markdown-body h3,
    .markdown-body h4 {
      margin: 18px 0 8px;
      letter-spacing: 0;
      line-height: 1.25;
    }

    .markdown-body h1:first-child,
    .markdown-body h2:first-child,
    .markdown-body h3:first-child,
    .markdown-body h4:first-child,
    .markdown-body p:first-child,
    .markdown-body ul:first-child,
    .markdown-body ol:first-child {
      margin-top: 0;
    }

    .markdown-body p,
    .markdown-body ul,
    .markdown-body ol,
    .markdown-body blockquote {
      margin: 10px 0;
    }

    .markdown-body ul,
    .markdown-body ol {
      padding-left: 22px;
    }

    .markdown-body li + li {
      margin-top: 4px;
    }

    .task-status-badge {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 1px 7px;
      border: 1px solid currentColor;
      border-radius: 999px;
      background: var(--panel);
      font-size: 0.78em;
      font-weight: 600;
      line-height: 1.4;
      white-space: nowrap;
      vertical-align: baseline;
    }

    .task-status-pending {
      color: var(--vscode-charts-yellow, var(--muted));
    }

    .task-status-in-progress {
      color: var(--vscode-charts-blue, var(--link));
    }

    .task-status-completed {
      color: var(--vscode-charts-green, var(--text));
    }

    .task-status-blocked {
      color: var(--vscode-inputValidation-errorForeground, var(--vscode-errorForeground, var(--text)));
    }

    .task-status-skipped {
      color: var(--muted);
    }

    .markdown-body code,
    .archive-list code {
      padding: 1px 4px;
      border-radius: 4px;
      background: var(--code-bg);
      font-family: var(--vscode-editor-font-family);
      font-size: 0.92em;
    }

    .markdown-body pre {
      overflow-x: auto;
      margin: 12px 0;
      padding: 12px;
      border-radius: 6px;
      background: var(--code-bg);
    }

    .markdown-body pre code {
      padding: 0;
      background: transparent;
    }

    .markdown-body blockquote {
      padding-left: 12px;
      border-left: 3px solid var(--accent);
      color: var(--muted);
    }

    .link-like {
      color: var(--link);
    }

    .side-panel {
      align-self: start;
      padding: 16px;
      position: sticky;
      top: 16px;
    }

    .archive-list {
      display: grid;
      gap: 10px;
      margin: 14px 0 0;
      padding: 0;
      list-style: none;
    }

    .archive-list li {
      display: grid;
      gap: 4px;
      min-width: 0;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }

    .archive-list li:last-child {
      padding-bottom: 0;
      border-bottom: 0;
    }

    .archive-list span,
    .archive-list code {
      overflow-wrap: anywhere;
    }

    .empty-state {
      padding: 24px;
    }

    @media (max-width: 860px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .side-panel {
        position: static;
      }
    }

    @media (max-width: 560px) {
      .hero,
      .summary-grid,
      .status-strip,
      .layout,
      .single-document {
        padding-left: 18px;
        padding-right: 18px;
      }

      .hero h1 {
        font-size: 24px;
      }
    }
  </style>
</head>
<body>
  ${body}
</body>
</html>`;
}
function getWorkspaceRoot() {
    return vscode.workspace.workspaceFolders?.[0];
}
function emptyNode(label) {
    return new WorkflowNode({
        label,
        kind: 'empty',
        icon: 'info'
    });
}
async function exists(uri) {
    try {
        await vscode.workspace.fs.stat(uri);
        return true;
    }
    catch {
        return false;
    }
}
async function safeReadDirectory(uri) {
    try {
        return await vscode.workspace.fs.readDirectory(uri);
    }
    catch {
        return [];
    }
}
async function readMarkdownFile(uri) {
    try {
        return new TextDecoder('utf-8').decode(await vscode.workspace.fs.readFile(uri));
    }
    catch {
        return undefined;
    }
}
function relativePath(uri) {
    const root = getWorkspaceRoot();
    if (!root) {
        return uri.fsPath;
    }
    const rootPath = normalizeUriPath(root.uri.path);
    const targetPath = normalizeUriPath(uri.path);
    if (targetPath === rootPath) {
        return root.name;
    }
    if (targetPath.startsWith(`${rootPath}/`)) {
        return targetPath.slice(rootPath.length + 1);
    }
    return uri.fsPath;
}
function normalizeUriPath(value) {
    return value.replace(/\/+$/, '');
}
function compareArchiveDocuments(left, right) {
    const leftIndex = ARCHIVE_DOCUMENT_ORDER.indexOf(left);
    const rightIndex = ARCHIVE_DOCUMENT_ORDER.indexOf(right);
    if (leftIndex !== -1 || rightIndex !== -1) {
        if (leftIndex === -1) {
            return 1;
        }
        if (rightIndex === -1) {
            return -1;
        }
        return leftIndex - rightIndex;
    }
    return left.localeCompare(right);
}
function archiveDocumentLabel(filename) {
    switch (filename) {
        case 'summary.md':
            return 'Summary';
        case 'task.md':
            return 'Tasks';
        case 'request.md':
            return 'Request';
        case 'plan.md':
            return 'Plan';
        case 'speedwagon.md':
            return 'External Findings';
        case 'index.md':
            return 'Archive Index';
        default:
            return filename;
    }
}
function escapeHtml(value) {
    return value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
//# sourceMappingURL=extension.js.map