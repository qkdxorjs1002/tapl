import type {
  BrowserApiCommand,
  DisplayLayout,
  HostMessage,
  RevisionMessage,
  WebviewCommand,
  WebviewView
} from './types';

type VsCodeApi = {
  postMessage: (message: WebviewCommand) => void;
  getState: () => unknown;
  setState: (state: unknown) => void;
  setPollingActive?: (active: boolean) => void;
};

type PersistedState = {
  view?: WebviewView;
  locale?: 'en' | 'ko';
  layout?: DisplayLayout;
};

declare const acquireVsCodeApi: (() => VsCodeApi) | undefined;

const SESSION_STATE_KEY = 'tapl.viewer.state.v1';
const SESSION_HISTORY_KEY = 'tapl.viewer.history.v1';
const WORKSPACE_KEY = 'tapl.viewer.workspace.v1';

let api: VsCodeApi | undefined;

export function vscodeApi(): VsCodeApi {
  if (!api) {
    api = typeof acquireVsCodeApi === 'function'
      ? acquireVsCodeApi()
      : new BrowserApi();
  }
  return api;
}

class BrowserApi implements VsCodeApi {
  private state = readStorage<PersistedState>(sessionStorage, SESSION_STATE_KEY) ?? {};
  private history = readStorage<WebviewView[]>(sessionStorage, SESSION_HISTORY_KEY) ?? [];
  private activeWorkspace: string | undefined;
  private revisionBaseline: string | undefined;
  private revisionWorkspace: string | undefined;
  private pollingActive = false;
  private pollingTimer: number | undefined;
  private backgroundFailureCount = 0;
  private revisionInFlight = false;
  private refreshInFlight = false;
  private refreshDirty = false;
  private trailingRefreshIsManual = false;
  private autoRefreshPending = false;

  private readonly onVisibilityChange = (): void => {
    if (document.visibilityState === 'visible') {
      this.scheduleRevisionCheck(0);
    } else {
      this.clearRevisionTimer();
    }
  };

  postMessage(message: WebviewCommand): void {
    if (message.command === 'back') {
      this.goBack();
      return;
    }
    if (message.command === 'chooseWorkspace') {
      this.showWorkspaceChooser();
      return;
    }
    if (message.command === 'refresh') {
      this.requestRefresh(false);
      return;
    }
    void this.send(message);
  }

  getState(): unknown {
    return this.state;
  }

  setState(state: unknown): void {
    this.state = isRecord(state) ? state as PersistedState : {};
    writeStorage(sessionStorage, SESSION_STATE_KEY, this.state);
    this.scheduleRevisionCheck();
  }

  setPollingActive(active: boolean): void {
    if (this.pollingActive === active) {
      return;
    }
    this.pollingActive = active;
    if (active) {
      document.addEventListener('visibilitychange', this.onVisibilityChange);
      this.scheduleRevisionCheck();
      return;
    }
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.clearRevisionTimer();
  }

