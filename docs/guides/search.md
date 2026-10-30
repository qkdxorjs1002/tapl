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

Install the semantic extra or `taplctl-semantic` formula as described in [Installation](../getting-started/installation.md). It supplies `numpy`, `sentence-transformers` and `sqlite-vec`. The current embedding model is `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, with 384 dimensions. The model is fixed by the implementation; there is no public `search.model` setting. SubAgent model preferences control delegation and do not select an embedding model.

```sh
taplctl reindex --dry-run --json
taplctl reindex --json
```

Dry-run reports item count, optional dependency availability, model and dimension. Actual reindex rebuilds the optional vector index for existing items, including searchable custom fields. It needs the optional dependencies and may load/download model weights if they are not cached. An empty/missing vector index or unavailable semantic dependencies results in text-search fallback. Rebuild an existing workspace when its semantic index needs refreshing; full-text search does not require a vector rebuild.

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

Search does not start the daemon automatically. The semantic Homebrew formula also does not start a preloaded search process. `searchd` can retain the model between queries and unloads it after 1,800 idle seconds by default; `search.searchd_model_idle_timeout_seconds = 0` disables idle unloading. Unloading the model does not stop the daemon. `searchd start --idle-timeout SECONDS` overrides the setting for that process.

The default socket is `~/.tapl/searchd.sock`; `TAPL_SEARCHD_SOCKET` selects another path. Management commands also accept `--socket PATH`. A custom management socket must match the environment used by search callers. The daemon uses Unix domain sockets and is unavailable on Windows, where semantic search uses the local path when dependencies are installed and BM25 otherwise. No provider API credential is required for this local embedding model.

## Verify results and limitations

Check `taplctl config get search --json`, `taplctl reindex --dry-run --json` and, if using searchd, `taplctl searchd status --json`. Then inspect a real search response for fallback details and open its source record. Configuring `semantic` or `hybrid` alone does not prove vectors were used.

The separate associative-memory store uses SQLite FTS and its own cue rules; semantic provider settings do not change memory matching or add automatic model calls to recall. Search relevance is not proof of a decision's correctness or current applicability. Verify the original source and current code before applying a prior result.

## Related pages

[Configuration](configuration.md) · [Memory](memory.md) · [Viewer](viewer.md) · [CLI reference](../reference/cli.md) · [MCP tools](../reference/mcp.md)
