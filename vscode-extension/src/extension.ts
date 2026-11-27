import * as vscode from 'vscode';
import { randomBytes } from 'node:crypto';
import { homedir } from 'node:os';
import { DatabaseRevisions, ViewerRefreshQueue } from './viewerRefresh';
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
import { defaultViewerPreferences, loadViewerConfig, viewerConfigRequiresTrust, type ViewerConfig } from './viewerConfig';
import { mergeTourHistory, normalizeTourHistory, TOUR_HISTORY_KEY, type TourHistory } from './viewer/tourHistory';
import { installedViewerBundle, type InstalledViewerBundle } from './viewerInstall';
import { INSTALLED_VIEWER_PROTOCOL, type InstalledViewerNavigation } from './viewer/types';

import type { ViewerPreferences, DisplayLayout, AssociativeMemory, MemoryDiagnostics, SettingsDocument, SettingsResult, HostCapabilities, RunDiscardResult, TaplRunSnapshot, TaplStatus, TaplItem, TaplArchive, TaplEvent, TaplSearchResult, TaplSearchPayload, TaplArchiveDetail, TaplItemDetail, WebviewView, HostMessage as HostWebviewMessage } from './viewer/types';

type NodeKind = 'overview' | 'task' | 'archive' | 'empty';

type PanelView = (
  | { type: 'run'; runId: string }
  | { type: 'records'; query: string; scope: 'all' | 'run'; runId?: string; offset: number; limit: number }
  | { type: 'overview' | 'debug' }
  | { type: 'archive' | 'archiveEvents'; archiveId: string }
  | { type: 'search'; query: string }
  | { type: 'searchItem'; itemId: number }
  | { type: 'memories'; query: string; offset: number }
  | { type: 'memory' | 'memorySource'; memoryId: string }) & { source_db?: string };

type RunSelection = { runId: string; source_db?: string };
type TaplMcpResult = { ok: true; value: Record<string, unknown> } | { ok: false; error: string };

