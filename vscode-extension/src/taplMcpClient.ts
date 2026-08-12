import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

const REQUEST_TIMEOUT_MS = 10_000;
const MAX_MESSAGE_BYTES = 16 * 1024 * 1024;

export interface TaplMcpWorkspace {
  key: string;
  cwd: string;
  commands: readonly string[];
}

export interface TaplMcpClientLike {
  onclose?: () => void;
  onerror?: (error: Error) => void;
  connect(transport: TaplMcpTransportLike, options?: { timeout?: number }): Promise<void>;
  callTool(
    params: { name: string; arguments?: Record<string, unknown> },
    resultSchema?: undefined,
    options?: { timeout?: number }
  ): Promise<{
    isError?: boolean;
    structuredContent?: Record<string, unknown>;
    content: Array<{ type: string; text?: string }>;
  }>;
  close(): Promise<void>;
}

export interface TaplMcpTransportLike {
  start(): Promise<void>;
  send(message: unknown): Promise<void>;
  close(): Promise<void>;
  onclose?: () => void;
  onerror?: (error: Error) => void;
  onmessage?: (message: never) => void;
}

export interface TaplMcpConnectionFactory {
  createClient(): TaplMcpClientLike;
  createTransport(command: string, cwd: string): TaplMcpTransportLike;
}

interface Connection {
  client: TaplMcpClientLike;
  command: string;
  closed: boolean;
}

export class TaplMcpToolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TaplMcpToolError';
  }
}

export class WorkspaceTaplMcpClient {
  private connection: Connection | undefined;
  private connecting: Promise<Connection> | undefined;
  private disposed = false;

  constructor(
    readonly workspace: TaplMcpWorkspace,
    private readonly factory: TaplMcpConnectionFactory = defaultConnectionFactory
  ) {}

  async callTool(name: string, args: Record<string, unknown> = {}): Promise<Record<string, unknown>> {
    let lastError: unknown;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const connection = await this.getConnection();
      try {
        const result = await connection.client.callTool(
          { name, arguments: args },
          undefined,
          { timeout: REQUEST_TIMEOUT_MS }
        );
        if (result.isError) {
          throw new TaplMcpToolError(toolResultMessage(result.content));
        }
        if (isRecord(result.structuredContent)) {
          return result.structuredContent;
        }
        const text = result.content.find((item) => item.type === 'text')?.text;
        if (text) {
          const parsed: unknown = JSON.parse(text);
          if (isRecord(parsed)) {
            return parsed;
          }
        }
        throw new Error(`${name} did not return structured object content.`);
      } catch (error) {
        if (error instanceof TaplMcpToolError) {
          throw error;
        }
        lastError = error;
        await this.invalidate(connection);
      }
    }
    throw asError(lastError, 'TAPL MCP request failed after restarting the server.');
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    const connection = this.connection;
    this.connection = undefined;
    if (connection) {
      connection.closed = true;
      await closeQuietly(connection.client);
    }
  }

  private async getConnection(): Promise<Connection> {
    if (this.disposed) {
      throw new Error('TAPL MCP client has been disposed.');
    }
    if (this.connection && !this.connection.closed) {
      return this.connection;
    }
    if (!this.connecting) {
      const starting = this.startConnection();
      this.connecting = starting;
      void starting.finally(() => {
        if (this.connecting === starting) {
          this.connecting = undefined;
        }
      }).catch(() => undefined);
    }
    const connection = await this.connecting;
    if (this.disposed) {
      connection.closed = true;
      await closeQuietly(connection.client);
      throw new Error('TAPL MCP client was disposed while starting.');
    }
    if (connection.closed) {
      throw new Error(`TAPL MCP server exited while starting: ${connection.command}`);
    }
    this.connection = connection;
    return connection;
  }

  private async startConnection(): Promise<Connection> {
    const failures: string[] = [];
    for (const command of this.workspace.commands) {
      const client = this.factory.createClient();
      const connection: Connection = { client, command, closed: false };
      client.onclose = () => {
        connection.closed = true;
        if (this.connection === connection) {
          this.connection = undefined;
        }
      };
      try {
        const transport = this.factory.createTransport(command, this.workspace.cwd);
        await client.connect(transport, { timeout: REQUEST_TIMEOUT_MS });
        if (!connection.closed) {
          return connection;
        }
        failures.push(`${command}: server exited during initialization`);
      } catch (error) {
        failures.push(`${command}: ${errorMessage(error)}`);
      }
      connection.closed = true;
      await closeQuietly(client);
    }
    throw new Error([
      'Unable to start the TAPL MCP server.',
      `Tried: ${this.workspace.commands.join(', ') || '(no command candidates)'}.`,
      failures.length ? `Last error: ${failures[failures.length - 1]}` : ''
    ].filter(Boolean).join(' '));
  }

  private async invalidate(connection: Connection): Promise<void> {
    connection.closed = true;
    if (this.connection === connection) {
      this.connection = undefined;
    }
    await closeQuietly(connection.client);
  }
}

