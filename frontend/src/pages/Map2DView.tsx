import React, { useState, useEffect, useRef, useMemo } from "react";
import * as d3 from "d3";
import { getFactionSystems, FactionSystemEntry } from "../api/factions";
import { getRecommendations, RecommendationsResponse } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor } from "../constants/ppColors";
import FactionSelector from "../components/FactionSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import LayoutModeSelector, { LayoutMode } from "../components/LayoutModeSelector";

type Axis = "xz" | "xy" | "yz";

// Extract the two coordinate values based on axis projection
function project(sys: FactionSystemEntry, axis: Axis): [number, number] {
  if (axis === "xz") return [sys.x, sys.z];
  if (axis === "xy") return [sys.x, sys.y];
  return [sys.y, sys.z];
}

function axisLabels(axis: Axis): [string, string] {
  if (axis === "xz") return ["X (left/right)", "Z (forward/back)"];
  if (axis === "xy") return ["X (left/right)", "Y (up/down)"];
  return ["Y (up/down)", "Z (forward/back)"];
}

// Build positions for each layout mode
function buildPositions(
  systems: FactionSystemEntry[],
  axis: Axis,
  mode: LayoutMode,
  centerIdx: number | null
): Map<number, [number, number]> {
  const pos = new Map<number, [number, number]>();

  if (mode === "actual") {
    systems.forEach((s) => pos.set(s.system_id64, project(s, axis)));
    return pos;
  }

  if (mode === "radial") {
    const center = centerIdx != null ? systems[centerIdx] : systems[0];
    const [cx, cy] = center ? project(center, axis) : [0, 0];
    systems.forEach((s, i) => {
      const dist = s.distance_from_center ?? Math.hypot(project(s, axis)[0] - cx, project(s, axis)[1] - cy);
      const angle = (2 * Math.PI * i) / systems.length;
      pos.set(s.system_id64, [dist * Math.cos(angle), dist * Math.sin(angle)]);
    });
    return pos;
  }

  // Force-directed: start from actual coords, spring-relax
  const pts: [number, number][] = systems.map((s) => project(s, axis));
  for (let iter = 0; iter < 80; iter++) {
    const forces: [number, number][] = pts.map(() => [0, 0]);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[j][0] - pts[i][0];
        const dy = pts[j][1] - pts[i][1];
        const dist = Math.hypot(dx, dy) || 0.001;
        const repulsion = 200 / (dist * dist);
        forces[i][0] -= repulsion * dx / dist;
        forces[i][1] -= repulsion * dy / dist;
        forces[j][0] += repulsion * dx / dist;
        forces[j][1] += repulsion * dy / dist;
      }
    }
    for (let i = 0; i < pts.length; i++) {
      pts[i][0] += forces[i][0] * 0.5;
      pts[i][1] += forces[i][1] * 0.5;
    }
  }
  systems.forEach((s, i) => pos.set(s.system_id64, pts[i]));
  return pos;
}

interface TooltipData {
  x: number; y: number;
  system: FactionSystemEntry;
  recoType: "fortify" | "expand" | null;
}

