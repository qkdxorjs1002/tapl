import * as vscode from 'vscode';

type WorkflowNodeKind = 'overview' | 'file' | 'archive' | 'empty';

interface WorkflowDocument {
  filename: string;
  label: string;
  description: string;
  icon: string;
}

interface LoadedDocument {
  document: WorkflowDocument;
  uri: vscode.Uri;
  content: string | undefined;
}

interface TabDocument {
  title: string;
  source: string;
  content: string | undefined;
  missingText: string;
}

interface ArchiveListItem {
  folderName: string;
  summary: string;
}

interface WorkflowItemBlock {
  id: string;
  kind: string;
  title: string;
  details: string[];
}

type WorkflowPanelView =
  | { type: 'overview' }
  | { type: 'document'; uri: vscode.Uri; title: string }
  | { type: 'archive'; uri: vscode.Uri; title: string };

const WORKFLOW_DIR = '.agent-workflow';
const ARCHIVE_DIR = 'archive';
const ACTIVE_DOCUMENTS: WorkflowDocument[] = [
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

export function activate(context: vscode.ExtensionContext): void {
  const activeProvider = new ActiveWorkflowProvider();
  const archiveProvider = new ArchiveWorkflowProvider();
  const webviewManager = new WorkflowWebviewManager();

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('repltaWorkflow.active', activeProvider),
    vscode.window.registerTreeDataProvider('repltaWorkflow.archives', archiveProvider),
    vscode.commands.registerCommand('repltaWorkflow.refresh', () => {
      activeProvider.refresh();
      archiveProvider.refresh();
      void webviewManager.refresh();
    }),
    vscode.commands.registerCommand('repltaWorkflow.openOverview', async () => {
      await webviewManager.openOverview();
    }),
    vscode.commands.registerCommand('repltaWorkflow.openDocument', async (node?: unknown) => {
      const uri = node instanceof WorkflowNode ? node.fileUri : undefined;
      const title = node instanceof WorkflowNode ? String(node.label ?? 'Workflow Document') : 'Workflow Document';
      if (!uri) {
        await vscode.window.showWarningMessage('Select a workflow Markdown file to view.');
        return;
      }

      await webviewManager.openDocument(uri, title);
    }),
    vscode.commands.registerCommand('repltaWorkflow.openArchive', async (node?: unknown) => {
      const uri = node instanceof WorkflowNode ? node.archiveUri : undefined;
      const title = node instanceof WorkflowNode ? String(node.label ?? 'Workflow Archive') : 'Workflow Archive';
      if (!uri) {
        await vscode.window.showWarningMessage('Select a workflow archive to view.');
        return;
      }

      await webviewManager.openArchive(uri, title);
    })
  );

  const root = getWorkspaceRoot();
  if (root) {
    const watcher = vscode.workspace.createFileSystemWatcher(
      new vscode.RelativePattern(root, `${WORKFLOW_DIR}/**/*.md`)
    );
    const refresh = () => {
      activeProvider.refresh();
      archiveProvider.refresh();
      void webviewManager.refresh();
    };

    context.subscriptions.push(
      watcher,
      watcher.onDidChange(refresh),
      watcher.onDidCreate(refresh),
      watcher.onDidDelete(refresh)
    );
  }
}

export function deactivate(): void {
  // Nothing to dispose manually. VSCode owns registered disposables through subscriptions.
}

class WorkflowNode extends vscode.TreeItem {
  readonly kind: WorkflowNodeKind;
  readonly fileUri?: vscode.Uri;
  readonly archiveUri?: vscode.Uri;

