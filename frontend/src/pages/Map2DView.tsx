import { useState, useEffect, useRef, useMemo } from "react";
import * as d3 from "d3";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { getRecommendations, RecommendationsResponse } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor, PP_STATE_LABELS, PP_STATES_ORDERED } from "../constants/ppColors";
import PowerSelector from "../components/PowerSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import LayoutModeSelector, { LayoutMode } from "../components/LayoutModeSelector";

type Axis = "xz" | "xy" | "yz";

function project(sys: PPSystemEntry, axis: Axis): [number, number] {
  if (axis === "xz") return [sys.x, sys.z];
  if (axis === "xy") return [sys.x, sys.y];
  return [sys.y, sys.z];
}

function axisLabels(axis: Axis): [string, string] {
  if (axis === "xz") return ["X (left/right)", "Z (forward/back)"];
  if (axis === "xy") return ["X (left/right)", "Y (up/down)"];
  return ["Y (up/down)", "Z (forward/back)"];
}

function buildPositions(
  systems: PPSystemEntry[], axis: Axis, mode: LayoutMode, centerIdx: number | null
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

  // Force-directed
  const pts: [number, number][] = systems.map((s) => project(s, axis));
  for (let iter = 0; iter < 80; iter++) {
    const forces: [number, number][] = pts.map(() => [0, 0]);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[j][0] - pts[i][0];
        const dy = pts[j][1] - pts[i][1];
        const dist = Math.hypot(dx, dy) || 0.001;
        const rep = 200 / (dist * dist);
        forces[i][0] -= rep * dx / dist; forces[i][1] -= rep * dy / dist;
        forces[j][0] += rep * dx / dist; forces[j][1] += rep * dy / dist;
      }
    }
    pts.forEach((p, i) => { p[0] += forces[i][0] * 0.5; p[1] += forces[i][1] * 0.5; });
  }
  systems.forEach((s, i) => pos.set(s.system_id64, pts[i]));
  return pos;
}

interface TooltipData { x: number; y: number; system: PPSystemEntry; recoType: "fortify" | "expand" | null; }

