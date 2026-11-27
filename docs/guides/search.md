# Search

[Documentation](../README.md) · [한국어](search.ko.md)

Search original active and archived workflow records when you need a prior decision, implementation pattern, failure or tradeoff. Use emitted [memory](memory.md) cues as an initial lead and verify the original record before relying on it.

## Search from the agent or Viewer

Ask the agent, for example: “Find prior SQLite rollback decisions and show the original PLAN or FINDING.” The agent calls `tapl_search_history` with compact task-specific terms, then reads matching records with `tapl_get_item` or `tapl_get_archive`. The browser and VS Code [Viewer](viewer.md) also provide record search.

Example `tapl_search_history` arguments, using the current hook session identity:

```json
{"session_id":"<current-hook-session-id>","query":"SQLite rollback","limit":12}
```

`query` is 1–500 characters. Explicit MCP `limit` is 1–50; when omitted, `search.max_results` supplies the default. Search summaries are exploration leads. Inspect original item/archive content for evidence and context. Workflow search uses MCP; `taplctl` has no workflow `search` command.

Search covers the working folder's `tapl-*.db` files. Forward each result's `source_db` to detail reads. See [Local identity and shared history](storage.md) for combined ranking, source errors, and sharing boundaries.

## Browse records in the Viewer

**Record search** is a paginated text library of PLAN, TASK and FINDING records. It starts with **All records** and accepts an empty query. A nonempty query matches literal title, body and stable-ID text; semantic/hybrid ranking settings below apply to `tapl_search_history`, not this library.

Select **Selected RUN** to restrict matches to its exact source database and RUN. RUN groups start collapsed; expand one to read its records or open the original RUN. **By record** displays a flat list. Query and scope changes collapse groups and reset the page. Totals and per-RUN counts are calculated after filtering, before pagination; a RUN can have matches on another page. Each page contains at most 50 records. Source failures remain visible without hiding successful sources. Internal detail links preserve a return path and source identity.

## Choose a search mode

SQLite full-text search is available in every installation. Optional semantic search adds embeddings and a vector index.

| `search.mode` | Behavior |
| --- | --- |
| `bm25` | SQLite FTS ranking for text matches. |
| `word` | Text matching across title, body, raw text, custom JSON and stable ID. |
| `semantic` | Vector similarity when available; otherwise BM25 with a fallback reason. |
| `hybrid` (default) | Merge semantic and BM25 result ranks; if semantic search is unavailable, use BM25 only and report a fallback reason. |

```sh
taplctl config get search --json
taplctl config set search.mode hybrid
taplctl config set search.max_results 12
taplctl config set search.hybrid_semantic_ratio 0.65
```

Hybrid weighting defaults to semantic `0.65` and BM25 `0.35`; BM25's weight is derived as `1 - hybrid_semantic_ratio`. Scores combine weighted reciprocal ranks, not raw vector distances and BM25 scores. A weight of `0` omits that source's contribution. `configured_mode`, returned `mode`, `fallback_reason` when present, and result `search_source` help distinguish configured behavior from the results actually used. Semantic-only fallback reports `mode="bm25"`; hybrid fallback keeps `mode="hybrid"` while using BM25 results.

## Semantic dependencies and index

Homebrew `taplctl` and `taplctl-pre` include semantic dependencies on supported platforms. See [Installation](../getting-started/installation.md) for standalone installs. ONNX Runtime runs the model on the local CPU.

Select a model under **Settings → Search → Search embedding model**, or use `taplctl config set search.model MODEL`.

| Model | Setting | Use |
| --- | --- | --- |
| KoEn-E5-Tiny INT8 | `koen-e5-tiny-int8` | Default for Korean and English |
| multilingual-e5-small INT8 | `multilingual-e5-small-int8` | Searching records across more languages |

Both models use a 128-token limit and 384-dimensional vectors. With the semantic dependencies installed and search mode set to `semantic` or `hybrid`, TAPL rebuilds an existing index in the background when its model or model fingerprint differs from the current model's identity. Automatic rebuilds target the current workspace's local or legacy local database. A `--db` override is eligible only if it points to one of those databases. TAPL checks in these cases:

- A save or reset in the browser Viewer or VS Code changes settings, or `taplctl config set` or `taplctl config unset` changes them.
- A standalone `taplctl update` activates a new release. `taplctl update --check` only checks for updates.
- After a Homebrew upgrade, you first open the workspace in the Viewer or start MCP in that workspace.

TAPL searches with BM25 until a matching index is ready. It keeps the existing vectors until the replacement is committed atomically and leaves peer databases untouched. Create the first index manually. Run these commands in the current workspace to check whether rebuilding is needed or to run it yourself.

```sh
taplctl reindex --dry-run --json
taplctl reindex --json
```

`--dry-run` reports the current index and `needs_reindex` without downloading a model. Actual indexing requires the semantic dependencies. It downloads the pinned model and tokenizer as needed, verifies SHA-256, and caches them under `~/.cache/tapl/models`. Set `TAPL_MODEL_CACHE` to use another cache. Existing MiniLM indexes are preserved.

## Embedding provider and searchd

`search.semantic_provider` selects how query embeddings are produced, rather than a remote model provider:

| Provider | Behavior |
| --- | --- |
| `local` | Load the embedding model in the calling process. |
| `auto` (default) | Try an already-running searchd, then local embedding if unavailable or a daemon error occurs. |
| `daemon` | Try searchd; if no usable daemon is listening, try local embedding. Other daemon errors make semantic search unavailable, allowing text fallback. |

```sh
taplctl config set search.semantic_provider auto
taplctl searchd start
taplctl searchd status --json
taplctl searchd stop
```

Search does not start the daemon automatically. The Homebrew formulas also does not start a preloaded search process. `searchd` can retain the model between queries and unloads it after 1,800 idle seconds by default; `search.searchd_model_idle_timeout_seconds = 0` disables idle unloading. Unloading the model does not stop the daemon. `searchd start --idle-timeout SECONDS` overrides the setting for that process.

The default socket is `~/.tapl/searchd.sock`; `TAPL_SEARCHD_SOCKET` selects another path. Management commands also accept `--socket PATH`. A custom management socket must match the environment used by search callers. The daemon uses Unix domain sockets and is unavailable on Windows, where semantic search uses the local path when dependencies are installed and BM25 otherwise. No provider API credential is required for this local embedding model.

## Verify results and limitations

Check `taplctl config get search --json`, `taplctl reindex --dry-run --json` and, if using searchd, `taplctl searchd status --json`. Then inspect a real search response for fallback details and open its source record. Configuring `semantic` or `hybrid` alone does not prove vectors were used.

The separate associative-memory store uses SQLite FTS and its own cue rules; semantic provider settings do not change memory matching or add automatic model calls to recall. Search relevance is not proof of a decision's correctness or current applicability. Verify the original source and current code before applying a prior result.

## Related pages

[Configuration](configuration.md) · [Memory](memory.md) · [Viewer](viewer.md) · [CLI reference](../reference/cli.md) · [MCP tools](../reference/mcp.md)
