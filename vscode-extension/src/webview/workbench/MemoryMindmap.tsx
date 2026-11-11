import { useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useI18n } from '../i18n';
import type { AssociativeMemory, WebviewCommand } from '../types';
import { Icon } from './Icon';
import { buildMemoryMindmap, type MemoryMindmapNode } from './memoryMindmapGraph';
import { useMindmapViewport } from './mindmapViewport';
import './run-mindmap.css';
import './memory-mindmap.css';

/** The current results page, connected only by recorded provenance and saved cues. */
export function MemoryMindmap({
  memories,
  send,
  cameraKey,
  workspaceKey
}: {
  memories: AssociativeMemory[];
  send: (message: WebviewCommand) => void;
  cameraKey: string;
  workspaceKey?: string;
}): JSX.Element {
  const { t } = useI18n();
  const workspaceTitle = workspaceKey?.split(/[\\/]/).filter(Boolean).pop() || t('wbWorkspace');
  const graph = useMemo(
    () => buildMemoryMindmap(memories, { workspaceKey, workspaceTitle }),
    [memories, workspaceKey, workspaceTitle]
  );
  const [active, setActive] = useState<string>();
  const related = useMemo(() => {
    if (!active || !graph.nodes.some((node) => node.key === active)) return undefined;
    const result = new Set([active]);
    // Trace every ancestor and descendant in this DAG, including all shared parents.
    for (const direction of ['from', 'to'] as const) {
      const visited = new Set([active]);
      const pending = [active];
      while (pending.length) {
        const key = pending.pop()!;
        for (const edge of graph.edges) {
          if (edge[direction] !== key) continue;
          const next = edge[direction === 'from' ? 'to' : 'from'];
          if (visited.has(next)) continue;
          visited.add(next);
          result.add(next);
          pending.push(next);
        }
      }
    }
    return result;
  }, [active, graph]);
  const { hostRef, worldRef, controlsRef, edges, suppressClickCapture } = useMindmapViewport({
    graph,
    cameraKey,
    setActive
  });
  const label = (node: MemoryMindmapNode) =>
    t(
      node.kind === 'workspace'
        ? 'wbWorkspace'
        : node.kind === 'source'
          ? 'wbMemoryMapSource'
          : node.kind === 'memory'
            ? 'wbMemoryMapMemory'
            : 'wbMemoryMapCue'
    );
  const open = (node: MemoryMindmapNode) => {
    if (node.kind === 'workspace') {
      controlsRef.current?.fit();
    } else if (node.kind === 'cue' && node.cue !== undefined) {
      send({ command: 'memories', query: node.cue, offset: 0 });
    } else if (node.memory && node.kind === 'memory') {
      send({ command: 'openMemory', memoryId: node.memory.id, source_db: node.memory.source_db });
    } else if (node.memory?.source_available && node.kind === 'source') {
      send({ command: 'openMemorySource', memoryId: node.memory.id, source_db: node.memory.source_db });
    }
  };
  const content = (node: MemoryMindmapNode) => {
    const memory = node.memory;
    if (node.kind === 'workspace')
      return (
        <>
          <span className="wb-mm-meta wb-mm-workspace-label">
            <Icon name="folder" />
            {label(node)}
          </span>
          <span className="wb-mm-title" title={workspaceKey || node.title}>
            {node.title}
          </span>
          <span className="wb-mm-workspace-count">{t('wbMemoryMapCount', { count: graph.memoryCount })}</span>
        </>
      );
    if (node.kind === 'cue')
      return (
        <>
          <span className="wb-mm-cue-role">{label(node)}</span>
          <span className="wb-mm-title" title={node.title}>
            {node.title}
          </span>
          <span className="wb-mm-relation-count" title={t('wbMemoryMapCount', { count: node.count })}>
            {node.count}
          </span>
        </>
      );
    return (
      <>
        <span className="wb-mm-meta">
          <span className="wb-mm-id">
            {label(node)}
            {node.kind === 'source' && memory?.source.kind
              ? ` · ${t(memory.source.kind === 'run' ? 'wbRun' : 'wbMemoryMapRecord')}`
              : ''}
          </span>
          {node.kind === 'memory' && memory && (
            <span className="wb-mm-state" data-status={memory.state === 'active' ? 'progress' : 'pending'}>
              <i />
              {t(
                memory.state === 'active'
                  ? 'memoryActive'
                  : memory.state === 'superseded'
                    ? 'memorySuperseded'
                    : 'memoryDeleted'
              )}
            </span>
          )}
          {node.kind === 'source' && (
            <span className="wb-mm-relation-count" title={t('wbMemoryMapCount', { count: node.count })}>
              {node.count}
            </span>
          )}
        </span>
        <span className="wb-mm-title" title={node.title}>
          {node.title}
        </span>
        {node.kind === 'memory' && memory ? (
          <span className="wb-mm-meta wb-mm-memory-foot">
            <span className="wb-mm-id" title={memory.id}>
              {memory.id}
            </span>
            <span>
              {t('wbRevision')} {memory.revision}
            </span>
          </span>
        ) : (
          <span
            className="wb-mm-source-location"
            title={[memory?.source.run_id, memory?.source_db].filter(Boolean).join(' · ')}
          >
            {memory?.source_available ? memory.source.run_id : t('sourceUnavailable')}
          </span>
        )}
      </>
    );
  };
  return (
    <div
      className="wb-mindmap wb-memory-mindmap"
      ref={hostRef}
      role="region"
      tabIndex={0}
      aria-label={t('wbMemoryMap')}
      aria-description={t('wbMemoryMapHelp')}
      data-memory-camera-key={cameraKey}
      onClickCapture={suppressClickCapture}
    >
      <div className="wb-mm-pointer-light" aria-hidden="true" />
      <div className="wb-mm-world" ref={worldRef}>
        <svg className="wb-mm-connections" aria-hidden="true">
          {edges.map((edge) => (
            <g
              key={JSON.stringify([edge.from, edge.to])}
              data-from={edge.from}
              data-to={edge.to}
              data-relation={graph.edges[edge.index].relation}
              className={
                related ? (related.has(edge.from) && related.has(edge.to) ? 'wb-mm-edge-active' : 'wb-mm-edge-dim') : ''
              }
            >
              <path className="wb-mm-edge" d={edge.path} />
              <circle className="wb-mm-pulse" r="2" cx={edge.start.x} cy={edge.start.y} />
            </g>
          ))}
        </svg>
        {graph.nodes.map((node, index) => (
          <div
            key={node.key}
            className={`wb-mm-node${related ? (related.has(node.key) ? ' wb-mm-emphasis' : ' wb-mm-dim') : ''}`}
            data-kind={node.kind}
            data-matched={node.kind === 'cue' && node.matched ? 'true' : undefined}
            data-mindmap-node={node.key}
            style={
              {
                width: node.width,
                height: node.height,
                transform: `translate(${node.x - node.width / 2}px, ${node.y - node.height / 2}px)`,
                '--mm-order': index
              } as CSSProperties
            }
            onPointerEnter={(event) => {
              if (event.pointerType !== 'touch') setActive(node.key);
            }}
            onPointerLeave={() => setActive(undefined)}
            onFocus={() => setActive(node.key)}
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setActive(undefined);
            }}
          >
            <button
              className="wb-mm-node-button"
              type="button"
              disabled={node.kind === 'source' && !node.memory?.source_available}
              aria-label={
                node.kind === 'workspace'
                  ? t('wbMemoryMapCenter', { workspace: node.title })
                  : node.kind === 'cue'
                    ? `${t('wbMemoryMapSearchCue', { cue: node.cue ?? node.title })} · ${t('wbMemoryMapCount', { count: node.count })}`
                    : `${node.kind === 'source' ? t('openOriginalSource') : t('memoryDetail')}: ${node.title}`
              }
              title={node.kind === 'source' && !node.memory?.source_available ? t('sourceUnavailable') : node.title}
              data-wb-focus={
                node.kind === 'memory'
                  ? `memory:${node.memory?.source_db ?? ''}:${node.memory?.id}`
                  : `memory-${node.key}`
              }
              onClick={() => open(node)}
            >
              {content(node)}
            </button>
          </div>
        ))}
      </div>
      <div className="wb-mm-legend wb-mm-memory-legend" aria-label={t('wbMemoryMapPage')}>
        <span>
          {t('wbMemoryMapSource')} <b>{graph.sourceCount}</b>
        </span>
        <span aria-hidden="true">·</span>
        <span>
          {t('wbMemoryMapMemory')} <b>{graph.memoryCount}</b>
        </span>
        <span aria-hidden="true">·</span>
        <span>
          {t('wbMemoryMapCue')} <b>{graph.cueCount}</b>
        </span>
      </div>
      <div className="wb-mm-camera-controls" data-mm-controls>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomOut')}
          onClick={() => controlsRef.current?.zoom(1 / 1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12" />
          </svg>
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapFit')}
          onClick={() => controlsRef.current?.fit()}
        >
          <Icon name="focus" />
        </button>
        <button
          className="wb-mm-icon-button"
          type="button"
          aria-label={t('wbMindmapZoomIn')}
          onClick={() => controlsRef.current?.zoom(1.2)}
        >
          <svg className="wb-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 12h12M12 6v12" />
          </svg>
        </button>
      </div>
    </div>
  );
}