export class TaplMcpClientPool {
  private readonly sessions = new Map<string, { fingerprint: string; session: WorkspaceTaplMcpClient }>();
  private disposed = false;

  constructor(private readonly factory: TaplMcpConnectionFactory = defaultConnectionFactory) {}

  async callTool(
    workspace: TaplMcpWorkspace,
    name: string,
    args: Record<string, unknown> = {}
  ): Promise<Record<string, unknown>> {
    if (this.disposed) {
      throw new Error('TAPL MCP client pool has been disposed.');
    }
    return this.sessionFor(workspace).callTool(name, args);
  }

  invalidate(workspaceKey?: string): void {
    if (workspaceKey !== undefined) {
      const existing = this.sessions.get(workspaceKey);
      this.sessions.delete(workspaceKey);
      if (existing) {
        void existing.session.dispose();
      }
      return;
    }
    const sessions = [...this.sessions.values()];
    this.sessions.clear();
    for (const { session } of sessions) {
      void session.dispose();
    }
  }

  async dispose(): Promise<void> {
    this.disposed = true;
    const sessions = [...this.sessions.values()];
    this.sessions.clear();
    await Promise.all(sessions.map(({ session }) => session.dispose()));
  }

  private sessionFor(workspace: TaplMcpWorkspace): WorkspaceTaplMcpClient {
    const fingerprint = JSON.stringify([workspace.cwd, ...workspace.commands]);
    const existing = this.sessions.get(workspace.key);
    if (existing?.fingerprint === fingerprint) {
      return existing.session;
    }
    if (existing) {
      void existing.session.dispose();
    }
    const session = new WorkspaceTaplMcpClient(workspace, this.factory);
    this.sessions.set(workspace.key, { fingerprint, session });
    return session;
  }
}

export function taplMcpCommandCandidates(
  configuredMcpPath: string,
  platform = process.platform
): string[] {
  const executable = platform === 'win32' ? 'tapl-mcp.exe' : 'tapl-mcp';
  return uniqueStrings([
    configuredMcpPath.trim() || undefined,
    executable,
    platform === 'win32' ? undefined : '/opt/homebrew/bin/tapl-mcp',
    platform === 'win32' ? undefined : '/usr/local/bin/tapl-mcp'
  ]);
}

export function taplMcpEnvironment(): Record<string, string> {
  const delimiter = process.platform === 'win32' ? ';' : ':';
  const inherited = Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined)
  );
  return {
    ...inherited,
    PATH: [process.env.PATH, '/opt/homebrew/bin', '/usr/local/bin'].filter(Boolean).join(delimiter)
  };
}

function uniqueStrings(values: Array<string | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))];
}

function toolResultMessage(content: Array<{ type: string; text?: string }>): string {
  const messages = content
    .filter((item) => item.type === 'text' && item.text)
    .map((item) => item.text as string);
  return messages.join('\n') || 'TAPL MCP tool returned an error.';
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function asError(error: unknown, fallback: string): Error {
  return error instanceof Error ? error : new Error(error === undefined ? fallback : String(error));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function closeQuietly(client: TaplMcpClientLike): Promise<void> {
  try {
    await client.close();
  } catch {
    // The process may already have exited.
  }
}

const defaultConnectionFactory: TaplMcpConnectionFactory = {
  createClient: () => new Client(
    { name: 'tapl-workflow-viewer', version: '2.0.0-beta1' },
    { capabilities: {} }
  ) as TaplMcpClientLike,
  createTransport: (command, cwd) => new StdioClientTransport({
    command,
    cwd,
    env: taplMcpEnvironment(),
    stderr: 'pipe',
    maxBufferSize: MAX_MESSAGE_BYTES
  }) as TaplMcpTransportLike
};