const COMMAND_PREFIX = "taplWorkflow";
const TAPL_DB_WATCH_DEBOUNCE_MS = 2000;
let taplMcpClients: TaplMcpClientPool | undefined;
let selectedWorkspacePath: string | undefined;
const selectedRuns = new Map<string, RunSelection>();
// Keep the transport command stable until a save acknowledgement has been delivered.
const settingsWriteConfigs = new Map<string, ViewerConfig>();

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
  const revisions = new DatabaseRevisions();
  const observeRead = async (workspace: string | undefined, before: string | undefined, valid: () => boolean) => {
    if (workspace && !await revisions.observe(workspace, before, valid)) { refreshQueue.schedule(workspace, true); }
  };
  // Tree notifications do not await getChildren. Check standalone tree reads for
  // concurrent changes; only a full refresh round advances the shared revision.
  const observeTreeRead = async (workspace: string | undefined, before: string | undefined, valid: () => boolean) => {
    if (!webviewManager.hasPanel()) { await observeRead(workspace, before, () => !webviewManager.hasPanel() && valid()); }
  };
  const activeProvider = new ActiveProvider(revisions, observeTreeRead);
  const archiveProvider = new ArchiveProvider(revisions, observeTreeRead);
  const webviewManager = new WorkflowWebviewManager(context.extensionUri, () => {
    taplMcpClients?.invalidate();
    void refreshAll();
  }, revisions, observeRead, () => refreshAll(), () => refreshTrees(), context.globalState);

  const refreshTrees = () => {
    activeProvider.refresh();
    archiveProvider.refresh();
  };
  const refreshQueue = new ViewerRefreshQueue(
    () => getWorkspaceRoot()?.uri.fsPath, revisions,
    async () => { refreshTrees(); await webviewManager.refresh(); },
    TAPL_DB_WATCH_DEBOUNCE_MS
  );
  const refreshAll = () => refreshQueue.request(true);

  context.subscriptions.push(
    refreshQueue,
    { dispose: () => taplMcpClients?.invalidate() },
    vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.active`, activeProvider),
    vscode.window.registerTreeDataProvider(`${COMMAND_PREFIX}.archives`, archiveProvider),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.refresh`, refreshAll),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.openOverview`, async () => {
      await webviewManager.openOverview();
    }),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.showTour`, () => webviewManager.showTour()),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.openArchive`, async (node?: unknown) => {
      if (node instanceof WorkflowNode && node.archive) {
        await webviewManager.openArchive(node.archive);
      }
    }),
    vscode.commands.registerCommand(`${COMMAND_PREFIX}.search`, async () => {
      await webviewManager.searchFromCommand();
    }),
    // VS Code preferences are intentionally not used for TAPL configuration.
    // Workspace trust is enforced before launching a workspace-selected executable.
    ...(vscode.workspace.onDidGrantWorkspaceTrust ? [vscode.workspace.onDidGrantWorkspaceTrust(() => webviewManager.configurationChanged())] : [])
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
      for (const pattern of ['.tapl/tapl.db', '.tapl/tapl.db-wal', '.tapl/tapl-*.db', '.tapl/tapl-*.db-wal']) {
        const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, pattern));
        watchers.push(watcher, watcher.onDidChange(() => refreshQueue.schedule(root.uri.fsPath)), watcher.onDidCreate(() => refreshQueue.schedule(root.uri.fsPath)), watcher.onDidDelete(() => refreshQueue.schedule(root.uri.fsPath)));
      }
      const configWatcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, '.tapl/config.toml'));
      const configChanged = () => webviewManager.configurationChanged();
      watchers.push(configWatcher, configWatcher.onDidChange(configChanged), configWatcher.onDidCreate(configChanged), configWatcher.onDidDelete(configChanged));
      workspaceWatchers.set(root.uri.fsPath, watchers);
    }
  };
  syncWatchers();
  // Watch even a missing user file so creation and local-file deletion update fallback.
  const userConfigWatcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(homedir(), '.tapl/config.toml'));
  const userConfigChanged = () => webviewManager.configurationChanged();
  context.subscriptions.push(
    userConfigWatcher, userConfigWatcher.onDidChange(userConfigChanged), userConfigWatcher.onDidCreate(userConfigChanged), userConfigWatcher.onDidDelete(userConfigChanged),
    { dispose: () => { for (const watchers of workspaceWatchers.values()) { watchers.forEach((watcher) => watcher.dispose()); } } },
    ...(vscode.window.onDidChangeWindowState ? [vscode.window.onDidChangeWindowState((state) => {
      if (state.focused) {
        if (!webviewManager.resume()) { void refreshQueue.request(); }
      }
    })] : []),
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      syncWatchers();
      webviewManager.resetWorkspace();
      void refreshAll();
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
  constructor(private readonly revisions: DatabaseRevisions,
    private readonly observeRead: (workspace: string | undefined, before: string | undefined, valid: () => boolean) => Promise<void>) {}

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
    const workspace = getWorkspaceRoot()?.uri.fsPath;
    const before = workspace ? await this.revisions.read(workspace) : undefined;
    const result = await safeStatus();
    await this.observeRead(workspace, before, () => result.ok && workspace === getWorkspaceRoot()?.uri.fsPath);
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
  constructor(private readonly revisions: DatabaseRevisions,
    private readonly observeRead: (workspace: string | undefined, before: string | undefined, valid: () => boolean) => Promise<void>) {}

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
    const workspace = getWorkspaceRoot()?.uri.fsPath;
    const before = workspace ? await this.revisions.read(workspace) : undefined;
    const result = await safeArchives();
    await this.observeRead(workspace, before, () => result.ok && workspace === getWorkspaceRoot()?.uri.fsPath);
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
  private reconnectOnOpen = false;
  private shellProbe?: { root?: vscode.WorkspaceFolder; promise: Promise<void> };
  private installed?: InstalledViewerBundle & { channel: string; workspace: TaplMcpWorkspace };
  private installedSelection = 0;
  private pendingNavigation?: InstalledViewerNavigation['message'];
  private resetInstalledWorkspace = false;
  private generation = 0;
  private capabilities: HostCapabilities = { associativeMemory: false };
  private discardPending = false;
  private settingsGeneration = 0;
  private settingsWorkspaceGeneration = 0;
  private settingsWritePending = false;
  private settingsRevision: { workspace: string; revision: string } | undefined;
  private tourPanel = { historyReady: false, hydrated: false, openRequested: false, opening: false };
  private tourHistory: TourHistory = {};
  private tourHistoryWrite = Promise.resolve();

  private deferredConfigRefresh = false;
  private deferredPanelRefresh = false;
  private deferredDiscardResult: { workspace: string | undefined; result: RunDiscardResult } | undefined;

  constructor(private readonly extensionUri: vscode.Uri, private readonly refreshConfiguration: () => void,
    private readonly revisions: DatabaseRevisions,
    private readonly observeRead: (workspace: string | undefined, before: string | undefined, valid: () => boolean) => Promise<void>,
    private readonly requestRefresh: () => Promise<void>, private readonly refreshTreeViews: () => void,
    private readonly globalState: vscode.ExtensionContext['globalState']) {}

  hasPanel(): boolean { return this.panel !== undefined; }

  panelVisible(): boolean {
    return this.panel !== undefined && this.panel.visible !== false;
  }

  resume(): boolean {
    if (!this.panelVisible()) { return false; }
    void this.postTourOpen(this.panel);
    if (!this.deferredPanelRefresh) { return false; }
    this.deferredPanelRefresh = false;
    void this.requestRefresh();
    return true;
  }

  configurationChanged(): void {
    if (this.settingsWritePending) {
      this.deferredConfigRefresh = true;
      return;
    }
    this.deferredConfigRefresh = false;
    this.shellProbe = undefined;
    this.refreshConfiguration();
  }

  async openOverview(): Promise<void> {
    this.backStack.length = 0;
    await this.navigate({ type: 'overview' }, { reveal: true });
  }

  async showTour(): Promise<void> {
    const panel = this.ensurePanel(true);
    this.tourPanel.openRequested = true;
    await this.initializeShell(panel);
    await this.postTourOpen(panel);
  }

  async openArchive(archive: TaplArchive): Promise<void> {
    await this.navigate({ type: 'archive', archiveId: archive.id, source_db: archive.source_db }, { pushHistory: this.panel !== undefined, reveal: true });
  }

  resetWorkspace(): void {
    this.settingsWorkspaceGeneration += 1;
    this.settingsRevision = undefined;
    this.generation += 1;
    this.backStack.length = 0;
    this.currentView = { type: 'overview' };
    this.pendingNavigation = undefined;
    this.resetInstalledWorkspace = this.installed !== undefined;
    this.capabilities = { associativeMemory: false };
  }

  async refresh(): Promise<void> {
    const panel = this.panel;
    if (!panel) return;
    await this.initializeShell(panel);
    if (this.panel !== panel) return;
    panel.title = workspaceTaplTitle();
    if (this.installed) await this.navigateInstalled(panel, { command: 'refresh' });
    else await this.postCurrentView('view:update');
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
    await this.initializeShell(panel);
    if (panel !== this.panel || this.currentView !== view) return;
    if (this.installed) {
      if (view.type === 'archive') await this.navigateInstalled(panel, { command: 'openArchive', archiveId: view.archiveId, source_db: view.source_db });
      else if (view.type === 'search') await this.navigateInstalled(panel, { command: 'search', query: view.query });
      else await this.navigateInstalled(panel, { command: 'ready' });
      return;
    }
    await this.postCurrentView('view:update');
  }

  private initializeShell(panel: vscode.WebviewPanel): Promise<void> {
    const root = getWorkspaceRoot();
    if (this.shellProbe && this.shellProbe.root === root) return this.shellProbe.promise;
    const promise = this.findInstalledViewer(root).then(candidate => {
      if (panel !== this.panel || this.shellProbe?.promise !== promise || getWorkspaceRoot() !== root) return;
      const previous = this.installed;
      const sameWorkspace = candidate?.workspace.key === previous?.workspace.key;
      if (this.shellReady && candidate?.assets === previous?.assets && candidate?.version === previous?.version
        && (sameWorkspace || this.tourPanel.hydrated)) {
        if (candidate && previous) {
          if (previous.workspace.key !== candidate.workspace.key) {
            this.pendingNavigation = undefined;
            this.resetInstalledWorkspace = true;
          }
          previous.workspace = candidate.workspace;
        }
        return;
      }
      this.installed = candidate && { ...candidate, channel: randomBytes(16).toString('hex') };
      this.pendingNavigation = undefined;
      this.resetInstalledWorkspace = false;
      this.tourPanel = { historyReady: false, hydrated: false, openRequested: this.tourPanel.openRequested, opening: false };
      this.generation += 1;
      const file = this.installed && vscode.Uri.file(this.installed.assets);
      const installedRoot = file && (this.extensionUri.scheme === 'vscode-remote' ? this.extensionUri.with({ path: file.path }) : file);
      const resourceRoot = installedRoot ?? vscode.Uri.joinPath(this.extensionUri, 'webview-dist', 'assets');
      panel.webview.options = { enableScripts: true, localResourceRoots: [resourceRoot] };
      panel.webview.html = this.renderShell(panel.webview, installedRoot, this.installed?.channel);
      this.shellReady = true;
    });
    this.shellProbe = { root, promise };
    return promise;
  }

  private async findInstalledViewer(root?: vscode.WorkspaceFolder) {
    if (!root || !taplMcpClients) return;
    try {
      const workspace = taplMcpWorkspace(root);
      const bundle = await installedViewerBundle(taplMcpClients, workspace);
      if (bundle) return { ...bundle, workspace };
    } catch { /* Older or unavailable installations use the VSIX renderer and its diagnostics. */ }
  }

  private async navigateInstalled(panel: vscode.WebviewPanel, command: InstalledViewerNavigation['message']): Promise<void> {
    const installed = this.installed;
    if (!installed || installed.workspace.key !== getWorkspaceRoot()?.uri.fsPath) return;
    if (!this.panelVisible() || !this.tourPanel.hydrated) {
      if (command.command !== 'refresh') this.pendingNavigation = command;
      if (!this.panelVisible()) this.deferredPanelRefresh = true;
      return;
    }
    const message = this.pendingNavigation ?? (this.resetInstalledWorkspace && command.command === 'refresh' ? { command: 'ready' } : command);
    const reset = this.resetInstalledWorkspace;
    this.resetInstalledWorkspace = false;
    this.pendingNavigation = undefined;
    await panel.webview.postMessage({ type: 'viewer:navigate', channel: installed.channel, message,
      ...(reset ? { reset: true } : {}) } satisfies InstalledViewerNavigation);
  }

  private async installedReady(panel: vscode.WebviewPanel): Promise<void> {
    this.tourPanel.hydrated = true;
    void this.postTourOpen(panel);
    if (this.pendingNavigation?.command === 'ready' && !this.resetInstalledWorkspace) this.pendingNavigation = undefined;
    if (this.pendingNavigation || this.resetInstalledWorkspace) await this.navigateInstalled(panel, { command: 'ready' });
  }

  private ensurePanel(reveal: boolean): vscode.WebviewPanel {
    if (this.panel) {
      if (reveal) { this.panel.reveal(vscode.ViewColumn.One); }
      return this.panel;
    }
    const root = getWorkspaceRoot();
    if (this.reconnectOnOpen && root) {
      if (this.settingsWritePending) this.deferredConfigRefresh = true;
      else taplMcpClients?.invalidate(root.uri.fsPath);
    }
    this.reconnectOnOpen = false;
    this.panel = vscode.window.createWebviewPanel('taplWorkflow.viewer', workspaceTaplTitle(), vscode.ViewColumn.One, {
      enableScripts: true,
      retainContextWhenHidden: true,
      localResourceRoots: []
    });
    const panel = this.panel;
    panel.webview.onDidReceiveMessage((message: unknown) => {
      if (this.panel === panel) return this.handleMessage(message);
    });
    this.panel.onDidChangeViewState?.(() => { this.resume(); });
    this.panel.onDidDispose(() => {
      this.settingsWorkspaceGeneration += 1;
      this.settingsRevision = undefined;
      this.generation += 1;
      this.panel = undefined;
      this.reconnectOnOpen = true;
      this.shellProbe = undefined;
      this.installed = undefined;
      this.pendingNavigation = undefined;
      this.shellReady = false;
      this.tourPanel = { historyReady: false, hydrated: false, openRequested: false, opening: false };
      this.deferredPanelRefresh = false;
      this.deferredDiscardResult = undefined;
    });
    return this.panel;
  }

  private readStoredTourHistory(): TourHistory {
    try {
      return normalizeTourHistory(this.globalState?.get(TOUR_HISTORY_KEY));
    } catch {
      return {};
    }
  }

  private async saveTourHistory(value: unknown): Promise<void> {
    const next = normalizeTourHistory(value);
    if (!next.intro && !next.releaseSeenThrough) return;
    this.tourHistory = mergeTourHistory(this.tourHistory, next);
    // Serialize profile writes so a slower save cannot overwrite newer progress.
    this.tourHistoryWrite = this.tourHistoryWrite.then(async () => {
      const stored = this.readStoredTourHistory();
      const history = mergeTourHistory(this.tourHistory, stored);
      this.tourHistory = history;
      if (stored.intro === history.intro && stored.releaseSeenThrough === history.releaseSeenThrough) return;
      try {
        await this.globalState?.update(TOUR_HISTORY_KEY, history);
      } catch { /* Keep progress available in memory for this host. */ }
    });
    await this.tourHistoryWrite;
  }

  private async sendTourHistory(panel: vscode.WebviewPanel): Promise<void> {
    const state = this.tourPanel;
    state.historyReady = false;
    state.hydrated = false;
    this.tourHistory = mergeTourHistory(this.tourHistory, this.readStoredTourHistory());
    try {
      state.historyReady = await panel.webview.postMessage({ type: 'tour:history', history: this.tourHistory } satisfies HostWebviewMessage);
    } catch { /* The panel can close before the message is delivered. */ }
  }

  private async hydratePanel(): Promise<void> {
    const panel = this.panel;
    if (!panel) return;
    await this.sendTourHistory(panel);
    if (panel === this.panel) await this.postCurrentView('hydrate');
  }

  private async postTourOpen(panel: vscode.WebviewPanel | undefined): Promise<void> {
    const state = this.tourPanel;
    if (!panel || panel !== this.panel || !this.panelVisible() || !state.historyReady || !state.hydrated || !state.openRequested || state.opening) return;
    state.opening = true;
    try {
      if (await panel.webview.postMessage({ type: 'tour:open' } satisfies HostWebviewMessage)) state.openRequested = false;
    } catch { /* Keep the request pending if the webview could not receive it. */ }
    finally { state.opening = false; }
  }

  private renderShell(webview: vscode.Webview, installedRoot?: vscode.Uri, channel?: string): string {
    const asset = (name: string) => webview.asWebviewUri(installedRoot
      ? vscode.Uri.joinPath(installedRoot, name)
      : vscode.Uri.joinPath(this.extensionUri, 'webview-dist', 'assets', name));
    const bridge = channel ? `<meta name="tapl-viewer-protocol" content="${INSTALLED_VIEWER_PROTOCOL}">
  <meta name="tapl-viewer-channel" content="${channel}">` : '';
    return `<!doctype html>
