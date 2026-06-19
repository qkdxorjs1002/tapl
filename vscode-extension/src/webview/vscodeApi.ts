import type { WebviewCommand } from './types';

type VsCodeApi = {
  postMessage: (message: WebviewCommand) => void;
  getState: () => unknown;
  setState: (state: unknown) => void;
};

declare const acquireVsCodeApi: (() => VsCodeApi) | undefined;

let api: VsCodeApi | undefined;

export function vscodeApi(): VsCodeApi {
  if (!api) {
    api = typeof acquireVsCodeApi === 'function'
      ? acquireVsCodeApi()
      : {
          postMessage: () => undefined,
          getState: () => undefined,
          setState: () => undefined
        };
  }
  return api;
}
