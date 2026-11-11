import { useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useI18n } from '../i18n';
import type { TaplItem, TaplRunSnapshot, TaplWorkflowRun } from '../types';
import { Icon } from './Icon';
import { buildRunMindmap, type MindmapNode } from './mindmap';
import { useMindmapViewport } from './mindmapViewport';
import './run-mindmap.css';

const openable = (item?: TaplItem) => typeof item?.id === 'number' && Number.isFinite(item.id);
const stateKind = (value?: string) =>
  value === 'In Progress' || value === 'active'
    ? 'progress'
    : value === 'Completed' || value === 'Finalized' || value === 'completed'
      ? 'completed'
      : value === 'Blocked' || value === 'blocked'
        ? 'blocked'
        : 'pending';

/** A RUN-owned camera survives record details and source-safe RUN navigation. */
export function RunMindmap({
  snapshot,
  open,
  back
}: {
  snapshot: TaplRunSnapshot;
  open: (item: TaplItem, run?: TaplWorkflowRun) => void;
  back?: () => void;
}): JSX.Element {
  const { t, status } = useI18n();
  const graph = useMemo(() => buildRunMindmap(snapshot), [snapshot]);
  const runKey = JSON.stringify([snapshot.run.source_db ?? '', snapshot.run.id]);
  const [active, setActive] = useState<string>();
  const byKey = useMemo(() => new Map(graph.nodes.map((node) => [node.key, node])), [graph]);
  const related = useMemo(() => {
    if (!active || !byKey.has(active)) return undefined;
    const result = new Set([active]);
    let node = byKey.get(active);
    while (node?.parent) {
      result.add(node.parent);
      node = byKey.get(node.parent);
    }
    const descendants = (key: string) => {
      for (const edge of graph.edges)
        if (edge.from === key) {
          result.add(edge.to);
          descendants(edge.to);
        }
    };
    descendants(active);
    return result;
  }, [active, byKey, graph]);
  const { hostRef, worldRef, controlsRef, edges, suppressClickCapture } = useMindmapViewport({
    graph,
    cameraKey: runKey,
    setActive
  });

  const nodeContent = (node: MindmapNode) => (
    <>
      <span className="wb-mm-meta">
        <span className="wb-mm-id">{node.kind === 'run' ? 'RUN' : node.item?.stable_id}</span>
        {node.status && (
          <span className="wb-mm-state" data-status={stateKind(node.status)}>
            <i />
            {status(node.status)}
          </span>
        )}
      </span>
      <span className="wb-mm-title" title={node.title}>
        {node.title || (node.kind === 'run' ? snapshot.run.slug || snapshot.run.id : '')}
      </span>
      {node.kind === 'run' && (
        <span className="wb-mm-run-foot">
          <span className="wb-mm-run-numbers">
            <span className="wb-mm-percent">
              {Math.round(graph.percent)}
              <small>%</small>
            </span>
            <span>
              {graph.completed} / {graph.total} {t('wbCompleted')}
            </span>
          </span>
          <svg className="wb-mm-ring" viewBox="0 0 48 48" aria-hidden="true">
            <circle className="wb-mm-ring-track" cx="24" cy="24" r="19" />
            <circle
              className="wb-mm-ring-value"
              cx="24"
              cy="24"
              r="19"
              pathLength="100"
              strokeDasharray={`${graph.percent} 100`}
            />
          </svg>
        </span>
      )}
      {node.kind === 'plan' && (
        <span className="wb-mm-plan-foot">
          <span>
            {node.completed} / {node.total} {t('wbCompleted')}
          </span>
          <span className="wb-mm-plan-track">
            <i style={{ width: `${node.total ? (node.completed / node.total) * 100 : 0}%` }} />
          </span>
        </span>
      )}
    </>
  );
  return (
    <div
      className="wb-mindmap wb-run-mindmap"
      ref={hostRef}
      role="region"
      tabIndex={0}
      aria-label={t('wbMindmap')}
      aria-description={t('wbMindmapHelp')}
      data-wb-page-heading
      data-run-key={runKey}
      onClickCapture={suppressClickCapture}
    >
      <div className="wb-mm-pointer-light" aria-hidden="true" />
      <div className="wb-mm-world" ref={worldRef}>
        <svg className="wb-mm-connections" aria-hidden="true">
          {edges.map((edge) => (
            <g
              key={`${edge.from}:${edge.to}`}
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
            className={`wb-mm-node${related ? (related.has(node.key) ? ' wb-mm-emphasis' : ' wb-mm-dim') : ''}`}
            key={node.key}
            data-kind={node.kind}
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
            onBlur={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget)) setActive(undefined);
            }}
          >
            {node.kind === 'run' ? (
              <div className="wb-mm-node-button" tabIndex={0}>
                {nodeContent(node)}
              </div>
            ) : (
              <button
                className="wb-mm-node-button"
                type="button"
                disabled={!openable(node.item)}
                title={!openable(node.item) ? t('wbRecordUnavailable') : undefined}
                data-wb-focus={`${node.kind}:${node.item?.id ?? node.key}`}
                data-status={node.status}
                onClick={() => {
                  if (openable(node.item)) open(node.item!, snapshot.run);
                }}
              >
                {nodeContent(node)}
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="wb-mm-top-controls" data-mm-controls>
        {back && (
          <button
            className="wb-mm-icon-button wb-back"
            type="button"
            aria-label={t('wbBack')}
            data-wb-focus="back"
            onClick={back}
          >
            <Icon name="back" />
          </button>
        )}
      </div>
      <div className="wb-mm-legend" aria-label={t('status')}>
        {['In Progress', 'Completed', 'Blocked', 'Pending'].map((value) => (
          <span className="wb-mm-state" data-status={stateKind(value)} key={value}>
            <i />
            {status(value)}
          </span>
        ))}
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