export default function Map2DView() {
  const { factionName, centerSystem, setFaction, setCenter } = useSelectionState();

  const [systems, setSystems] = useState<FactionSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [axis, setAxis] = useState<Axis>("xz");
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("actual");
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const W = 800, H = 600;

  // Build recommendation sets
  const fortifySet = useMemo(() => new Set((recommendations?.fortify ?? []).map((r) => r.system_name)), [recommendations]);
  const expandSet = useMemo(() => new Set((recommendations?.expand ?? []).map((r) => r.system_name)), [recommendations]);
  function recoType(name: string): "fortify" | "expand" | null {
    if (fortifySet.has(name)) return "fortify";
    if (expandSet.has(name)) return "expand";
    return null;
  }

  // Fetch data
  useEffect(() => {
    if (!factionName) { setSystems([]); setRecommendations(null); return; }
    setLoading(true);
    Promise.all([
      getFactionSystems(factionName, centerSystem?.id),
      getRecommendations(factionName, centerSystem?.id),
    ])
      .then(([sys, recs]) => { setSystems(sys); setRecommendations(recs); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [factionName, centerSystem?.id]);

  // Center index
  const centerIdx = useMemo(() => {
    if (!centerSystem) return null;
    const i = systems.findIndex((s) => s.system_id64 === centerSystem.id);
    return i >= 0 ? i : null;
  }, [systems, centerSystem?.id]);

  // Compute positions
  const positions = useMemo(
    () => buildPositions(systems, axis, layoutMode, centerIdx),
    [systems, axis, layoutMode, centerIdx]
  );

  // D3 zoom
  useEffect(() => {
    if (!svgRef.current || systems.length === 0) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>("g.zoom-layer");
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 20])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);
    // Reset zoom on new dataset
    svg.call(zoom.transform, d3.zoomIdentity);
  }, [systems, axis, layoutMode]);

  // Compute D3 scales from positions
  const [scaleX, scaleY] = useMemo(() => {
    const vals = Array.from(positions.values());
    if (vals.length === 0) return [null, null];
    const margin = 48;
    const xs = vals.map((v) => v[0]);
    const ys = vals.map((v) => v[1]);
    const sx = d3.scaleLinear().domain([Math.min(...xs), Math.max(...xs)]).range([margin, W - margin]).nice();
    const sy = d3.scaleLinear().domain([Math.min(...ys), Math.max(...ys)]).range([H - margin, margin]).nice();
    return [sx, sy];
  }, [positions]);

  const [labelH, labelV] = axisLabels(axis);

  return (
    <div style={{ padding: "16px 24px", fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: "#1f2328" }}>
      {/* Controls */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <FactionSelector value={factionName} onChange={setFaction} />
        <CenterSystemSelector value={centerSystem} onChange={setCenter} />
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          <span style={{ fontSize: 12, color: "#57606a" }}>Axis:</span>
          {(["xz", "xy", "yz"] as Axis[]).map((a) => (
            <button key={a} onClick={() => setAxis(a)} style={{ padding: "4px 10px", fontSize: 12, borderRadius: 4, border: "1px solid #e5e7eb", background: axis === a ? "#3b82d4" : "#fff", color: axis === a ? "#fff" : "#57606a", cursor: "pointer", fontFamily: "inherit" }}>
              {a.toUpperCase()}
            </button>
          ))}
        </div>
        <LayoutModeSelector value={layoutMode} onChange={setLayoutMode} />
        {loading && <span style={{ fontSize: 13, color: "#57606a" }}>Loading…</span>}
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, marginBottom: 8, flexWrap: "wrap" }}>
        {[
          { color: "#4AD94A", label: "Fortified" },
          { color: "#D94A4A", label: "Undermined" },
          { color: "#FF8C00", label: "Turmoil" },
          { color: "#4A90D9", label: "Expansion" },
          { color: "#D9D94A", label: "Contested" },
          { color: "#999", label: "Other" },
        ].map((l) => (
          <span key={l.label} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#57606a" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: l.color, display: "inline-block" }} />
            {l.label}
          </span>
        ))}
        <span style={{ fontSize: 12, color: "#57606a" }}>· Diamond = center · Red ring = Fortify priority · Blue ring = Expand target</span>
      </div>

      {/* SVG Canvas */}
      <div ref={containerRef} style={{ position: "relative", border: "1px solid #e5e7eb", borderRadius: 8, background: "#0a0a1a", overflow: "hidden" }}>
        <svg ref={svgRef} width={W} height={H} style={{ display: "block" }}>
          <g className="zoom-layer">
            {scaleX && scaleY && systems.map((sys) => {
              const p = positions.get(sys.system_id64);
              if (!p) return null;
              const cx = scaleX(p[0]);
              const cy = scaleY(p[1]);
              const isCenter = sys.system_id64 === centerSystem?.id;
              const reco = recoType(sys.system_name);
              const color = ppStateColor(sys.pp_state);
              const r = 6;

              return (
                <g
                  key={sys.system_id64}
                  transform={`translate(${cx},${cy})`}
                  style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => {
                    const rect = (e.currentTarget.closest("svg") as SVGSVGElement).getBoundingClientRect();
                    setTooltip({ x: e.clientX - rect.left + 12, y: e.clientY - rect.top - 8, system: sys, recoType: reco });
                  }}
                  onMouseLeave={() => setTooltip(null)}
                >
                  {/* Recommendation ring */}
                  {reco === "fortify" && <circle r={r + 4} fill="none" stroke="#D94A4A" strokeWidth={2} opacity={0.8} />}
                  {reco === "expand" && <circle r={r + 4} fill="none" stroke="#4A90D9" strokeWidth={2} opacity={0.8} />}

                  {/* System node */}
                  {isCenter ? (
                    <polygon
                      points="0,-10 3,-3 10,-3 4,2 6,10 0,5 -6,10 -4,2 -10,-3 -3,-3"
                      fill="#FFD700"
                      stroke="#fff"
                      strokeWidth={1}
                    />
                  ) : (
                    <circle r={r} fill={color} stroke={sys.is_controlling ? "#fff" : "rgba(255,255,255,0.3)"} strokeWidth={sys.is_controlling ? 1.5 : 0.5} />
                  )}
                </g>
              );
            })}
          </g>

          {/* Axis labels */}
          <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="#57606a">{labelH}</text>
          <text x={10} y={H / 2} textAnchor="middle" fontSize={11} fill="#57606a" transform={`rotate(-90,10,${H / 2})`}>{labelV}</text>
        </svg>

        {/* Tooltip */}
        {tooltip && (
          <div style={{ position: "absolute", left: tooltip.x, top: tooltip.y, background: "rgba(10,10,26,0.92)", color: "#fff", padding: "8px 12px", borderRadius: 6, fontSize: 12, pointerEvents: "none", border: "1px solid #3b82d4", maxWidth: 220, zIndex: 10 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{tooltip.system.system_name}</div>
            {tooltip.system.pp_state && <div>State: <span style={{ color: ppStateColor(tooltip.system.pp_state) }}>{tooltip.system.pp_state}</span></div>}
            {tooltip.system.pp_power && <div>Power: {tooltip.system.pp_power}</div>}
            {tooltip.system.influence != null && <div>Influence: {(tooltip.system.influence * 100).toFixed(1)}%</div>}
            {tooltip.system.is_controlling && <div style={{ color: "#4AD94A" }}>Controlling faction</div>}
            {tooltip.recoType === "fortify" && <div style={{ color: "#D94A4A", marginTop: 4, fontWeight: 600 }}>Fortify Priority</div>}
            {tooltip.recoType === "expand" && <div style={{ color: "#4A90D9", marginTop: 4, fontWeight: 600 }}>Expansion Target</div>}
          </div>
        )}
      </div>

      {!factionName && (
        <p style={{ color: "#57606a", fontSize: 14, marginTop: 16 }}>Select a faction to render the 2D map.</p>
      )}
      {factionName && !loading && systems.length === 0 && (
        <p style={{ color: "#57606a", fontSize: 14, marginTop: 16 }}>No system data found. Run a Spansh ingest first.</p>
      )}
    </div>
  );
}
