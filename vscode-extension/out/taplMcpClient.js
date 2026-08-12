"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.TaplMcpClientPool = exports.WorkspaceTaplMcpClient = exports.TaplMcpToolError = void 0;
exports.taplMcpCommandCandidates = taplMcpCommandCandidates;
exports.taplMcpEnvironment = taplMcpEnvironment;
const index_js_1 = require("@modelcontextprotocol/sdk/client/index.js");
const stdio_js_1 = require("@modelcontextprotocol/sdk/client/stdio.js");
const REQUEST_TIMEOUT_MS = 10000;
const MAX_MESSAGE_BYTES = 16 * 1024 * 1024;
class TaplMcpToolError extends Error {
    constructor(message) {
        super(message);
        this.name = 'TaplMcpToolError';
    }
}
exports.TaplMcpToolError = TaplMcpToolError;
class WorkspaceTaplMcpClient {
    constructor(workspace, factory = defaultConnectionFactory) {
        this.workspace = workspace;
        this.factory = factory;
        this.disposed = false;
    }
    async callTool(name, args = {}) {
        let lastError;
        for (let attempt = 0; attempt < 2; attempt += 1) {
            const connection = await this.getConnection();
            try {
                const result = await connection.client.callTool({ name, arguments: args }, undefined, { timeout: REQUEST_TIMEOUT_MS });
                if (result.isError) {
                    throw new TaplMcpToolError(toolResultMessage(result.content));
                }
                if (isRecord(result.structuredContent)) {
                    return result.structuredContent;
                }
                const text = result.content.find((item) => item.type === 'text')?.text;
                if (text) {
                    const parsed = JSON.parse(text);
                    if (isRecord(parsed)) {
                        return parsed;
                    }
                }
                throw new Error(`${name} did not return structured object content.`);
            }
            catch (error) {
                if (error instanceof TaplMcpToolError) {
                    throw error;
                }
                lastError = error;
                await this.invalidate(connection);
            }
        }
        throw asError(lastError, 'TAPL MCP request failed after restarting the server.');
    }
    async dispose() {
        this.disposed = true;
        const connection = this.connection;
        this.connection = undefined;
        if (connection) {
            connection.closed = true;
            await closeQuietly(connection.client);
        }
    }
    async getConnection() {
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
    async startConnection() {
        const failures = [];
        for (const command of this.workspace.commands) {
            const client = this.factory.createClient();
            const connection = { client, command, closed: false };
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
            }
            catch (error) {
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
    async invalidate(connection) {
        connection.closed = true;
        if (this.connection === connection) {
            this.connection = undefined;
        }
        await closeQuietly(connection.client);
    }
}
exports.WorkspaceTaplMcpClient = WorkspaceTaplMcpClient;
class TaplMcpClientPool {
    constructor(factory = defaultConnectionFactory) {
        this.factory = factory;
        this.sessions = new Map();
        this.disposed = false;
    }
    async callTool(workspace, name, args = {}) {
        if (this.disposed) {
            throw new Error('TAPL MCP client pool has been disposed.');
        }
        return this.sessionFor(workspace).callTool(name, args);
    }
    invalidate(workspaceKey) {
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
    async dispose() {
        this.disposed = true;
        const sessions = [...this.sessions.values()];
        this.sessions.clear();
        await Promise.all(sessions.map(({ session }) => session.dispose()));
    }
    sessionFor(workspace) {
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
exports.TaplMcpClientPool = TaplMcpClientPool;
function taplMcpCommandCandidates(configuredMcpPath, platform = process.platform) {
    const executable = platform === 'win32' ? 'tapl-mcp.exe' : 'tapl-mcp';
    return uniqueStrings([
        configuredMcpPath.trim() || undefined,
        executable,
        platform === 'win32' ? undefined : '/opt/homebrew/bin/tapl-mcp',
        platform === 'win32' ? undefined : '/usr/local/bin/tapl-mcp'
    ]);
}
function taplMcpEnvironment() {
    const delimiter = process.platform === 'win32' ? ';' : ':';
    const inherited = Object.fromEntries(Object.entries(process.env).filter((entry) => entry[1] !== undefined));
    return {
        ...inherited,
        PATH: [process.env.PATH, '/opt/homebrew/bin', '/usr/local/bin'].filter(Boolean).join(delimiter)
    };
}
function uniqueStrings(values) {
    return [...new Set(values.filter((value) => Boolean(value)))];
}
function toolResultMessage(content) {
    const messages = content
        .filter((item) => item.type === 'text' && item.text)
        .map((item) => item.text);
    return messages.join('\n') || 'TAPL MCP tool returned an error.';
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function asError(error, fallback) {
    return error instanceof Error ? error : new Error(error === undefined ? fallback : String(error));
}
function isRecord(value) {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}
async function closeQuietly(client) {
    try {
        await client.close();
    }
    catch {
        // The process may already have exited.
    }
}
const defaultConnectionFactory = {
    createClient: () => new index_js_1.Client({ name: 'tapl-workflow-viewer', version: '2.0.0-beta1' }, { capabilities: {} }),
    createTransport: (command, cwd) => new stdio_js_1.StdioClientTransport({
        command,
        cwd,
        env: taplMcpEnvironment(),
        stderr: 'pipe',
        maxBufferSize: MAX_MESSAGE_BYTES
    })
};
//# sourceMappingURL=taplMcpClient.js.map