<html lang="${displayLocale()}">
<head>
  <meta charset="UTF-8">
  ${bridge}
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src ${webview.cspSource}; script-src ${webview.cspSource}; font-src ${webview.cspSource}; connect-src https://api.github.com;">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="${asset('index.css')}">
  <title>${localize('appTitle')}</title>
</head>
<body><div id="root"></div><script type="module" src="${asset('index.js')}"></script></body>
</html>`;
  }

  private async postCurrentView(type: 'hydrate' | 'view:update', discardResult?: RunDiscardResult): Promise<void> {
    const panel = this.panel;
    if (!panel) { return; }
    const generation = ++this.generation;
    if (discardResult) { this.deferredDiscardResult = { workspace: getWorkspaceRoot()?.uri.fsPath, result: discardResult }; }
    if (!this.panelVisible()) { this.deferredPanelRefresh = true; return; }
    this.deferredPanelRefresh = false;
    const root = getWorkspaceRoot();
    const workspace = root?.uri.fsPath;
    const before = workspace ? await this.revisions.read(workspace) : undefined;
    if (generation !== this.generation || panel !== this.panel || root !== getWorkspaceRoot()) { return; }
    if (!this.panelVisible()) { this.deferredPanelRefresh = true; return; }
    const view = await this.buildCurrentView(this.currentView);
    // A slow read must not replace a newer navigation, workspace or closed panel.
    if (generation !== this.generation || panel !== this.panel || root !== getWorkspaceRoot()) { return; }
    if (!this.panelVisible()) { this.deferredPanelRefresh = true; return; }
    if (view.type === 'overview' || view.type === 'debug') {
      const activeRun = view.status.active_run;
      if (workspace && activeRun?.id) {
        selectedRuns.set(workspace, { runId: activeRun.id, source_db: activeRun.source_db ?? view.status.source_db });
      }
      this.capabilities = {
        associativeMemory: view.status.viewer_capabilities?.associativeMemory === true,
        discardRun: view.status.viewer_capabilities?.discardRun === true
      };
    }
    panel.title = workspaceTaplTitle();
    const pendingDiscard = this.deferredDiscardResult;
    const pendingDiscardResult = pendingDiscard?.workspace === workspace ? pendingDiscard?.result : undefined;
    const message: HostWebviewMessage = {
      type, view, locale: displayLocale(), layout: displayLayout(),
      preferences: displayPreferences(),
      workspace: root?.uri.fsPath, capabilities: this.capabilities,
      ...(pendingDiscardResult ? { discardResult: pendingDiscardResult } : {})
    };
    const delivered = await panel.webview.postMessage(message);
    if (delivered && pendingDiscard === this.deferredDiscardResult) { this.deferredDiscardResult = undefined; }
    if (delivered && panel === this.panel && this.tourPanel.historyReady) {
      this.tourPanel.hydrated = true;
      void this.postTourOpen(panel);
    }
    await this.observeRead(workspace, before, () => delivered && view.type !== 'error'
      && generation === this.generation && panel === this.panel && this.panelVisible() && root === getWorkspaceRoot());
  }

  private async buildCurrentView(route: PanelView): Promise<WebviewView> {
    if (route.type === 'run') {
      const result = await callTaplMcp('tapl_get_run', { run_id: route.runId, ...(route.source_db ? { source_db: route.source_db } : {}) });
      return result.ok ? { type: 'run', snapshot: result.value as unknown as TaplRunSnapshot, workspace: getWorkspaceRoot()?.uri.fsPath }
        : { type: 'error', message: result.error };
    }
    if (route.type === 'records') {
      const result = await callTaplMcp('tapl_list_records', { query: route.query, scope: route.scope,
        offset: route.offset, limit: route.limit, ...(route.runId ? { run_id: route.runId } : {}),
        ...(route.source_db ? { source_db: route.source_db } : {}) });
      if (!result.ok) { return { type: 'error', message: result.error }; }
      const payload = result.value;
      const context = route.scope === 'run' ? await readRunContext(route.runId, route.source_db) : undefined;
      return { ...payload, type: 'records', query: route.query, scope: route.scope,
        runId: route.scope === 'run' ? route.runId : undefined,
        source_db: typeof payload.source_db === 'string' ? payload.source_db : undefined,
        offset: route.offset, limit: route.limit, total: Number(payload.total ?? 0),
        records: payload.records ?? [], runs: payload.runs ?? [], ...(context ? { context } : {}) } as Extract<WebviewView, { type: 'records' }>;
    }
    if (route.type === 'archive' || route.type === 'archiveEvents') {
      const detail = await safeArchiveDetail(route.archiveId, route.source_db);
      if (!detail.ok) { return { type: 'error', message: detail.error }; }
      const context = await readRunContext(detail.value.archive.run_id, detail.value.archive.source_db ?? route.source_db);
      return { type: route.type, archive: detail.value.archive, detail: detail.value, ...(context ? { context } : {}) };
    }
    if (route.type === 'search') {
      const result = await searchTapl(route.query);
      return result.ok ? { type: 'search', search: result.value } : { type: 'error', message: result.error };
    }
    if (route.type === 'searchItem') {
      return this.itemView(route.itemId, route.source_db);
    }
    if (route.type === 'memories') {
      const result = await callTaplMcp('tapl_recall', { query: route.query, offset: route.offset, limit: 50 });
      if (!result.ok) { return { type: 'error', message: result.error }; }
      const payload = result.value;
      return { type: 'memories', query: route.query, offset: route.offset, limit: 50,
        total: Number(payload.total ?? 0), memories: (payload.memories ?? []) as AssociativeMemory[],
        ...(payload.diagnostics ? { diagnostics: payload.diagnostics as unknown as MemoryDiagnostics } : {}) };
    }
    if (route.type === 'memory' || route.type === 'memorySource') {
      const result = await callTaplMcp('tapl_get_memory', { memory_id: route.memoryId, ...(route.source_db ? { source_db: route.source_db } : {}) });
      if (!result.ok) { return { type: 'error', message: result.error }; }
      const memory = (result.value.memory ?? null) as AssociativeMemory | null;
      const source = memory?.source_record;
      if (route.type === 'memorySource' && memory?.source_available && source) {
        if (source.kind === 'item' && source.item) { return this.itemView(source.item.id, memory.source_db ?? route.source_db); }
        if (source.kind === 'run' && source.run) {
          const context = await readRunContext(source.run.id, memory.source_db ?? route.source_db);
          return { type: 'memorySource', memoryId: route.memoryId, run: source.run, source_db: memory.source_db ?? route.source_db,
            ...(context ? { context } : {}) };
        }
      }
      return { type: 'memory', memoryId: route.memoryId, memory, source_db: memory?.source_db ?? route.source_db };
    }
    const status = await safeStatus({ full: true, includeEvents: route.type === 'debug' });
    if (!status.ok) { return { type: 'error', message: status.error }; }
    if (route.type === 'debug') { return { type: 'debug', status: status.value }; }
    const archives = await safeArchives(8);
    return archives.ok
      ? { type: 'overview', status: status.value, archives: archives.value, searchQuery: this.lastSearchQuery, workspace: getWorkspaceRoot()?.uri.fsPath }
      : { type: 'error', message: archives.error };
  }

  private async itemView(itemId: number, sourceDb?: string): Promise<WebviewView> {
    const detail = await safeItemDetail(itemId, sourceDb);
    if (!detail.ok) { return { type: 'error', message: detail.error }; }
    const context = await readRunContext(detail.value.run_id, detail.value.source_db ?? sourceDb);
    const item = await enrichTaskDetail(detail.value, context);
    return { type: 'searchItem', result: searchResultFromItem(item), detail: item, ...(context ? { context } : {}) };
  }

  private async runSearch(query: string, reveal = false): Promise<void> {
    const trimmed = query.trim();
    if (!trimmed) { return; }
    this.lastSearchQuery = trimmed;
    await this.navigate({ type: 'search', query: trimmed }, { pushHistory: this.currentView.type !== 'search', reveal });
  }

  private async handleMessage(message: unknown): Promise<void> {
    if (!isRecord(message) || typeof message.command !== 'string') { return; }
    if (this.installed && message.command !== 'chooseWorkspace' && message.command !== 'saveTourHistory') {
      if (message.command === 'viewerRequest') await this.dispatchInstalled(message);
      return;
    }
    switch (message.command) {
      case 'ready': await this.hydratePanel(); return;
      case 'saveTourHistory': await this.saveTourHistory(message.history); return;
      case 'refresh': await this.requestRefresh(); return;
      case 'discardRun': await this.discardRun(message); return;
      case 'getSettings':
      case 'saveSettings':
      case 'resetSettings': await this.settingsRequest(message); return;
      case 'openRun':
        if (typeof message.runId === 'string' && message.runId && message.runId.length <= 256) {
          await this.navigate({ type: 'run', runId: message.runId,
            source_db: typeof message.source_db === 'string' ? message.source_db : undefined }, { pushHistory: true });
        }
        return;
      case 'records': {
        const query = message.query ?? '', scope = message.scope ?? 'all';
        const offset = message.offset ?? 0, limit = message.limit ?? 50;
        if (typeof query !== 'string' || query.length > 500 || (scope !== 'all' && scope !== 'run')
          || typeof offset !== 'number' || !Number.isInteger(offset) || offset < 0 || offset > 1000000
          || typeof limit !== 'number' || !Number.isInteger(limit) || limit < 1 || limit > 50
          || (scope === 'run' && (typeof message.runId !== 'string' || !message.runId || message.runId.length > 256))) { return; }
        await this.navigate({ type: 'records', query, scope, offset, limit,
          runId: scope === 'run' ? message.runId as string : undefined,
          source_db: typeof message.source_db === 'string' ? message.source_db : undefined },
          { pushHistory: this.currentView.type !== 'records' });
        return;
      }
      case 'selectRun': {
        const root = getWorkspaceRoot();
        if (!root) return;
        if (typeof message.runId === 'string' && message.runId && message.runId.length <= 256) {
          selectedRuns.set(root.uri.fsPath, { runId: message.runId,
            source_db: typeof message.source_db === 'string' ? message.source_db : undefined });
        } else if (message.runId === undefined && message.sessionId === '' && message.source_db === undefined) {
          selectedRuns.delete(root.uri.fsPath);
        } else return;
        await this.openOverview();
        this.refreshTreeViews();
        return;
      }
      case 'back': await this.navigate(this.backStack.pop() ?? { type: 'overview' }); return;
      case 'chooseWorkspace': {
        const root = await vscode.window.showWorkspaceFolderPick();
        if (root) {
          if (root.uri.fsPath !== getWorkspaceRoot()?.uri.fsPath) {
            this.settingsWorkspaceGeneration += 1;
            this.settingsRevision = undefined;
          }
          selectedWorkspacePath = root.uri.fsPath;
          this.capabilities = { associativeMemory: false };
          await this.openOverview();
          this.refreshTreeViews();
        }
        return;
      }
      case 'debug': await this.navigate({ type: 'debug' }, { pushHistory: true }); return;
      case 'archiveEvents':
      case 'openArchive':
        if (typeof message.archiveId === 'string' && message.archiveId) {
          await this.navigate({ type: message.command === 'archiveEvents' ? 'archiveEvents' : 'archive', archiveId: message.archiveId, source_db: typeof message.source_db === "string" ? message.source_db : undefined }, { pushHistory: true });
        }
        return;
      case 'search': if (typeof message.query === 'string') { await this.runSearch(message.query); } return;
      case 'openSearchResult':
        if (typeof message.itemId === 'number' && Number.isInteger(message.itemId) && message.itemId > 0) {
          await this.navigate({ type: 'searchItem', itemId: message.itemId, source_db: typeof message.source_db === "string" ? message.source_db : undefined }, { pushHistory: true });
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
          await this.navigate({ type: message.command === 'openMemory' ? 'memory' : 'memorySource', memoryId: message.memoryId, source_db: typeof message.source_db === "string" ? message.source_db : undefined }, { pushHistory: true });
        }
        return;
    }
  }

  private async dispatchInstalled(request: Record<string, unknown>): Promise<void> {
    const panel = this.panel, installed = this.installed, root = getWorkspaceRoot();
    const { requestId, message } = request;
    if (!panel || !installed || !root || request.protocol !== INSTALLED_VIEWER_PROTOCOL || request.channel !== installed.channel
      || typeof requestId !== 'string' || !requestId || requestId.length > 128
      || !isRecord(message) || Array.isArray(message) || typeof message.command !== 'string') return;
    const workspace = installed.workspace;
    await this.initializeShell(panel);
    const current = () => this.panel === panel && this.installed === installed && getWorkspaceRoot() === root
      && installed.workspace.key === workspace.key && workspace.key === root.uri.fsPath;
    if (!current() || !taplMcpClients) return;
    const response = { type: 'viewer:response', channel: installed.channel, requestId };
    const command = message.command;
    const selection = ['selectRun', 'discardRun', 'ready'].includes(command) ? ++this.installedSelection : undefined;
    const writingSettings = command === 'saveSettings' || command === 'resetSettings';
    if (writingSettings && this.settingsWritePending) {
      await panel.webview.postMessage({ ...response, error: 'A settings write is already in progress.' });
      return;
    }
    try {
      if (writingSettings) {
        this.settingsWritePending = true;
        settingsWriteConfigs.set(workspace.key, loadViewerConfig(workspace.key));
      }
      if (command === 'ready') await this.sendTourHistory(panel);
      if (!current()) return;
      const before = command === 'revision' ? undefined : await this.revisions.read(workspace.key);
      if (!current()) return;
      const payload = await taplMcpClients.callTool(installed.workspace, 'tapl_viewer_dispatch', {
        protocol: INSTALLED_VIEWER_PROTOCOL, message: { ...message, locale: vscode.env.language }
      });
      if (!current()) return;
      const delivered = await panel.webview.postMessage({ ...response, payload });
      if (!current() || !delivered) return;
      if (command === 'ready') await this.installedReady(panel);
      if (selection === this.installedSelection && current()) {
        const view = payload.view;
        if (isRecord(view) && view.type === 'overview' && isRecord(view.status)) {
          const run = view.status.active_run;
          if (isRecord(run) && typeof run.id === 'string') {
            const source = run.source_db ?? view.status.source_db;
            selectedRuns.set(workspace.key, { runId: run.id, source_db: typeof source === 'string' ? source : undefined });
          } else selectedRuns.delete(workspace.key);
          this.refreshTreeViews();
        }
      }
      if (payload.type === 'hydrate' || payload.type === 'view:update') {
        await this.observeRead(workspace.key, before, current);
      }
    } catch (error) {
      if (current()) {
        const delivered = await panel.webview.postMessage({ ...response, error: error instanceof Error ? error.message : String(error) });
        if (delivered && current() && command === 'ready') await this.installedReady(panel);
      }
    } finally {
      if (writingSettings) {
        settingsWriteConfigs.delete(workspace.key);
        this.settingsWritePending = false;
        if (this.deferredConfigRefresh) this.configurationChanged();
      }
    }
  }

  private async settingsRequest(message: Record<string, unknown>): Promise<void> {
    const panel = this.panel, root = getWorkspaceRoot();
    if (!panel) return;
    const workspace = root?.uri.fsPath ?? '';
    const requestId = typeof message.requestId === 'string' ? message.requestId : '';
    const action = message.command === 'getSettings' ? 'get' : message.command === 'saveSettings' ? 'save' : 'reset';
    const workspaceGeneration = this.settingsWorkspaceGeneration;
    const inWorkspace = () => panel === this.panel && root === getWorkspaceRoot()
      && workspaceGeneration === this.settingsWorkspaceGeneration;
    const reply = async (result: Omit<SettingsResult, 'type' | 'requestId' | 'workspace' | 'action'>) => {
      if (inWorkspace()) await panel.webview.postMessage({ type: 'settings:result', requestId, workspace, action,
        locale: displayLocale(), layout: displayLayout(), preferences: displayPreferences(), ...result } satisfies SettingsResult);
    };
    if (!requestId || requestId.length > 128 || !root || (message.workspace !== undefined && message.workspace !== workspace)) {
      await reply({ ok: false, code: 'workspace_mismatch', message: 'Settings require the current workspace and a request ID.' }); return;
    }
    if (this.settingsWritePending) {
      await reply({ ok: false, code: 'busy', message: 'A settings write is already in progress.' }); return;
    }
    const revision = message.revision;
    if (action !== 'get' && (message.workspace !== workspace || typeof revision !== 'string' || !revision
      || this.settingsRevision?.workspace !== workspace || this.settingsRevision.revision !== revision
      || (action === 'reset' && message.confirmed !== true)
      || (action === 'save' && (!isRecord(message.values) || Array.isArray(message.values))))) {
      await reply({ ok: false, code: 'invalid_request', message: 'Reload settings before saving; reset also requires explicit confirmation.' }); return;
    }
    const generation = ++this.settingsGeneration;
    this.settingsWritePending = action !== 'get';
    try {
      if (action !== 'get') {
        try { settingsWriteConfigs.set(workspace, loadViewerConfig(workspace)); }
        catch (error) {
          await reply({ ok: false, code: 'invalid_settings', message: error instanceof Error ? error.message : String(error) });
          return;
        }
      }
      // Configuration belongs to this workspace, independent of selected RUN and source database.
      if (!inWorkspace()) return;
      const result = action === 'get'
        ? await callTaplMcp('tapl_get_settings', {}, root)
        : await callTaplMcp('tapl_save_settings', {
          expected_revision: revision, values: action === 'reset' ? {} : message.values,
          ...(action === 'reset' ? { reset_all: true } : {})
        }, root);
      if (!inWorkspace() || generation !== this.settingsGeneration) return;
      if (!result.ok || result.value.ok === false) {
        const text = result.ok ? String(result.value.error ?? result.value.message ?? 'Settings request failed.') : result.error;
        const unsupported = /unknown tool|not found|not supported|does not exist|unrecognized|not available/i.test(text);
        await reply({ ok: false, code: unsupported ? 'unsupported' : result.ok && typeof result.value.code === 'string' ? result.value.code : 'request_failed',
          message: unsupported ? 'This TAPL MCP server does not support settings. Update TAPL or set viewer.mcp_path in .tapl/config.toml, then restart the Viewer.' : text });
        return;
      }
      const settings = result.value.settings;
      if (!isRecord(settings) || typeof settings.revision !== 'string' || !Array.isArray(settings.fields)
        || !isRecord(settings.values) || !isRecord(settings.defaults)) {
        await reply({ ok: false, code: 'invalid_response', message: 'The TAPL MCP server returned an invalid settings document.' }); return;
      }
      this.settingsRevision = { workspace, revision: settings.revision };
      await reply({ ok: true, settings: settings as unknown as SettingsDocument,
        ...(typeof result.value.changed === 'boolean' ? { changed: result.value.changed } : {}) });
    } finally {
      if (action !== 'get') {
        settingsWriteConfigs.delete(workspace);
        this.settingsWritePending = false;
      }
      // Invalidate only after delivering the save reply, including when a watcher
      // observed the atomic config replacement before the MCP response arrived.
      if (this.deferredConfigRefresh) this.configurationChanged();
    }
  }

  private async discardRun(message: Record<string, unknown>): Promise<void> {
    const panel = this.panel;
    const root = getWorkspaceRoot();
    const runId = typeof message.runId === 'string' ? message.runId : '';
    const confirmationRunId = message.confirmationRunId;
    const targetSessionId = message.targetSessionId;
    const sourceDb = message.source_db;
    const workspace = message.workspace;
    const generation = this.generation;
    const error = async (text: string): Promise<void> => {
      if (panel && panel === this.panel && root === getWorkspaceRoot()) {
        await panel.webview.postMessage({ type: 'error', message: text, locale: displayLocale(), layout: displayLayout(),
          discardResult: { runId, ok: false, message: text } } satisfies HostWebviewMessage);
      }
    };
    if (!panel || !root) { return; }
    if (!this.capabilities.discardRun || this.discardPending || message.confirmed !== true || !runId.trim()
      || typeof sourceDb !== 'string' || !sourceDb
      || typeof confirmationRunId !== 'string' || confirmationRunId !== runId
      || typeof targetSessionId !== 'string' || targetSessionId.length > 256
      || targetSessionId !== targetSessionId.trim() || /[\x00-\x1f\x7f]/.test(targetSessionId)
      || workspace !== root.uri.fsPath) {
      await error('RUN discard requires the source database, complete matching RUN ID, explicit confirmation, and current workspace.');
      return;
    }
    this.discardPending = true;
    try {
      const result = await callTaplMcp('tapl_viewer_discard_run', {
        source_db: sourceDb, run_id: runId, target_session_id: targetSessionId,
        confirmed: true, confirmation_run_id: confirmationRunId
      }, root);
      if (root !== getWorkspaceRoot() || panel !== this.panel || workspace !== root.uri.fsPath) { return; }
      if (!result.ok || result.value.ok !== true) {
        await error(result.ok ? String(result.value.error ?? 'RUN discard failed.') : result.error);
        return;
      }
      const selected = selectedRuns.get(workspace);
      if (selected?.runId === runId && selected.source_db === sourceDb) {
        selectedRuns.delete(workspace);
      }
      if (generation === this.generation && this.currentView.type === 'run'
        && this.currentView.runId === runId && this.currentView.source_db === sourceDb) {
        this.backStack.length = 0;
        this.currentView = { type: 'overview' };
      }
      await this.postCurrentView('view:update', { runId, ok: true });
      if (root === getWorkspaceRoot() && panel === this.panel) {
        await vscode.commands.executeCommand(`${COMMAND_PREFIX}.refresh`);
      }
    } finally {
      this.discardPending = false;
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
  if (!root) return { ok: false, error: localize('openWorkspaceToUseTapl') };
  const selected = selectedRuns.get(root.uri.fsPath);
  const args = {
    full: options.full ?? false,
    include_events: options.includeEvents ?? false,
    events_limit: options.eventsLimit ?? 12
  };

  try {
    const clients = taplMcpClients ??= new TaplMcpClientPool();
    const workspace = taplMcpWorkspace(root);
    const supportsTool = (name: string) => clients.supportsTool?.(workspace, name);
    if (await supportsTool('tapl_viewer_get_status')) {
      const status = await readTaplStatus('tapl_viewer_get_status', {
        ...args, ...(selected ? runSelectionArgs(selected) : {})
      }, root);
      if (!status.ok) return status;
      status.value.viewer_capabilities = {
        associativeMemory: status.value.viewer_capabilities?.associativeMemory === true,
        discardRun: status.value.viewer_capabilities?.discardRun !== false && await supportsTool('tapl_viewer_discard_run') === true
      };
      return status;
    }
  } catch (error) {
    return taplMcpFailure(error);
  }

  const initial = await readTaplStatus('tapl_get_status', args, root);
  if (!initial.ok) return initial;
  const status = initial.value;
  status.viewer_capabilities = { associativeMemory: status.viewer_capabilities?.associativeMemory === true, discardRun: false };
  const firstRun = status.active_runs?.[0];
  const selection = selected ?? (!status.active_run && firstRun?.id
    ? { runId: firstRun.id, source_db: firstRun.source_db }
    : undefined);
  if (!selection) return initial;

  const exact = await callTaplMcp('tapl_get_run', runSelectionArgs(selection), root);
  if (!exact.ok) return exact;
  const snapshot = exact.value as unknown as TaplRunSnapshot;
  const sourceDb = snapshot.run?.source_db ?? snapshot.source_db ?? selection.source_db;
  if (exact.value.ok === false || snapshot.run?.id !== selection.runId
    || (selection.source_db !== undefined && selection.source_db !== sourceDb)) {
    return { ok: false, error: String(exact.value.error ?? 'The TAPL MCP server returned an invalid RUN snapshot.') };
  }
  const { run, tasks = [], plans = [], findings = [], task_counts = {}, active_batches = [], active_executions = [],
    active_runs, references } = snapshot;
  const initialRun = status.active_run;
  const initialSource = initialRun?.source_db ?? status.source_db;
  const sameRun = initialRun?.id === selection.runId && initialSource === sourceDb;
  const sharedStatus = sameRun ? status : {
    ...DEFAULT_STATUS, schema: initialSource === sourceDb ? status.schema : DEFAULT_STATUS.schema,
    config: status.config, reference_limits: status.reference_limits,
    source_errors: status.source_errors, viewer_capabilities: status.viewer_capabilities,
    counts: { archives: status.counts?.archives }
  };
  return {
    ok: true,
    value: {
      ...sharedStatus, active_run: run, session_id: run.session_id, source_db: sourceDb,
      tasks, plans, findings, task_counts, active_batches, active_executions, references,
      active_runs: active_runs ?? status.active_runs,
      incomplete_tasks: (task_counts.Pending ?? 0) + (task_counts['In Progress'] ?? 0) + (task_counts.Blocked ?? 0),
      counts: { ...sharedStatus.counts, plans: plans.length, tasks: tasks.length, findings: findings.length,
        active_batches: active_batches.length, active_executions: active_executions.length }
    }
  };
}

function runSelectionArgs({ runId, source_db }: RunSelection): Record<string, unknown> {
  return { run_id: runId, ...(source_db ? { source_db } : {}) };
}

async function readTaplStatus(tool: 'tapl_get_status' | 'tapl_viewer_get_status', args: Record<string, unknown>,
  root: vscode.WorkspaceFolder): Promise<{ ok: true; value: TaplStatus } | { ok: false; error: string }> {
  const result = await callTaplMcp(tool, args, root);
  if (!result.ok) return result;
  if (result.value.ok === false) {
    return { ok: false, error: String(result.value.error ?? 'TAPL status request failed.') };
  }
  return { ok: true, value: { ...DEFAULT_STATUS, ...result.value as unknown as TaplStatus } };
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

async function safeArchiveDetail(archiveId: string, sourceDb?: string): Promise<{ ok: true; value: TaplArchiveDetail } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_get_archive', { archive_id: archiveId, ...(sourceDb ? { source_db: sourceDb } : {}) });
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

async function safeItemDetail(itemId: number, sourceDb?: string): Promise<{ ok: true; value: TaplItemDetail } | { ok: false; error: string }> {
  const result = await callTaplMcp('tapl_get_item', { item_id: itemId, ...(sourceDb ? { source_db: sourceDb } : {}) });
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

async function readRunContext(runId?: string, sourceDb?: string): Promise<TaplRunSnapshot | undefined> {
  if (!runId) { return undefined; }
  const result = await callTaplMcp('tapl_get_run', { run_id: runId, ...(sourceDb ? { source_db: sourceDb } : {}) });
  return result.ok ? result.value as unknown as TaplRunSnapshot : undefined;
}

async function enrichTaskDetail(detail: TaplItemDetail, context?: TaplRunSnapshot): Promise<TaplItemDetail> {
  if (detail.run_id && !context) { return detail; }
  if (detail.kind !== 'task' || detail.archived || detail.run_status === 'archived') {
    return detail;
  }
  const status = context ? { ok: true as const, value: context } : await safeStatus({ full: true });
  if (!status.ok) {
    return detail;
  }
  const task = status.value.tasks.find((candidate) => candidate.id === detail.id && candidate.source_db === detail.source_db);
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
    active_execution: task.active_execution,
    execution_timing: detail.execution_timing ?? task.execution_timing
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
  tool: 'tapl_get_status' | 'tapl_viewer_get_status' | 'tapl_get_run' | 'tapl_list_records' | 'tapl_get_item' | 'tapl_search_history' | 'tapl_list_archives' | 'tapl_get_archive' | 'tapl_recall' | 'tapl_get_memory' | 'tapl_viewer_discard_run' | 'tapl_get_settings' | 'tapl_save_settings',
  args: Record<string, unknown>,
  root: vscode.WorkspaceFolder | undefined = getWorkspaceRoot()
): Promise<TaplMcpResult> {
  if (!root) {
    return { ok: false, error: localize('openWorkspaceToUseTapl') };
  }
  try {
    const clients = taplMcpClients ??= new TaplMcpClientPool();
    return { ok: true, value: await clients.callTool(taplMcpWorkspace(root), tool, args) };
  } catch (error) {
    return taplMcpFailure(error);
  }
}

function taplMcpFailure(error: unknown): { ok: false; error: string } {
  const message = error instanceof Error ? error.message : String(error);
  return { ok: false, error: `${message} Set viewer.mcp_path in .tapl/config.toml to the tapl-mcp executable path if it is not on PATH.` };
}

function taplMcpWorkspace(root: vscode.WorkspaceFolder): TaplMcpWorkspace {
  const config = settingsWriteConfigs.get(root.uri.fsPath) ?? loadViewerConfig(root.uri.fsPath);
  if (viewerConfigRequiresTrust(config) && vscode.workspace.isTrusted === false) {
    throw new Error(`Trust this workspace before running viewer.mcp_path from ${config.path}.`);
  }
  return {
    key: root.uri.fsPath,
    cwd: root.uri.fsPath,
    commands: taplMcpCommandCandidates(config.preferences.mcp_path)
  };
}

function displayLocale(): SupportedLocale {
  const language = displayPreferences().language;
  return resolveLocale(language === 'auto' ? vscode.env.language : language);
}

function displayLayout(): DisplayLayout {
  return displayPreferences().layout;
}

function displayPreferences(): ViewerPreferences {
  try { return loadViewerConfig(getWorkspaceRoot()?.uri.fsPath).preferences; }
  catch {
    // Keep error messages renderable; MCP calls surface the selected-file error.
    return defaultViewerPreferences();
  }
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
    ...(item.run_id ? { run_id: item.run_id } : {}),
    stable_id: item.stable_id,
    kind: item.kind,
    title: item.title,
    status: item.status,
    source: item.source,
    source_db: item.source_db,
    snippet: item.body || item.raw_text,
    search_source: 'item'
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