export default function Map2DView() {
  const { powerName, centerSystem, setPower, setCenter } = useSelectionState();
  const [systems, setSystems] = useState<PPSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [axis, setAxis] = useState<Axis>("xz");
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("actual");
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);

  const svgRef = useRef<SVGSVGElement>(null);
  const W = 800, H = 600;

  const fortifySet = useMemo(() => new Set((recommendations?.fortify ?? []).map((r) => r.system_name)), [recommendations]);
  const expandSet  = useMemo(() => new Set((recommendations?.expand  ?? []).map((r) => r.system_name)), [recommendations]);
  function recoType(name: string): "fortify" | "expand" | null {
    return fortifySet.has(name) ? "fortify" : expandSet.has(name) ? "expand" : null;
  }

  useEffect(() => {
    if (!powerName) { setSystems([]); setRecommendations(null); return; }
    setLoading(true);
    Promise.all([
      getPowerSystems(powerName, centerSystem?.id),
      getRecommendations(powerName, centerSystem?.id),
    ])
      .then(([sys, recs]) => { setSystems(sys); setRecommendations(recs); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [powerName, centerSystem?.id]);

  const centerIdx = useMemo(() => {
    if (!centerSystem) return null;
    const i = systems.findIndex((s) => s.system_id64 === centerSystem.id);
    return i >= 0 ? i : null;
  }, [systems, centerSystem?.id]);

  const positions = useMemo(
    () => buildPositions(systems, axis, layoutMode, centerIdx),
    [systems, axis, layoutMode, centerIdx]
  );

  useEffect(() => {
    if (!svgRef.current || systems.length === 0) return;
    const svg = d3.select(svgRef.current);
    const g = svg.select<SVGGElement>("g.zoom-layer");
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.1, 20])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);
    svg.call(zoom.transform, d3.zoomIdentity);
  }, [systems, axis, layoutMode]);

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
    <div style={{ padding: "16px 20px", background: "#0d1117", minHeight: "calc(100vh - 44px)", fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3" }}>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", marginBottom: 12 }}>
        <PowerSelector value={powerName} onChange={setPower} />
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

      <div style={{ display: "flex", gap: 12, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
        {PP_STATES_ORDERED.map((state) => (
          <span key={state} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#57606a" }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: ppStateColor(state), display: "inline-block", flexShrink: 0 }} />
            {PP_STATE_LABELS[state] ?? state}
          </span>
        ))}
        <span style={{ fontSize: 11, color: "#57606a", marginLeft: 4 }}>· ⭐ center · <span style={{ color: "#D94A4A" }}>●</span> Fortify · <span style={{ color: "#4A90D9" }}>●</span> Expand</span>
      </div>

      <div style={{ position: "relative", border: "1px solid #e5e7eb", borderRadius: 8, background: "#0a0a1a", overflow: "hidden" }}>
        <svg ref={svgRef} width={W} height={H} style={{ display: "block" }}>
          <g className="zoom-layer">
            {scaleX && scaleY && systems.map((sys) => {
              const p = positions.get(sys.system_id64);
              if (!p) return null;
              const cx2 = scaleX(p[0]);
              const cy2 = scaleY(p[1]);
              const isCenter = sys.system_id64 === centerSystem?.id;
              const reco = recoType(sys.name);
              const color = ppStateColor(sys.power_state);
              const r = 6;
              return (
                <g key={sys.system_id64} transform={`translate(${cx2},${cy2})`} style={{ cursor: "pointer" }}
                  onMouseEnter={(e) => {
                    const rect = (e.currentTarget.closest("svg") as SVGSVGElement).getBoundingClientRect();
                    setTooltip({ x: e.clientX - rect.left + 12, y: e.clientY - rect.top - 8, system: sys, recoType: reco });
                  }}
                  onMouseLeave={() => setTooltip(null)}
                >
                  {reco === "fortify" && <circle r={r + 4} fill="none" stroke="#D94A4A" strokeWidth={2} opacity={0.8} />}
                  {reco === "expand"  && <circle r={r + 4} fill="none" stroke="#4A90D9" strokeWidth={2} opacity={0.8} />}
                  {isCenter ? (
                    <polygon points="0,-10 3,-3 10,-3 4,2 6,10 0,5 -6,10 -4,2 -10,-3 -3,-3" fill="#FFD700" stroke="#fff" strokeWidth={1} />
                  ) : (
                    <circle r={r} fill={color} stroke="rgba(255,255,255,0.4)" strokeWidth={0.8} />
                  )}
                </g>
              );
            })}
          </g>
          <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={11} fill="#57606a">{labelH}</text>
          <text x={10} y={H / 2} textAnchor="middle" fontSize={11} fill="#57606a" transform={`rotate(-90,10,${H / 2})`}>{labelV}</text>
        </svg>

        {tooltip && (
          <div style={{ position: "absolute", left: tooltip.x, top: tooltip.y, background: "rgba(10,10,26,0.92)", color: "#fff", padding: "8px 12px", borderRadius: 6, fontSize: 12, pointerEvents: "none", border: "1px solid #3b82d4", maxWidth: 240, zIndex: 10 }}>
            <div style={{ fontWeight: 700, marginBottom: 4 }}>{tooltip.system.name}</div>
            {tooltip.system.power_state && <div>State: <span style={{ color: ppStateColor(tooltip.system.power_state) }}>{PP_STATE_LABELS[tooltip.system.power_state] ?? tooltip.system.power_state}</span></div>}
            {tooltip.system.reinforcement != null && <div>Reinforcement: {tooltip.system.reinforcement.toLocaleString()}</div>}
            {tooltip.system.undermining != null && <div style={{ color: tooltip.system.undermining > 0 ? "#D94A4A" : undefined }}>Undermining: {tooltip.system.undermining.toLocaleString()}</div>}
            {tooltip.system.undermine_ratio != null && <div>Threat: {(tooltip.system.undermine_ratio * 100).toFixed(0)}%</div>}
            {tooltip.recoType === "fortify" && <div style={{ color: "#D94A4A", marginTop: 4, fontWeight: 600 }}>⚠ Fortify Priority</div>}
            {tooltip.recoType === "expand"  && <div style={{ color: "#4A90D9", marginTop: 4, fontWeight: 600 }}>➕ Expansion Target</div>}
          </div>
        )}
      </div>

      {!powerName && <p style={{ color: "#57606a", fontSize: 14, marginTop: 16 }}>Select a Power to render the 2D map.</p>}
      {powerName && !loading && systems.length === 0 && <p style={{ color: "#57606a", fontSize: 14, marginTop: 16 }}>No system data found. Run a Spansh PP ingest first.</p>}
    </div>
  );
}