  private async send(
    message: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>,
    options: { background?: boolean } = {}
  ): Promise<boolean> {
    const previous = this.state.view;
    const recentWorkspace = readStorage<string>(localStorage, WORKSPACE_KEY) ?? '';
    const requestWorkspace = message.command === 'ready'
      ? ''
      : message.command === 'selectWorkspace'
        ? message.workspace.trim()
        : this.activeWorkspace ?? recentWorkspace;
    const request = {
      ...message,
      workspace: requestWorkspace,
      locale: navigator.language,
      layout: this.state.layout ?? 'auto',
      ...refreshContext(message, previous)
    };

    try {
      const response = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      });
      const payload = await response.json() as HostMessage;
      if (!response.ok) {
        throw new Error(payload.type === 'error' && typeof payload.message === 'string'
          ? payload.message
          : `Viewer request failed (${response.status}).`);
      }
      if (
        options.background
        && (payload.type === 'error' || ((payload.type === 'hydrate' || payload.type === 'view:update') && payload.view.type === 'error'))
      ) {
        return false;
      }
      if ((payload.type === 'hydrate' || payload.type === 'view:update') && 'workspace' in payload) {
        this.setActiveWorkspace(payload.workspace);
      }
      if (
        message.command === 'ready'
        && (payload.type === 'hydrate' || payload.type === 'view:update')
        && payload.view.type === 'workspace'
        && recentWorkspace
      ) {
        await this.send({ command: 'selectWorkspace', workspace: recentWorkspace });
        return true;
      }
      if (shouldPushHistory(message, previous, payload)) {
        this.history.push(previous as WebviewView);
        this.persistHistory();
      }
      dispatchHostMessage(payload);
      return true;
    } catch (error) {
      if (!options.background) {
        dispatchHostMessage({
          type: 'error',
          message: error instanceof Error ? error.message : 'The local viewer request failed.',
          locale: this.state.locale ?? resolveBrowserLocale(),
          layout: this.state.layout ?? 'auto'
        });
      }
      return false;
    }
  }

  private requestRefresh(background: boolean): void {
    if (this.refreshInFlight) {
      this.refreshDirty = true;
      this.trailingRefreshIsManual ||= !background;
      return;
    }
    this.refreshInFlight = true;
    void this.runRefresh(background);
  }

  private async runRefresh(initiallyBackground: boolean): Promise<void> {
    let background = initiallyBackground;
    try {
      do {
        this.refreshDirty = false;
        this.trailingRefreshIsManual = false;
        this.autoRefreshPending = false;
        const succeeded = await this.send({ command: 'refresh' }, { background });
        if (succeeded) {
          this.resetBackgroundBackoff();
        } else if (background) {
          if (this.refreshDirty && this.trailingRefreshIsManual) {
            background = false;
            continue;
          }
          this.autoRefreshPending = true;
          this.recordBackgroundFailure();
          break;
        }
        if (!this.refreshDirty) {
          break;
        }
        background = !this.trailingRefreshIsManual;
      } while (true);
    } finally {
      this.refreshInFlight = false;
      this.scheduleRevisionCheck();
    }
  }

  private scheduleRevisionCheck(delay = this.pollDelay()): void {
    if (!this.shouldPoll() || this.revisionInFlight) {
      this.clearRevisionTimer();
      return;
    }
    this.clearRevisionTimer();
    this.pollingTimer = window.setTimeout(() => {
      this.pollingTimer = undefined;
      void this.checkRevision();
    }, delay);
  }

  private async checkRevision(): Promise<void> {
    if (!this.shouldPoll() || this.revisionInFlight) {
      return;
    }
    this.revisionInFlight = true;
    try {
      const response = await fetch('/api/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.revisionRequest())
      });
      const payload: unknown = await response.json();
      if (!response.ok) {
        throw new Error(`Viewer revision request failed (${response.status}).`);
      }
      if (!isRevisionMessage(payload)) {
        throw new Error('Viewer revision response was invalid.');
      }
      if (payload.workspaceValid) {
        this.handleRevision(payload);
      } else {
        this.handleInvalidWorkspace(payload);
      }
      this.resetBackgroundBackoff();
    } catch {
      // Polling is opportunistic: leave the current screen intact and retry later.
      this.recordBackgroundFailure();
    } finally {
      this.revisionInFlight = false;
      this.scheduleRevisionCheck();
    }
  }

  private revisionRequest(): Extract<BrowserApiCommand, { command: 'revision' }> {
    return {
      command: 'revision',
      workspace: this.activeWorkspace ?? readStorage<string>(localStorage, WORKSPACE_KEY) ?? ''
    };
  }

  private handleRevision(message: RevisionMessage): void {
    if (this.revisionWorkspace !== message.workspace) {
      this.revisionWorkspace = message.workspace;
      this.revisionBaseline = undefined;
    }
    if (this.revisionBaseline === undefined) {
      this.revisionBaseline = message.revision;
      this.autoRefreshPending = true;
    } else if (this.revisionBaseline !== message.revision) {
      this.revisionBaseline = message.revision;
      this.autoRefreshPending = true;
    }
    if (this.autoRefreshPending) {
      this.requestRefresh(true);
    }
  }

  private handleInvalidWorkspace(message: RevisionMessage): void {
    this.activeWorkspace = undefined;
    this.resetRevisionBaseline();
    this.autoRefreshPending = false;
    dispatchHostMessage({
      type: 'view:update',
      view: {
        type: 'workspace',
        workspace: message.workspace,
        message: message.message
      },
      locale: this.state.locale ?? resolveBrowserLocale(),
      layout: this.state.layout ?? 'auto'
    });
  }

  private shouldPoll(): boolean {
    return this.pollingActive
      && document.visibilityState === 'visible'
      && !!this.state.view
      && this.state.view.type !== 'workspace';
  }

  private pollDelay(): number {
    return Math.min(1_000 * (2 ** this.backgroundFailureCount), 30_000);
  }

  private recordBackgroundFailure(): void {
    this.backgroundFailureCount = Math.min(this.backgroundFailureCount + 1, 5);
  }

  private resetBackgroundBackoff(): void {
    this.backgroundFailureCount = 0;
  }

  private clearRevisionTimer(): void {
    if (this.pollingTimer !== undefined) {
      window.clearTimeout(this.pollingTimer);
      this.pollingTimer = undefined;
    }
  }

  private resetRevisionBaseline(): void {
    this.revisionBaseline = undefined;
    this.revisionWorkspace = undefined;
  }

  private setActiveWorkspace(workspace: string | undefined): void {
    const nextWorkspace = workspace ?? '';
    if (this.activeWorkspace !== nextWorkspace) {
      this.activeWorkspace = nextWorkspace;
      this.resetRevisionBaseline();
    }
    if (nextWorkspace) {
      writeStorage(localStorage, WORKSPACE_KEY, nextWorkspace);
    }
  }

  private goBack(): void {
    const previous = this.history.pop();
    this.persistHistory();
    if (!previous) {
      void this.send({ command: 'ready' });
      return;
    }
    dispatchHostMessage({
      type: 'view:update',
      view: previous,
      locale: this.state.locale ?? resolveBrowserLocale(),
      layout: this.state.layout ?? 'auto'
    });
  }

  private showWorkspaceChooser(): void {
    this.resetRevisionBaseline();
    if (this.state.view && this.state.view.type !== 'workspace') {
      this.history.push(this.state.view);
      this.persistHistory();
    }
    dispatchHostMessage({
      type: 'view:update',
      view: {
        type: 'workspace',
        workspace: readStorage<string>(localStorage, WORKSPACE_KEY) ?? '',
        message: ''
      },
      locale: this.state.locale ?? resolveBrowserLocale(),
      layout: this.state.layout ?? 'auto'
    });
  }

  private persistHistory(): void {
    writeStorage(sessionStorage, SESSION_HISTORY_KEY, this.history.slice(-20));
  }
}

