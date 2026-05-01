import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeMouseHandler,
  type EdgeMouseHandler,
} from "@xyflow/react";
import { useEffect, useImperativeHandle, useMemo, forwardRef } from "react";

import "@xyflow/react/dist/style.css";

export interface GraphCanvasHandle {
  focusNode: (id: string | null) => void;
  fitView: () => void;
}

export interface GraphCanvasProps {
  nodes: Node[];
  edges: Edge[];
  /** ID of the node that should be highlighted (e.g. from a diagnostic click). */
  focusedNodeId: string | null;
  /** ID of the edge that should be highlighted (e.g. from a diagnostic click
   *  with edge_id hint). */
  focusedEdgeId?: string | null;
  /** IDs that should be visually faded (sections / search filter). */
  fadedNodeIds: Set<string>;
  /** When true, drag is disabled (lock mode). */
  dragLocked?: boolean;
  onSelectNode: (id: string | null) => void;
  onSelectEdge: (id: string | null) => void;
  onNodeMoved?: (id: string, position: { x: number; y: number }) => void;
}

const Inner = forwardRef<GraphCanvasHandle, GraphCanvasProps>(function Inner(
  props,
  ref,
) {
  const rf = useReactFlow();

  useImperativeHandle(ref, () => ({
    focusNode: (id) => {
      if (!id) return;
      const n = rf.getNode(id);
      if (!n) return;
      rf.setCenter(n.position.x, n.position.y, { zoom: 1.15, duration: 0 });
    },
    fitView: () => {
      rf.fitView({ duration: 0, padding: 0.15 });
    },
  }));

  // When focus changes, scroll viewport to the target.
  useEffect(() => {
    if (!props.focusedNodeId) return;
    const n = rf.getNode(props.focusedNodeId);
    if (!n) return;
    rf.setCenter(n.position.x, n.position.y, { zoom: 1.15, duration: 0 });
  }, [props.focusedNodeId, rf]);

  const onNodeClick: NodeMouseHandler = (_e, node) => props.onSelectNode(node.id);
  const onEdgeClick: EdgeMouseHandler = (_e, edge) => props.onSelectEdge(edge.id);
  const onPaneClick = () => {
    props.onSelectNode(null);
    props.onSelectEdge(null);
  };
  const onNodeDragStop = (_e: React.MouseEvent, node: Node) => {
    if (props.dragLocked) return;
    props.onNodeMoved?.(node.id, node.position);
  };

  // Apply faded styling and focus highlight without mutating caller arrays.
  const styledNodes = useMemo<Node[]>(
    () =>
      props.nodes.map((n) => {
        const faded = props.fadedNodeIds.has(n.id);
        const focused = props.focusedNodeId === n.id;
        return {
          ...n,
          draggable: !props.dragLocked,
          className: `${n.className ?? ""}${faded ? " wb-node-faded" : ""}${focused ? " wb-node-focused" : ""}`,
          data: { ...(n.data as object), focused, faded, dragLocked: !!props.dragLocked },
        } as Node;
      }),
    [props.nodes, props.fadedNodeIds, props.focusedNodeId, props.dragLocked],
  );

  const styledEdges = useMemo<Edge[]>(
    () =>
      props.edges.map((e) => {
        const focused = props.focusedEdgeId === e.id;
        return {
          ...e,
          className: `${e.className ?? ""}${focused ? " wb-edge-focused" : ""}`,
          animated: focused,
          data: { ...(e.data as object | undefined), focused },
        } as Edge;
      }),
    [props.edges, props.focusedEdgeId],
  );

  return (
    <ReactFlow
      nodes={styledNodes}
      edges={styledEdges}
      onNodeClick={onNodeClick}
      onEdgeClick={onEdgeClick}
      onPaneClick={onPaneClick}
      onNodeDragStop={onNodeDragStop}
      nodesDraggable={!props.dragLocked}
      fitView
      proOptions={{ hideAttribution: true }}
      minZoom={0.1}
      maxZoom={2.5}
    >
      <Background gap={24} size={1} />
      <Controls showInteractive={false} />
      <MiniMap pannable zoomable />
    </ReactFlow>
  );
});

export const GraphCanvas = forwardRef<GraphCanvasHandle, GraphCanvasProps>(
  function GraphCanvas(props, ref) {
    return (
      <ReactFlowProvider>
        <Inner ref={ref} {...props} />
      </ReactFlowProvider>
    );
  },
);
