import { INSTALLED_VIEWER_PROTOCOL } from './types';
import type { BrowserApiCommand, HostMessage, InstalledViewerNavigation, InstalledViewerRequest, WebviewCommand } from './types';

export interface NativeVsCodeApi {
  postMessage(message: WebviewCommand | InstalledViewerRequest): unknown;
  getState(): unknown;
  setState(state: unknown): void;
}

type ViewerResponse = Pick<Response, 'ok' | 'status' | 'json'>;
type PendingRequest = {
  resolve: (response: ViewerResponse) => void;
  reject: (error: Error) => void;
  timer: number;
};

const REQUEST_TIMEOUT_MS = 30_000;

export function installedViewerChannel(): string | undefined {
  if (typeof document === 'undefined') return;
  const protocol = document.querySelector?.<HTMLMetaElement>('meta[name="tapl-viewer-protocol"]')?.content;
  const channel = document.querySelector?.<HTMLMetaElement>('meta[name="tapl-viewer-channel"]')?.content;
  if (protocol === String(INSTALLED_VIEWER_PROTOCOL) && channel && /^[a-f0-9]{32,128}$/.test(channel)) return channel;
}

export class InstalledViewerBridge {
  private readonly pending = new Map<string, PendingRequest>();
  private nextRequest = 0;
  private listener: ((message: HostMessage) => void) | undefined;

  constructor(
    readonly native: NativeVsCodeApi,
    private readonly channel: string,
    private readonly navigate: (navigation: InstalledViewerNavigation) => void
  ) {
    window.addEventListener('message', this.receive);
  }

  subscribe(listener: (message: HostMessage) => void): () => void {
    this.listener = listener;
    return () => { if (this.listener === listener) this.listener = undefined; };
  }

  publish(message: HostMessage): void {
    this.listener?.(message);
  }

  request(message: BrowserApiCommand): Promise<ViewerResponse> {
    const requestId = String(++this.nextRequest);
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.pending.delete(requestId);
        reject(new Error('The VS Code Viewer request timed out.'));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(requestId, { resolve, reject, timer });
      try {
        this.native.postMessage({ command: 'viewerRequest', protocol: INSTALLED_VIEWER_PROTOCOL,
          channel: this.channel, requestId, message });
      } catch (error) {
        this.take(requestId);
        reject(error);
      }
    });
  }

  reset(): void {
    for (const requestId of this.pending.keys()) {
      this.take(requestId)?.reject(new Error('The VS Code Viewer workspace changed.'));
    }
  }

  private take(requestId: string): PendingRequest | undefined {
    const request = this.pending.get(requestId);
    if (request) {
      this.pending.delete(requestId);
      window.clearTimeout(request.timer);
    }
    return request;
  }

  private readonly receive = ({ data }: MessageEvent): void => {
    if (!record(data)) return;
    if (data.type === 'tour:history' || data.type === 'tour:open') {
      this.publish(data as HostMessage);
      return;
    }
    // The editor's webview API supplies the sender. Match each message to this shell and request.
    if (data.channel !== this.channel) return;
    if (data.type === 'viewer:response' && typeof data.requestId === 'string') {
      const request = this.take(data.requestId);
      if (typeof data.error === 'string') request?.reject(new Error(data.error));
      else if (record(data.payload) && typeof data.payload.type === 'string') {
        request?.resolve({ ok: true, status: 200, json: async () => data.payload });
      } else request?.reject(new Error('The VS Code Viewer response was invalid.'));
    }
    if (data.type === 'viewer:navigate' && record(data.message) && typeof data.message.command === 'string'
      && ['ready', 'refresh', 'openArchive', 'search'].includes(data.message.command)) {
      this.navigate(data as unknown as InstalledViewerNavigation);
    }
  };
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