  constructor(options: {
    label: string;
    kind: WorkflowNodeKind;
    collapsibleState?: vscode.TreeItemCollapsibleState;
    description?: string;
    tooltip?: string;
    icon?: string;
    fileUri?: vscode.Uri;
    archiveUri?: vscode.Uri;
  }) {
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

class ActiveWorkflowProvider implements vscode.TreeDataProvider<WorkflowNode> {
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
      return [emptyNode('Open a workspace folder to view workflow documents.')];
    }

    const workflowUri = vscode.Uri.joinPath(root.uri, WORKFLOW_DIR);
    if (!(await exists(workflowUri))) {
      return [emptyNode('No .agent-workflow folder found.')];
    }

    const nodes: WorkflowNode[] = [new WorkflowNode({
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

class ArchiveWorkflowProvider implements vscode.TreeDataProvider<WorkflowNode> {
  private readonly changedEmitter = new vscode.EventEmitter<WorkflowNode | undefined>();
  readonly onDidChangeTreeData = this.changedEmitter.event;

  refresh(): void {
    this.changedEmitter.fire(undefined);
  }

  getTreeItem(element: WorkflowNode): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: WorkflowNode): Promise<WorkflowNode[]> {
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

  private async getArchiveDocuments(archiveUri: vscode.Uri): Promise<WorkflowNode[]> {
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
  private panel: vscode.WebviewPanel | undefined;
  private currentView: WorkflowPanelView = { type: 'overview' };

  async openOverview(): Promise<void> {
    this.currentView = { type: 'overview' };
    await this.render('Workflow Dashboard');
  }

  async openDocument(uri: vscode.Uri, title: string): Promise<void> {
    this.currentView = { type: 'document', uri, title };
    await this.render(title);
  }

  async openArchive(uri: vscode.Uri, title: string): Promise<void> {
    this.currentView = { type: 'archive', uri, title };
    await this.render(title);
  }

  async refresh(): Promise<void> {
    if (!this.panel) {
      return;
    }

    await this.render(this.panel.title);
  }

  private async render(title: string): Promise<void> {
    const panel = this.ensurePanel(title);
    panel.title = title;
    panel.webview.html = await this.renderCurrentView(panel.webview);
  }

  private ensurePanel(title: string): vscode.WebviewPanel {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.One);
      return this.panel;
    }

    this.panel = vscode.window.createWebviewPanel(
      'repltaWorkflow.viewer',
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
    switch (this.currentView.type) {
      case 'document':
        return renderPage(
          webview,
          await renderDocumentView(this.currentView.uri, this.currentView.title),
          `document:${relativePath(this.currentView.uri)}`
        );
      case 'archive':
        return renderPage(
          webview,
          await renderArchiveView(this.currentView.uri, this.currentView.title),
          `archive:${relativePath(this.currentView.uri)}`
        );
      case 'overview':
      default:
        return renderPage(webview, await renderOverviewView(), 'overview');
    }
  }

  private async handleMessage(message: unknown): Promise<void> {
    if (!isRecord(message) || typeof message.command !== 'string') {
      return;
    }

    if (message.command === 'openOverview') {
      await this.openOverview();
      return;
    }

    if (message.command === 'openArchive' && typeof message.archiveFolder === 'string') {
      await this.openArchiveFromDashboard(message.archiveFolder);
    }
  }

  private async openArchiveFromDashboard(folderName: string): Promise<void> {
    const root = getWorkspaceRoot();
    if (!root) {
      return;
    }

    const archiveRootUri = vscode.Uri.joinPath(root.uri, WORKFLOW_DIR, ARCHIVE_DIR);
    const archiveFolders = await listArchiveFolders(archiveRootUri);
    if (!archiveFolders.includes(folderName)) {
      return;
    }

    await this.openArchive(vscode.Uri.joinPath(archiveRootUri, folderName), folderName);
  }
}

async function renderOverviewView(): Promise<string> {
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
  const archiveRootUri = vscode.Uri.joinPath(workflowUri, ARCHIVE_DIR);
  const archiveFolders = await listArchiveFolders(archiveRootUri);
  const visibleArchiveItems = await loadArchiveListItems(archiveRootUri, archiveFolders.slice(0, 8));

  const sections = documents.map(({ document, uri, content }) => ({
    title: document.label,
    source: relativePath(uri),
    content,
    missingText: `${document.filename} does not exist.`
  }));

  const archiveItems = archiveFolders.length > 0
    ? `<ul class="archive-list">${visibleArchiveItems.map(renderArchiveListItem).join('')}</ul>`
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
      ${renderDocumentTabs('active-workflow-documents', sections)}
      <aside class="side-panel">
        <h2>Archives</h2>
        ${archiveItems}
      </aside>
    </main>
  `;
}

async function renderDocumentView(uri: vscode.Uri, title: string): Promise<string> {
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

async function renderArchiveView(archiveUri: vscode.Uri, title: string): Promise<string> {
  const entries = await safeReadDirectory(archiveUri);
  const markdownFiles = entries
    .filter(([name, type]) => (type & vscode.FileType.File) !== 0 && name.endsWith('.md'))
    .map(([name]) => name)
    .sort(compareArchiveDocuments);

  const documents = markdownFiles.length > 0
    ? await Promise.all(markdownFiles.map(async (filename) => {
      const uri = vscode.Uri.joinPath(archiveUri, filename);
      return {
        title: archiveDocumentLabel(filename),
        source: relativePath(uri),
        content: await readMarkdownFile(uri),
        missingText: `${filename} does not exist.`
      };
    }))
    : [];

  const body = documents.length > 1
    ? renderDocumentTabs('archive-documents', documents)
    : documents.length === 1
      ? renderDocumentCard(documents[0])
      : '<section class="doc-card"><p class="muted">No Markdown files in this archive.</p></section>';

  return `
    <nav class="page-actions" aria-label="Archive navigation">
      <button class="dashboard-button" type="button" data-open-overview>
        <span aria-hidden="true">Home</span>
        <span>Workflow Dashboard</span>
      </button>
    </nav>
    <header class="hero compact">
      <p class="eyebrow">${escapeHtml(relativePath(archiveUri))}</p>
      <h1>${escapeHtml(title)}</h1>
      <p class="lede">${markdownFiles.length} Markdown document${markdownFiles.length === 1 ? '' : 's'}</p>
    </header>
    <main class="single-document">
      ${body}
    </main>
  `;
}

async function loadActiveDocuments(workflowUri: vscode.Uri): Promise<LoadedDocument[]> {
  return Promise.all(ACTIVE_DOCUMENTS.map(async (document) => {
    const uri = vscode.Uri.joinPath(workflowUri, document.filename);
    return {
      document,
      uri,
      content: await readMarkdownFile(uri)
    };
  }));
}

async function listArchiveFolders(archiveRootUri: vscode.Uri): Promise<string[]> {
  const entries = await safeReadDirectory(archiveRootUri);
  return entries
    .filter(([, type]) => (type & vscode.FileType.Directory) !== 0)
    .map(([name]) => name)
    .sort((left, right) => right.localeCompare(left));
}

async function loadArchiveListItems(archiveRootUri: vscode.Uri, folderNames: string[]): Promise<ArchiveListItem[]> {
  return Promise.all(folderNames.map(async (folderName) => {
    const summaryUri = vscode.Uri.joinPath(archiveRootUri, folderName, 'summary.md');
    const summaryContent = await readMarkdownFile(summaryUri);
    return {
      folderName,
      summary: extractArchiveSummary(summaryContent, folderName)
    };
  }));
}

function renderArchiveListItem(item: ArchiveListItem): string {
  return `
    <li>
      <button class="archive-open-button" type="button" data-archive-folder="${escapeHtml(item.folderName)}">
        <span class="archive-summary">${escapeHtml(item.summary)}</span>
        <small class="archive-folder">${escapeHtml(item.folderName)}</small>
      </button>
    </li>
  `;
}

function extractArchiveSummary(markdown: string | undefined, folderName: string): string {
  if (!markdown) {
    return folderName;
  }

  return firstUsefulSummaryLine(extractMarkdownSection(markdown, 'Original Request'))
    ?? firstUsefulSummaryLine(extractMarkdownSection(markdown, 'Final Requirements'))
    ?? firstUsefulSummaryLine(markdown)
    ?? folderName;
}

function extractMarkdownSection(markdown: string, heading: string): string | undefined {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const sectionLines: string[] = [];
  let collecting = false;

  for (const line of lines) {
    const sectionHeading = /^##\s+(.+?)\s*$/.exec(line);
    if (sectionHeading) {
      if (collecting) {
        break;
      }

      collecting = sectionHeading[1].trim().toLowerCase() === heading.toLowerCase();
      continue;
    }

    if (collecting) {
      sectionLines.push(line);
    }
  }

  return sectionLines.length > 0 ? sectionLines.join('\n') : undefined;
}

function firstUsefulSummaryLine(markdown: string | undefined): string | undefined {
  if (!markdown) {
    return undefined;
  }

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const summary = line
      .trim()
      .replace(/^[-*]\s+/, '')
      .replace(/^(?:REQ|SPEC|TASK|FINDING|ASSUMPTION|QUESTION)-\d{3}:\s*/, '')
      .trim();

    if (summary.length === 0 || summary.startsWith('#')) {
      continue;
    }

    return truncateSummary(summary);
  }

  return undefined;
}

function truncateSummary(value: string): string {
  const compact = value.replace(/\s+/g, ' ').trim();
  return compact.length > 180 ? `${compact.slice(0, 177)}...` : compact;
}

function renderDocumentCard(options: {
  title: string;
  source: string;
  content: string | undefined;
  missingText: string;
}): string {
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

function renderDocumentTabs(groupId: string, documents: TabDocument[]): string {
  if (documents.length === 0) {
    return '<section class="doc-card"><p class="muted">No workflow documents found.</p></section>';
  }

  const safeGroupId = sanitizeHtmlId(groupId);
  const tabs = documents.map((document, index) => {
    const tabId = `${safeGroupId}-${index}`;
    const checked = index === 0 ? ' checked' : '';

    return `
      <input class="tab-radio" type="radio" name="${safeGroupId}" id="${tabId}"${checked}>
      <label class="tab-label" for="${tabId}">
        <span>${escapeHtml(document.title)}</span>
        <small>${escapeHtml(document.source.split('/').pop() ?? document.source)}</small>
      </label>
      <section class="tab-panel">
        ${renderDocumentCard(document)}
      </section>
    `;
  }).join('');

  return `
    <section class="document-tabs" aria-label="Workflow documents">
      ${tabs}
    </section>
  `;
}

function renderEmptyView(title: string, message: string): string {
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

function renderMetric(label: string, value: string, detail: string): string {
  return `
    <article class="metric-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <p>${escapeHtml(detail)}</p>
    </article>
  `;
}

function renderStatusPill(label: string, count: number): string {
  const statusClass = label.toLowerCase().replace(/\s+/g, '-');
  const activeClasses = count > 0 ? ` status-pill-active status-pill-${statusClass}` : '';
  return `<span class="status-pill${activeClasses}"><strong>${count}</strong>${escapeHtml(label)}</span>`;
}

function taskStatusLabel(summary: TaskSummary): string {
  if (summary.total === 0) {
    return 'no task entries';
  }

  return `${summary.completed} completed, ${summary.pending + summary.inProgress + summary.blocked} active`;
}

interface TaskSummary {
  total: number;
  pending: number;
  inProgress: number;
  completed: number;
  blocked: number;
  skipped: number;
}

function summarizeTasks(content: string | undefined): TaskSummary {
  const summary: TaskSummary = {
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

function renderMarkdown(markdown: string): string {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const html: string[] = [];
  let listType: 'ul' | 'ol' | undefined;
  let inCodeBlock = false;
  let codeLines: string[] = [];

  const closeList = () => {
    if (!listType) {
      return;
    }

    html.push(`</${listType}>`);
    listType = undefined;
  };

  const openList = (type: 'ul' | 'ol') => {
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

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];

    if (line.startsWith('```')) {
      if (inCodeBlock) {
        closeCodeBlock();
      } else {
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

    const workflowItem = parseWorkflowItemLine(line);
    if (workflowItem) {
      closeList();
      while (index + 1 < lines.length) {
        const detail = /^\s{2,}-\s+(.+)$/.exec(lines[index + 1]);
        if (!detail) {
          break;
        }

        workflowItem.details.push(detail[1]);
        index += 1;
      }

      html.push(renderWorkflowItemBlock(workflowItem));
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

function parseWorkflowItemLine(line: string): WorkflowItemBlock | undefined {
  const match = /^-\s+((?:REQ|SPEC|TASK|FINDING|ASSUMPTION|QUESTION)-\d{3})(.*)$/.exec(line);
  if (!match) {
    return undefined;
  }

  return {
    id: match[1],
    kind: match[1].split('-')[0].toLowerCase(),
    title: match[2].replace(/^:\s*/, '').trim(),
    details: []
  };
}

function renderWorkflowItemBlock(item: WorkflowItemBlock): string {
  const title = item.title.length > 0
    ? `<div class="workflow-item-title">${renderInlineMarkdown(item.title)}</div>`
    : '';
  const details = item.details.length > 0
    ? `<ul class="workflow-item-details">${item.details.map((detail) => `<li>${renderInlineMarkdown(detail)}</li>`).join('')}</ul>`
    : '';

  return `
    <article class="workflow-item-block workflow-item-${escapeHtml(item.kind)}">
      <div class="workflow-item-heading">
        <span class="workflow-item-id">${escapeHtml(item.id)}</span>
        ${title}
      </div>
      ${details}
    </article>
  `;
}

function renderInlineMarkdown(value: string): string {
  return renderStatusTokensOutsideCode(escapeHtml(value)
    .replace(/`([^`]+)`/g, (_match, code: string) => {
      return `<code>${code}</code>`;
    })
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<span class="link-like">$1</span>'));
}

function renderStatusTokensOutsideCode(value: string): string {
  return value
    .split(/(<code>[\s\S]*?<\/code>)/g)
    .map((segment) => segment.startsWith('<code>')
      ? segment
      : segment.replace(/\[(Pending|In Progress|Completed|Blocked|Skipped)\]/g, (_match, status: string) => renderStatusBadge(status)))
    .join('');
}

function renderStatusBadge(status: string): string {
  const className = status.toLowerCase().replace(/\s+/g, '-');
  return `<span class="task-status-badge task-status-${className}">${status}</span>`;
}

function renderPage(webview: vscode.Webview, body: string, viewStateKey: string): string {
  const nonce = String(Date.now());
  const encodedViewStateKey = JSON.stringify(viewStateKey).replace(/</g, '\\u003c');
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource} 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
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

    .page-actions {
      display: flex;
      align-items: center;
      padding: 14px 36px 0;
      background: var(--panel);
    }

    .page-actions + .hero {
      padding-top: 18px;
    }

    .dashboard-button {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 32px;
      max-width: 100%;
      padding: 4px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--panel-alt);
      color: var(--text);
      cursor: pointer;
      font: inherit;
      font-weight: 600;
    }

    .dashboard-button:hover {
      border-color: var(--accent);
      color: var(--link);
    }

    .dashboard-button:focus-visible {
      outline: 1px solid var(--accent);
      outline-offset: 2px;
    }

    .dashboard-button span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
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

    .status-pill-active {
      border-color: currentColor;
    }

    .status-pill-active strong {
      color: inherit;
    }

    .status-pill-pending {
      color: var(--vscode-charts-yellow, var(--muted));
    }

    .status-pill-in-progress {
      color: var(--vscode-charts-blue, var(--link));
    }

    .status-pill-completed {
      color: var(--vscode-charts-green, var(--text));
    }

    .status-pill-blocked {
      color: var(--vscode-inputValidation-errorForeground, var(--vscode-errorForeground, var(--text)));
    }

    .status-pill-skipped {
      color: var(--muted);
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

    .document-tabs {
      display: flex;
      flex-wrap: wrap;
      align-content: flex-start;
      align-items: stretch;
      gap: 8px;
      min-width: 0;
    }

    .layout > .document-tabs,
    .single-document > .document-tabs {
      min-width: 0;
    }

    .tab-radio {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }

    .tab-label {
      display: inline-flex;
      flex: 1 1 150px;
      order: 1;
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      min-width: 0;
      min-height: 46px;
      padding: 7px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--panel);
      color: var(--muted);
      cursor: pointer;
    }

    .tab-label span,
    .tab-label small {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .tab-label span {
      color: var(--text);
      font-weight: 600;
    }

    .tab-label small {
      font-size: 11px;
      color: var(--muted);
      font-family: var(--vscode-editor-font-family);
    }

    .tab-radio:checked + .tab-label {
      border-color: var(--accent);
      background: var(--panel-alt);
      box-shadow: inset 0 -2px 0 var(--accent);
    }

    .tab-radio:focus-visible + .tab-label {
      outline: 1px solid var(--accent);
      outline-offset: 2px;
    }

    .tab-panel {
      display: none;
      order: 2;
      flex: 1 0 100%;
      min-width: 0;
    }

    .tab-radio:checked + .tab-label + .tab-panel {
      display: block;
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

    .workflow-item-block {
      margin: 12px 0;
      padding: 12px 14px;
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: 8px;
      background: var(--panel);
    }

    .workflow-item-heading {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 10px;
      min-width: 0;
    }

    .workflow-item-id {
      flex: 0 0 auto;
      padding: 1px 7px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--panel-alt);
      color: var(--link);
      font-family: var(--vscode-editor-font-family);
      font-size: 0.82em;
      font-weight: 700;
      line-height: 1.6;
    }

    .workflow-item-title {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      column-gap: 6px;
      row-gap: 4px;
      min-width: 0;
      overflow-wrap: anywhere;
      font-weight: 600;
      line-height: 1.45;
    }

    .workflow-item-details {
      display: grid;
      gap: 5px;
      margin: 10px 0 0;
      padding-left: 20px;
      color: var(--muted);
    }

    .workflow-item-details li {
      overflow-wrap: anywhere;
    }

    .task-status-badge {
      display: inline-flex;
      align-items: center;
      flex: 0 0 auto;
      min-height: 20px;
      padding: 1px 7px;
      border: 1px solid currentColor;
      border-radius: 999px;
      background: var(--panel);
      font-size: 0.78em;
      font-weight: 600;
      line-height: 1.25;
      white-space: nowrap;
      vertical-align: middle;
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

    .markdown-body code {
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

    .archive-open-button {
      display: grid;
      gap: 4px;
      width: 100%;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      cursor: pointer;
      font: inherit;
      text-align: left;
    }

    .archive-open-button:focus-visible {
      outline: 1px solid var(--accent);
      outline-offset: 3px;
    }

    .archive-open-button:hover .archive-summary {
      color: var(--link);
    }

    .archive-summary {
      font-weight: 600;
    }

    .archive-folder {
      color: var(--muted);
      font-size: 12px;
    }

    .archive-summary,
    .archive-folder {
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
      .page-actions,
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

      .tab-label {
        flex-basis: 130px;
      }

      .workflow-item-heading {
        align-items: flex-start;
        flex-direction: column;
        gap: 6px;
      }
    }
  </style>
</head>
<body>
  ${body}
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const viewStateKey = ${encodedViewStateKey};
    let webviewState = vscode.getState() || {};
    const getStoredViews = () => {
      return webviewState.views && typeof webviewState.views === 'object' ? webviewState.views : {};
    };
    let viewState = getStoredViews()[viewStateKey] || {};
    let scrollSaveTimer;

    const getSelectedTabs = () => {
      const tabs = { ...(viewState.tabs || {}) };
      document.querySelectorAll('.tab-radio:checked').forEach((radio) => {
        if (!(radio instanceof HTMLInputElement) || !radio.name || !radio.id) {
          return;
        }

        tabs[radio.name] = radio.id;
      });
      return tabs;
    };

    const saveViewState = () => {
      viewState = {
        ...viewState,
        tabs: getSelectedTabs(),
        scrollY: window.scrollY
      };
      webviewState = {
        ...webviewState,
        views: {
          ...getStoredViews(),
          [viewStateKey]: viewState
        }
      };
      vscode.setState(webviewState);
    };

    const scheduleScrollSave = () => {
      window.clearTimeout(scrollSaveTimer);
      scrollSaveTimer = window.setTimeout(saveViewState, 120);
    };

    const restoreViewState = () => {
      const tabs = viewState.tabs || {};
      Object.entries(tabs).forEach(([groupName, tabId]) => {
        document.querySelectorAll('.tab-radio').forEach((radio) => {
          if (radio instanceof HTMLInputElement && radio.name === groupName && radio.id === String(tabId)) {
            radio.checked = true;
          }
        });
      });

      if (typeof viewState.scrollY === 'number') {
        window.scrollTo(0, viewState.scrollY);
      }
    };

    const restoreAfterLayout = () => {
      window.requestAnimationFrame(restoreViewState);
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', restoreAfterLayout, { once: true });
    } else {
      restoreAfterLayout();
    }

    document.addEventListener('change', (event) => {
      const target = event.target;
      if (target instanceof HTMLInputElement && target.classList.contains('tab-radio')) {
        saveViewState();
      }
    });

    window.addEventListener('scroll', scheduleScrollSave, { passive: true });
    window.addEventListener('beforeunload', saveViewState);

    document.addEventListener('click', (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const dashboardButton = target?.closest('[data-open-overview]');
      if (dashboardButton instanceof HTMLElement) {
        saveViewState();
        vscode.postMessage({ command: 'openOverview' });
        return;
      }

      const archiveButton = target?.closest('[data-archive-folder]');
      if (!(archiveButton instanceof HTMLElement)) {
        return;
      }

      const archiveFolder = archiveButton.dataset.archiveFolder;
      if (!archiveFolder) {
        return;
      }

      saveViewState();
      vscode.postMessage({ command: 'openArchive', archiveFolder });
    });
  </script>
</body>
</html>`;
}

function getWorkspaceRoot(): vscode.WorkspaceFolder | undefined {
  return vscode.workspace.workspaceFolders?.[0];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function emptyNode(label: string): WorkflowNode {
  return new WorkflowNode({
    label,
    kind: 'empty',
    icon: 'info'
  });
}

async function exists(uri: vscode.Uri): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(uri);
    return true;
  } catch {
    return false;
  }
}

async function safeReadDirectory(uri: vscode.Uri): Promise<[string, vscode.FileType][]> {
  try {
    return await vscode.workspace.fs.readDirectory(uri);
  } catch {
    return [];
  }
}

async function readMarkdownFile(uri: vscode.Uri): Promise<string | undefined> {
  try {
    return new TextDecoder('utf-8').decode(await vscode.workspace.fs.readFile(uri));
  } catch {
    return undefined;
  }
}

function relativePath(uri: vscode.Uri): string {
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

function normalizeUriPath(value: string): string {
  return value.replace(/\/+$/, '');
}

function sanitizeHtmlId(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  return normalized.length > 0 ? normalized : 'workflow-tabs';
}

function compareArchiveDocuments(left: string, right: string): number {
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

function archiveDocumentLabel(filename: string): string {
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

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
