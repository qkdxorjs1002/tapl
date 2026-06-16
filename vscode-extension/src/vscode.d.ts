declare module 'vscode' {
  export class Uri {
    scheme: string;
    path: string;
    fsPath: string;
    static parse(value: string): Uri;
    static joinPath(base: Uri, ...pathSegments: string[]): Uri;
  }

  export class ThemeIcon {
    constructor(id: string);
  }

  export class EventEmitter<T> {
    event: Event<T>;
    fire(data: T): void;
    dispose(): void;
  }

  export class TreeItem {
    label?: string | TreeItemLabel;
    description?: string | boolean;
    tooltip?: string;
    contextValue?: string;
    iconPath?: ThemeIcon;
    resourceUri?: Uri;
    command?: Command;
    collapsibleState?: TreeItemCollapsibleState;
    constructor(label: string, collapsibleState?: TreeItemCollapsibleState);
  }

  export class RelativePattern {
    constructor(base: WorkspaceFolder | Uri | string, pattern: string);
  }

  export enum TreeItemCollapsibleState {
    None = 0,
    Collapsed = 1,
    Expanded = 2
  }

  export enum FileType {
    Unknown = 0,
    File = 1,
    Directory = 2,
    SymbolicLink = 64
  }

  export enum ViewColumn {
    One = 1,
    Two = 2,
    Three = 3
  }

  export interface TreeItemLabel {
    label: string;
    highlights?: [number, number][];
  }

  export interface Command {
    command: string;
    title: string;
    arguments?: unknown[];
  }

  export interface Disposable {
    dispose(): void;
  }

  export interface ExtensionContext {
    subscriptions: Disposable[];
  }

  export interface WorkspaceFolder {
    uri: Uri;
    name: string;
    index: number;
  }

  export interface FileSystemWatcher extends Disposable {
    onDidChange(listener: (uri: Uri) => unknown): Disposable;
    onDidCreate(listener: (uri: Uri) => unknown): Disposable;
    onDidDelete(listener: (uri: Uri) => unknown): Disposable;
  }

  export interface Webview {
    html: string;
    cspSource: string;
    onDidReceiveMessage(listener: (message: unknown) => unknown): Disposable;
  }

  export interface WebviewOptions {
    enableScripts?: boolean;
  }

  export interface WebviewPanelOptions {
    retainContextWhenHidden?: boolean;
  }

  export interface WebviewPanel extends Disposable {
    title: string;
    webview: Webview;
    reveal(viewColumn?: ViewColumn): void;
    onDidDispose(listener: () => unknown): Disposable;
  }

  export interface FileStat {
    type: FileType;
  }

  export interface InputBoxOptions {
    prompt?: string;
    value?: string;
    placeHolder?: string;
  }

  export interface WorkspaceConfiguration {
    get<T>(section: string, defaultValue: T): T;
  }

  export type Event<T> = (listener: (e: T) => unknown) => Disposable;

  export interface TreeDataProvider<T> {
    onDidChangeTreeData?: Event<T | undefined | null | void>;
    getTreeItem(element: T): TreeItem;
    getChildren(element?: T): Thenable<T[]> | T[];
  }

  export type ProviderResult<T> = T | undefined | null | Thenable<T | undefined | null>;

  export namespace window {
    export function registerTreeDataProvider<T>(viewId: string, treeDataProvider: TreeDataProvider<T>): Disposable;
    export function createWebviewPanel(
      viewType: string,
      title: string,
      showOptions: ViewColumn,
      options?: WebviewPanelOptions & WebviewOptions
    ): WebviewPanel;
    export function showInformationMessage(message: string): Thenable<string | undefined>;
    export function showWarningMessage(message: string): Thenable<string | undefined>;
    export function showInputBox(options?: InputBoxOptions): Thenable<string | undefined>;
  }

  export namespace workspace {
    export const workspaceFolders: readonly WorkspaceFolder[] | undefined;
    export const fs: {
      stat(uri: Uri): Thenable<FileStat>;
      readDirectory(uri: Uri): Thenable<[string, FileType][]>;
      readFile(uri: Uri): Thenable<Uint8Array>;
    };
    export function getConfiguration(section?: string): WorkspaceConfiguration;
    export function createFileSystemWatcher(globPattern: RelativePattern): FileSystemWatcher;
  }

  export namespace commands {
    export function registerCommand(command: string, callback: (...args: unknown[]) => unknown): Disposable;
    export function executeCommand<T = unknown>(command: string, ...rest: unknown[]): Thenable<T>;
  }
}

declare class TextDecoder {
  constructor(label?: string);
  decode(input?: Uint8Array): string;
}

declare function setTimeout(handler: () => void, timeout?: number): number;
declare function clearTimeout(handle?: number): void;
declare const process: {
  env: Record<string, string | undefined>;
  platform: string;
};

declare module 'child_process' {
  export interface ExecFileOptions {
    cwd?: string;
    timeout?: number;
    env?: Record<string, string | undefined>;
  }

  export function execFile(
    command: string,
    args: readonly string[],
    options: ExecFileOptions,
    callback: (error: Error | null, stdout: string, stderr: string) => void
  ): void;
}

declare module 'path' {
  export function join(...paths: string[]): string;
}
