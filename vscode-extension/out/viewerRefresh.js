"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ViewerRefreshQueue = exports.DatabaseRevisions = void 0;
exports.databaseRevision = databaseRevision;
const promises_1 = require("node:fs/promises");
const node_path_1 = require("node:path");
// SQLite opens and removes SHM and empty WAL files even for reads. Only database
// files and WALs with frames represent a possible committed data change.
async function databaseRevision(workspace) {
    try {
        const directory = (0, node_path_1.join)(workspace, '.tapl');
        let names;
        try {
            names = await (0, promises_1.readdir)(directory);
        }
        catch (error) {
            if (error.code === 'ENOENT') {
                return '[]';
            }
            throw error;
        }
        const entries = [];
        for (const name of names.sort()) {
            if (!/^tapl(?:-.+)?\.db(?:-wal)?$/.test(name)) {
                continue;
            }
            let stat;
            try {
                stat = await (0, promises_1.stat)((0, node_path_1.join)(directory, name), { bigint: true });
            }
            catch (error) {
                // An ephemeral sidecar may disappear between readdir and stat.
                if (name.endsWith('-wal') && error.code === 'ENOENT') {
                    continue;
                }
                throw error;
            }
            if (!stat.isFile() || (name.endsWith('-wal') && stat.size <= 32n)) {
                continue;
            }
            entries.push(`${name}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}`);
        }
        return JSON.stringify(entries);
    }
    catch {
        return undefined;
    }
}
class DatabaseRevisions {
    constructor(capture = databaseRevision) {
        this.capture = capture;
        this.accepted = new Map();
        this.observations = new Map();
    }
    async read(workspace) { return this.capture(workspace); }
    changed(workspace, revision) {
        return revision === undefined || this.accepted.get(workspace) !== revision;
    }
    // This cursor belongs to the whole refresh round, not one panel or tree read.
    // Advancing it when just one consumer reads would hide changes from the others.
    accept(workspace, revision) {
        if (revision === undefined) {
            this.accepted.delete(workspace);
        }
        else {
            this.accepted.set(workspace, revision);
        }
    }
    // A snapshot detects concurrent changes but never consumes another view's signal.
    async observe(workspace, before, valid) {
        const current = () => typeof valid === 'function' ? valid() : valid;
        if (!current()) {
            return true;
        }
        const observation = (this.observations.get(workspace) ?? 0) + 1;
        this.observations.set(workspace, observation);
        const after = await this.capture(workspace);
        if (!current() || this.observations.get(workspace) !== observation) {
            return true;
        }
        if (before === undefined || after === undefined) {
            return true;
        }
        if (before !== after) {
            return false;
        }
        return true;
    }
}
exports.DatabaseRevisions = DatabaseRevisions;
class ViewerRefreshQueue {
    constructor(currentWorkspace, revisions, refresh, delayMs) {
        this.currentWorkspace = currentWorkspace;
        this.revisions = revisions;
        this.refresh = refresh;
        this.delayMs = delayMs;
        this.dirty = false;
        this.force = false;
        this.scheduledForce = false;
        this.disposed = false;
    }
    schedule(workspace = this.currentWorkspace(), force = false) {
        if (this.disposed || workspace !== this.currentWorkspace()) {
            return;
        }
        // Automatic changes keep the trailing debounce even during a snapshot.
        // Otherwise continuous commits can turn the single-flight queue into a hot loop.
        this.scheduledForce || (this.scheduledForce = force);
        if (this.timer !== undefined) {
            clearTimeout(this.timer);
        }
        this.timer = setTimeout(() => {
            this.timer = undefined;
            const force = this.scheduledForce;
            this.scheduledForce = false;
            if (workspace === this.currentWorkspace()) {
                void this.request(force);
            }
        }, this.delayMs);
    }
    request(force = false) {
        if (this.disposed) {
            return Promise.resolve();
        }
        if (this.timer !== undefined) {
            clearTimeout(this.timer);
            this.timer = undefined;
        }
        this.dirty = true;
        this.force || (this.force = force || this.scheduledForce);
        this.scheduledForce = false;
        if (!this.running) {
            this.running = Promise.resolve().then(() => this.drain()).finally(() => {
                this.running = undefined;
                if (this.dirty && !this.disposed) {
                    void this.request();
                }
            });
        }
        return this.running;
    }
    async drain() {
        while (this.dirty && !this.disposed) {
            this.dirty = false;
            const force = this.force;
            this.force = false;
            const workspace = this.currentWorkspace();
            const revision = workspace ? await this.revisions.read(workspace) : undefined;
            if (this.disposed) {
                return;
            }
            if (workspace !== this.currentWorkspace()) {
                this.force || (this.force = force);
                this.dirty = true;
                continue;
            }
            if (force || (workspace && this.revisions.changed(workspace, revision))) {
                if (workspace) {
                    this.revisions.accept(workspace, revision);
                }
                await this.refresh();
            }
        }
    }
    dispose() {
        this.disposed = true;
        if (this.timer !== undefined) {
            clearTimeout(this.timer);
            this.timer = undefined;
        }
    }
}
exports.ViewerRefreshQueue = ViewerRefreshQueue;
//# sourceMappingURL=viewerRefresh.js.map