function refreshContext(
  message: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>,
  view: WebviewView | undefined
): Record<string, unknown> {
  if (message.command !== 'refresh' || !view) {
    return {};
  }
  if (view.type === 'archive' || view.type === 'archiveEvents') {
    return { viewType: view.type, archiveId: view.archive.id };
  }
  if (view.type === 'search') {
    return { viewType: view.type, query: view.search.query };
  }
  if (view.type === 'searchItem') {
    return { viewType: view.type, itemId: view.result.id };
  }
  return { viewType: view.type };
}

function shouldPushHistory(
  command: Exclude<WebviewCommand, { command: 'back' | 'chooseWorkspace' }>,
  previous: WebviewView | undefined,
  response: HostMessage
): boolean {
  if (!previous || command.command === 'ready' || command.command === 'refresh' || command.command === 'selectWorkspace') {
    return false;
  }
  return (response.type === 'hydrate' || response.type === 'view:update')
    && response.view.type !== 'error'
    && response.view.type !== 'workspace';
}

function resolveBrowserLocale(): 'en' | 'ko' {
  return navigator.language.toLowerCase().startsWith('ko') ? 'ko' : 'en';
}

function dispatchHostMessage(message: HostMessage): void {
  window.dispatchEvent(new MessageEvent('message', { data: message }));
}

function readStorage<T>(storage: Storage, key: string): T | undefined {
  try {
    const value = storage.getItem(key);
    return value ? JSON.parse(value) as T : undefined;
  } catch {
    return undefined;
  }
}

function writeStorage(storage: Storage, key: string, value: unknown): void {
  try {
    storage.setItem(key, JSON.stringify(value));
  } catch {
    // Private browsing or storage policy can disable persistence; the viewer still works.
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isRevisionMessage(value: unknown): value is RevisionMessage {
  return isRecord(value)
    && value.type === 'revision'
    && typeof value.revision === 'string'
    && typeof value.workspace === 'string'
    && typeof value.workspaceValid === 'boolean'
    && typeof value.message === 'string';
}
