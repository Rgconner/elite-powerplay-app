import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { getArchitectureSchema, getArchitectureStatus, type ArchitectureSchema, type ArchitectureStatus } from "../api/architecture";

export default function ArchitecturePage() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [schema, setSchema] = useState<ArchitectureSchema | null>(null);
  const [status, setStatus] = useState<ArchitectureStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        const [schemaData, statusData] = await Promise.all([
          getArchitectureSchema(),
          getArchitectureStatus(),
        ]);
        setSchema(schemaData);
        setStatus(statusData);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load architecture data");
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  useEffect(() => {
    if (!schema || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth;
    const height = svgRef.current.clientHeight;

    svg.selectAll("*").remove();

    // Create simulation
    const simulation = d3
      .forceSimulation(schema.nodes as any)
      .force(
        "link",
        d3
          .forceLink(schema.edges as any)
          .id((d: any) => d.id)
          .distance(150)
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(50));

    // Create arrow markers
    svg
      .append("defs")
      .selectAll("marker")
      .data(["data_fetch", "write", "read", "stream", "api", "read_write"])
      .join("marker")
      .attr("id", (d) => `arrow-${d}`)
      .attr("viewBox", "0 -5 10 10")
      .attr("refX", 20)
      .attr("refY", 0)
      .attr("markerWidth", 6)
      .attr("markerHeight", 6)
      .attr("orient", "auto")
      .append("path")
      .attr("fill", (d) => {
        const colors: Record<string, string> = {
          data_fetch: "#4ade80",
          write: "#60a5fa",
          read: "#fbbf24",
          stream: "#a78bfa",
          api: "#f472b6",
          read_write: "#fb923c",
        };
        return colors[d] || "#94a3b8";
      })
      .attr("d", "M0,-5L10,0L0,5");

    // Create links
    const link = svg
      .append("g")
      .selectAll("line")
      .data(schema.edges)
      .join("line")
      .attr("stroke", (d) => {
        const colors: Record<string, string> = {
          data_fetch: "#4ade80",
          write: "#60a5fa",
          read: "#fbbf24",
          stream: "#a78bfa",
          api: "#f472b6",
          read_write: "#fb923c",
        };
        return colors[d.type] || "#94a3b8";
      })
      .attr("stroke-width", 2)
      .attr("stroke-opacity", 0.6)
      .attr("marker-end", (d) => `url(#arrow-${d.type})`);

    // Create link labels
    const linkLabel = svg
      .append("g")
      .selectAll("text")
      .data(schema.edges)
      .join("text")
      .attr("font-size", "10px")
      .attr("fill", "#94a3b8")
      .attr("text-anchor", "middle")
      .text((d) => d.label);

    // Create nodes
    const node = svg
      .append("g")
      .selectAll("g")
      .data(schema.nodes)
      .join("g")
      .call(
        d3
          .drag<any, any>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      )
      .on("click", (_event: any, d: any) => {
        setSelectedNode(d.id);
      });

    // Node circles
    node
      .append("circle")
      .attr("r", 20)
      .attr("fill", (d) => {
        const colors: Record<string, string> = {
          service: "#3b82f6",
          table: "#10b981",
          external: "#ef4444",
          endpoint: "#f59e0b",
        };
        return colors[d.type] || "#64748b";
      })
      .attr("stroke", "#1e293b")
      .attr("stroke-width", 2);

    // Status indicators
    node
      .append("circle")
      .attr("r", 6)
      .attr("cx", 15)
      .attr("cy", -15)
      .attr("fill", (d) => {
        if (!status) return "#64748b";
        
        const nodeStatus = status.services[d.id] || status.tables[d.id];
        if (!nodeStatus) return "#64748b";
        
        const s = nodeStatus.status;
        if (s === "running" || s === "completed") return "#10b981";
        if (s === "failed" || s === "error") return "#ef4444";
        if (s === "idle" || s === "unknown") return "#f59e0b";
        return "#64748b";
      });

    // Node labels
    node
      .append("text")
      .attr("dy", 35)
      .attr("text-anchor", "middle")
      .attr("font-size", "12px")
      .attr("font-weight", "600")
      .attr("fill", "#e2e8f0")
      .text((d) => d.label);

    // Update positions on tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);

      linkLabel
        .attr("x", (d: any) => (d.source.x + d.target.x) / 2)
        .attr("y", (d: any) => (d.source.y + d.target.y) / 2);

      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [schema, status]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-lg text-slate-400">Loading architecture...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-lg text-red-400">{error}</div>
      </div>
    );
  }

  const selectedNodeData = selectedNode && schema
    ? schema.nodes.find((n) => n.id === selectedNode)
    : null;

  const selectedNodeStatus = selectedNode && status
    ? status.services[selectedNode] || status.tables[selectedNode]
    : null;

  return (
    <div className="flex h-full">
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full bg-slate-900" />
        
        {/* Legend */}
        <div className="absolute top-4 left-4 bg-slate-800/90 backdrop-blur rounded-lg p-4 text-sm">
          <div className="font-semibold mb-2 text-slate-200">Node Types</div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-blue-500"></div>
              <span className="text-slate-300">Service</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-emerald-500"></div>
              <span className="text-slate-300">Table</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-red-500"></div>
              <span className="text-slate-300">External</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 rounded-full bg-amber-500"></div>
              <span className="text-slate-300">Endpoint</span>
            </div>
          </div>
          
          <div className="font-semibold mt-4 mb-2 text-slate-200">Edge Types</div>
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-green-400"></div>
              <span className="text-slate-300">Data Fetch</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-blue-400"></div>
              <span className="text-slate-300">Write</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-yellow-400"></div>
              <span className="text-slate-300">Read</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-purple-400"></div>
              <span className="text-slate-300">Stream</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-8 h-0.5 bg-pink-400"></div>
              <span className="text-slate-300">API</span>
            </div>
          </div>
        </div>
      </div>

      {/* Detail Panel */}
      {selectedNodeData && (
        <div className="w-80 bg-slate-800 border-l border-slate-700 p-4 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-slate-200">
              {selectedNodeData.label}
            </h2>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-slate-400 hover:text-slate-200"
            >
              ✕
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <div className="text-sm font-medium text-slate-400 mb-1">Type</div>
              <div className="text-slate-200 capitalize">{selectedNodeData.type}</div>
            </div>

            <div>
              <div className="text-sm font-medium text-slate-400 mb-1">Description</div>
              <div className="text-slate-300 text-sm">{selectedNodeData.description}</div>
            </div>

            {selectedNodeData.source_file && (
              <div>
                <div className="text-sm font-medium text-slate-400 mb-1">Source File</div>
                <div className="text-slate-300 text-sm font-mono">
                  {selectedNodeData.source_file}
                </div>
              </div>
            )}

            {selectedNodeData.schedule && (
              <div>
                <div className="text-sm font-medium text-slate-400 mb-1">Schedule</div>
                <div className="text-slate-300 text-sm">{selectedNodeData.schedule}</div>
              </div>
            )}

            {selectedNodeData.columns && (
              <div>
                <div className="text-sm font-medium text-slate-400 mb-1">Columns</div>
                <div className="text-slate-300 text-sm font-mono">
                  {selectedNodeData.columns.join(", ")}
                </div>
              </div>
            )}

            {selectedNodeStatus && (
              <div>
                <div className="text-sm font-medium text-slate-400 mb-2">Live Status</div>
                <div className="bg-slate-900 rounded p-3 space-y-2">
                  {selectedNodeStatus.status && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 text-sm">Status:</span>
                      <span className="text-slate-200 text-sm">{selectedNodeStatus.status}</span>
                    </div>
                  )}
                  {selectedNodeStatus.last_run && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 text-sm">Last Run:</span>
                      <span className="text-slate-200 text-sm">
                        {new Date(selectedNodeStatus.last_run).toLocaleString()}
                      </span>
                    </div>
                  )}
                  {selectedNodeStatus.records_processed !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 text-sm">Records:</span>
                      <span className="text-slate-200 text-sm">
                        {selectedNodeStatus.records_processed.toLocaleString()}
                      </span>
                    </div>
                  )}
                  {selectedNodeStatus.total_events !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 text-sm">Total Events:</span>
                      <span className="text-slate-200 text-sm">
                        {selectedNodeStatus.total_events.toLocaleString()}
                      </span>
                    </div>
                  )}
                  {selectedNodeStatus.row_count !== undefined && (
                    <div className="flex justify-between">
                      <span className="text-slate-400 text-sm">Row Count:</span>
                      <span className="text-slate-200 text-sm">
                        {selectedNodeStatus.row_count.toLocaleString()}
                      </span>
                    </div>
                  )}
                  {selectedNodeStatus.error && (
                    <div className="text-red-400 text-sm mt-2">
                      Error: {selectedNodeStatus.error}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}