import { useEffect, useState, useCallback } from 'react';
import { ReactFlow, Background, Controls, MiniMap, useNodesState, useEdgesState, MarkerType, Node, Edge } from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import { RefreshCw, Maximize, Download, Network, Server } from 'lucide-react';
import * as api from '@/services/api';
import type { TopologyNode, TopologyEdge } from '@/types';
import '@xyflow/react/dist/style.css';

const PLATFORM_COLORS: Record<string, string> = {
  ios: '#10b981',
  fortios: '#f97316',
  panos_xml: '#3b82f6',
  junos: '#8b5cf6',
  checkpoint: '#ef4444',
  pfsense_xml: '#06b6d4',
  unknown: '#6b7280',
};

function getNodeColor(platform: string) {
  return PLATFORM_COLORS[platform] || PLATFORM_COLORS.unknown;
}

function autoLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: 'TB', nodesep: 80, ranksep: 100 });
  g.setDefaultEdgeLabel(() => ({}));

  nodes.forEach(n => g.setNode(n.id, { width: 180, height: 80 }));
  edges.forEach(e => g.setEdge(e.source, e.target));

  dagre.layout(g);

  return nodes.map(n => {
    const pos = g.node(n.id);
    return { ...n, position: { x: pos.x - 90, y: pos.y - 40 } };
  });
}

function toFlowNodes(topoNodes: TopologyNode[]): Node[] {
  return topoNodes.map(n => ({
    id: n.id,
    position: { x: 0, y: 0 },
    data: {
      label: (
        <div className="flex flex-col items-center gap-1">
          <Server className="h-5 w-5" style={{ color: getNodeColor(n.platform) }} />
          <span className="text-xs font-semibold text-white truncate max-w-[160px]">{n.hostname || `Device ${n.id}`}</span>
          <span className="text-[10px] text-gray-400">{n.platform}</span>
        </div>
      ),
    },
    style: {
      background: '#1a1a2e',
      border: `2px solid ${getNodeColor(n.platform)}`,
      borderRadius: 8,
      padding: '10px 14px',
      width: 180,
    },
  }));
}

function toFlowEdges(topoEdges: TopologyEdge[]): Edge[] {
  return topoEdges.map(e => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.link_type === 'vpn' ? 'VPN' : e.link_type === 'subnet' ? e.shared_network || '' : '',
    labelStyle: { fontSize: 10, fill: '#9ca3af' },
    style: {
      stroke: e.link_type === 'vpn' ? '#f97316' : e.link_type === 'subnet' ? '#3b82f6' : '#6b7280',
      strokeWidth: 2,
      strokeDasharray: e.link_type === 'vpn' ? '6 3' : undefined,
    },
    markerEnd: { type: MarkerType.ArrowClosed, color: '#6b7280' },
    animated: e.link_type === 'vpn',
  }));
}

export default function TopologyTab({ missionId }: { missionId: number }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [lastRebuilt, setLastRebuilt] = useState<string | null>(null);
  const [isEmpty, setIsEmpty] = useState(true);

  const loadTopology = useCallback(async () => {
    setLoading(true);
    try {
      const result = await api.getTopology(missionId);
      const graph = result.graph;
      setLastRebuilt(result.last_rebuilt_at);

      if (!graph.nodes || graph.nodes.length === 0) {
        setIsEmpty(true);
        setNodes([]);
        setEdges([]);
      } else {
        setIsEmpty(false);
        const flowNodes = toFlowNodes(graph.nodes);
        const flowEdges = toFlowEdges(graph.edges || []);
        const laid = autoLayout(flowNodes, flowEdges);
        setNodes(laid);
        setEdges(flowEdges);
      }
    } catch {
      setIsEmpty(true);
    } finally {
      setLoading(false);
    }
  }, [missionId, setNodes, setEdges]);

  useEffect(() => { loadTopology(); }, [loadTopology]);

  const handleRebuild = useCallback(async () => {
    setRebuilding(true);
    try {
      const result = await api.rebuildTopology(missionId);
      const graph = result.graph;
      setLastRebuilt(result.last_rebuilt_at);

      if (!graph.nodes || graph.nodes.length === 0) {
        setIsEmpty(true);
        setNodes([]);
        setEdges([]);
      } else {
        setIsEmpty(false);
        const flowNodes = toFlowNodes(graph.nodes);
        const flowEdges = toFlowEdges(graph.edges || []);
        const laid = autoLayout(flowNodes, flowEdges);
        setNodes(laid);
        setEdges(flowEdges);
      }
    } catch (e) {
      void e;
    } finally {
      setRebuilding(false);
    }
  }, [missionId, setNodes, setEdges]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-dark-muted">
        <RefreshCw className="mr-2 h-5 w-5 animate-spin" />
        Loading topology...
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <Network className="mb-4 h-16 w-16 text-dark-muted opacity-40" />
        <h3 className="mb-2 text-lg font-semibold text-white">No Topology Data</h3>
        <p className="mb-6 max-w-md text-sm text-dark-secondary">
          Upload device configurations or run scans to build the network topology.
          Navigate to the Targets tab to upload configs.
        </p>
        <button
          onClick={handleRebuild}
          disabled={rebuilding}
          className="inline-flex items-center gap-2 rounded-lg bg-ey-yellow px-4 py-2 text-sm font-medium text-dark-bg hover:bg-ey-yellow/90 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${rebuilding ? 'animate-spin' : ''}`} />
          Build Topology
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between rounded-lg border border-dark-border bg-dark-card px-4 py-2.5">
        <div className="flex items-center gap-3">
          <span className="text-sm text-dark-secondary">
            {nodes.length} device{nodes.length !== 1 ? 's' : ''} · {edges.length} link{edges.length !== 1 ? 's' : ''}
          </span>
          {lastRebuilt && (
            <span className="text-xs text-dark-muted">
              Last rebuilt: {new Date(lastRebuilt).toLocaleString()}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRebuild}
            disabled={rebuilding}
            className="inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium text-dark-secondary hover:bg-dark-elevated hover:text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${rebuilding ? 'animate-spin' : ''}`} />
            Rebuild
          </button>
        </div>
      </div>

      {/* Graph */}
      <div className="rounded-lg border border-dark-border bg-dark-card" style={{ height: 600 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          fitView
          proOptions={{ hideAttribution: true }}
          style={{ background: '#0d0d1a' }}
        >
          <Background color="#333" gap={20} />
          <Controls />
          <MiniMap
            nodeColor={(n) => {
              const platform = (n.data as any)?.platform || 'unknown';
              return getNodeColor(platform);
            }}
            style={{ background: '#1a1a2e' }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}
