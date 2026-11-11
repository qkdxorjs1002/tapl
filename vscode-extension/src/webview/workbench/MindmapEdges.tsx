import { memo } from 'react';

type Edge = { from: string; to: string; path: string; start: { x: number; y: number }; flowing?: boolean };

/** Keep the primary path and pulse in graph order; only executing edges gain glass/light layers. */
export const MindmapEdge = memo(function MindmapEdge({
  edge,
  emphasis,
  relation
}: {
  edge: Edge;
  emphasis?: 'active' | 'dim';
  relation?: string;
}): JSX.Element {
  return (
    <g
      data-from={edge.from}
      data-to={edge.to}
      data-relation={relation}
      data-flow={edge.flowing ? 'running' : undefined}
      className={[edge.flowing ? 'wb-mm-edge-running' : '', emphasis ? `wb-mm-edge-${emphasis}` : ''].filter(Boolean).join(' ')}
    >
      <path className="wb-mm-edge" d={edge.path} />
      {edge.flowing && (
        <>
          <path className="wb-mm-glass-path wb-mm-tube-channel" d={edge.path} />
          <path className="wb-mm-glass-path wb-mm-tube-reflection" d={edge.path} />
        </>
      )}
      <g className={edge.flowing ? 'wb-mm-pulse wb-mm-flow' : 'wb-mm-pulse'}>
        {edge.flowing && (
          <>
            <path className="wb-mm-glass-path wb-mm-flow-glow" pathLength="100" d={edge.path} />
            <path className="wb-mm-glass-path wb-mm-flow-halo" pathLength="100" d={edge.path} />
            <path className="wb-mm-glass-path wb-mm-flow-tail" pathLength="100" d={edge.path} />
            <path className="wb-mm-glass-path wb-mm-flow-core" pathLength="100" d={edge.path} />
          </>
        )}
      </g>
    </g>
  );
});
