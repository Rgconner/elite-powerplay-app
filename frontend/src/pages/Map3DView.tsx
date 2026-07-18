import { useState, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Stars, Html } from "@react-three/drei";
import * as THREE from "three";
import { getPowerSystems, PPSystemEntry } from "../api/powers";
import { getRecommendations, RecommendationsResponse } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor, PP_STATE_LABELS, PP_STATES_ORDERED } from "../constants/ppColors";
import PowerSelector from "../components/PowerSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import LayoutModeSelector, { LayoutMode } from "../components/LayoutModeSelector";

function normalizeCoords(systems: PPSystemEntry[], mode: LayoutMode, center: PPSystemEntry | null): Map<number, THREE.Vector3> {
  const out = new Map<number, THREE.Vector3>();
  if (systems.length === 0) return out;

  if (mode === "actual") {
    const maxAbs = systems.reduce((m, s) => Math.max(m, Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)), 1);
    const scale = 50 / maxAbs;
    systems.forEach((s) => out.set(s.system_id64, new THREE.Vector3(s.x * scale, s.y * scale, s.z * scale)));
    return out;
  }

  if (mode === "radial") {
    const cx = center?.x ?? 0, cy = center?.y ?? 0, cz = center?.z ?? 0;
    systems.forEach((s, i) => {
      const dist = s.distance_from_center ?? Math.sqrt((s.x-cx)**2+(s.y-cy)**2+(s.z-cz)**2);
      const phi = Math.acos(-1 + (2 * i) / systems.length);
      const theta = Math.sqrt(systems.length * Math.PI) * phi;
      out.set(s.system_id64, new THREE.Vector3(dist*Math.sin(phi)*Math.cos(theta), dist*Math.cos(phi), dist*Math.sin(phi)*Math.sin(theta)));
    });
    const maxR = Math.max(...Array.from(out.values()).map((v) => v.length()), 1);
    const scale = 50 / maxR;
    out.forEach((v) => v.multiplyScalar(scale));
    return out;
  }

  const pts: THREE.Vector3[] = systems.map((s) => new THREE.Vector3(s.x, s.y, s.z));
  const maxAbs = pts.reduce((m, v) => Math.max(m, v.length()), 1);
  pts.forEach((v) => v.multiplyScalar(50 / maxAbs));
  for (let iter = 0; iter < 60; iter++) {
    const forces: THREE.Vector3[] = pts.map(() => new THREE.Vector3());
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const diff = new THREE.Vector3().subVectors(pts[j], pts[i]);
        const dist = diff.length() || 0.001;
        const rep = 300 / (dist * dist);
        const dir = diff.clone().normalize();
        forces[i].addScaledVector(dir, -rep);
        forces[j].addScaledVector(dir, rep);
      }
    }
    pts.forEach((p, i) => p.addScaledVector(forces[i], 0.3));
  }
  systems.forEach((s, i) => out.set(s.system_id64, pts[i]));
  return out;
}

// ── Slider sub-component ────────────────────────────────────────────────────

function FilterSlider({
  label, value, min, max, step, unit, onChange, disabled,
}: {
  label: string; value: number; min: number; max: number; step: number;
  unit: string; onChange: (v: number) => void; disabled?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 180 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#8b949e" }}>
        <span>{label}</span>
        <span style={{ color: disabled ? "#555" : "#e6edf3", fontWeight: 600 }}>
          {value >= max ? `Any` : `≤ ${value}${unit}`}
        </span>
      </div>
      <input
        type="range" min={min} max={max} step={step} value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        style={{
          width: "100%", accentColor: "#3b82d4",
          cursor: disabled ? "not-allowed" : "pointer",
          opacity: disabled ? 0.4 : 1,
        }}
      />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#555" }}>
        <span>{min}{unit}</span>
        <span>Any</span>
      </div>
    </div>
  );
}

// ── 3D sphere component ────────────────────────────────────────────────────

interface SphereProps {
  system: PPSystemEntry;
  position: THREE.Vector3;
  isCenter: boolean;
  recoType: "fortify" | "expand" | null;
  onHover: (s: PPSystemEntry | null) => void;
}

function SystemSphere({ system, position, isCenter, recoType, onHover }: SphereProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const color = ppStateColor(system.power_state);
  const radius = isCenter ? 1.8 : 0.8 + (system.undermine_ratio ?? 0) * 0.8;

  useFrame(() => { if (meshRef.current && isCenter) meshRef.current.rotation.y += 0.01; });

  return (
    <group position={position}>
      {recoType === "fortify" && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[radius + 0.8, 0.15, 8, 32]} />
          <meshStandardMaterial color="#D94A4A" emissive="#D94A4A" emissiveIntensity={0.6} />
        </mesh>
      )}
      {recoType === "expand" && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[radius + 0.8, 0.15, 8, 32]} />
          <meshStandardMaterial color="#4A90D9" emissive="#4A90D9" emissiveIntensity={0.6} />
        </mesh>
      )}
      <mesh ref={meshRef}
        onPointerEnter={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); setHovered(true); onHover(system); }}
        onPointerLeave={() => { setHovered(false); onHover(null); }}
      >
        <sphereGeometry args={[radius, 16, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={isCenter ? "#FFD700" : color}
          emissiveIntensity={isCenter ? 1.5 : hovered ? 0.5 : 0.1}
          roughness={0.6} metalness={0.2}
        />
      </mesh>
      {hovered && (
        <Html distanceFactor={30} style={{ pointerEvents: "none" }}>
          <div style={{ background: "rgba(10,10,26,0.92)", color: "#fff", padding: "6px 10px", borderRadius: 5, fontSize: 11, border: "1px solid #3b82d4", whiteSpace: "nowrap" }}>
            <strong>{system.name}</strong>
            {system.power_state && <div style={{ color: ppStateColor(system.power_state) }}>{PP_STATE_LABELS[system.power_state] ?? system.power_state}</div>}
            {system.reinforcement != null && <div>R: {system.reinforcement.toLocaleString()}</div>}
            {system.undermining != null && <div style={{ color: system.undermining > 0 ? "#D94A4A" : undefined }}>U: {system.undermining.toLocaleString()}</div>}
            {system.undermine_ratio != null && <div>Threat: {(system.undermine_ratio * 100).toFixed(0)}%</div>}
            {system.distance_from_center != null && <div>Dist: {system.distance_from_center.toFixed(1)} LY</div>}
          </div>
        </Html>
      )}
    </group>
  );
}

function Scene({ systems, positions, fortifySet, expandSet, centerSystemId, onHover }: {
  systems: PPSystemEntry[]; positions: Map<number, THREE.Vector3>;
  fortifySet: Set<string>; expandSet: Set<string>;
  centerSystemId?: number; onHover: (s: PPSystemEntry | null) => void;
}) {
  return (
    <>
      <ambientLight intensity={0.4} />
      <pointLight position={[50, 50, 50]} intensity={1.2} />
      <pointLight position={[-50, -50, -50]} intensity={0.5} />
      <Stars radius={200} depth={80} count={3000} factor={4} saturation={0} fade />
      <OrbitControls enableDamping dampingFactor={0.08} />
      {systems.map((sys) => {
        const pos = positions.get(sys.system_id64);
        if (!pos) return null;
        const reco: "fortify" | "expand" | null = fortifySet.has(sys.name) ? "fortify" : expandSet.has(sys.name) ? "expand" : null;
        return (
          <SystemSphere key={sys.system_id64} system={sys} position={pos}
            isCenter={sys.system_id64 === centerSystemId}
            recoType={reco} onHover={onHover} />
        );
      })}
    </>
  );
}

export default function Map3DView() {
  const { powerName, centerSystem, setPower, setCenter } = useSelectionState();
  const [systems, setSystems] = useState<PPSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("actual");
  const [hoveredSystem, setHoveredSystem] = useState<PPSystemEntry | null>(null);

  // ── Two separate filter sliders ────────────────────────────────────────────
  // Slider 1: Max distance from center (LY). Only active when a center is set.
  const [maxDistLY, setMaxDistLY] = useState<number>(500);
  // Slider 2: Min undermine ratio threshold (%). Show systems at or above this threat level.
  const [minThreatPct, setMinThreatPct] = useState<number>(0);

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

  const centerObj = useMemo(() => systems.find((s) => s.system_id64 === centerSystem?.id) ?? null, [systems, centerSystem?.id]);

  // Apply filters before rendering
  const filteredSystems = useMemo(() => {
    return systems.filter((s) => {
      // Distance filter (only when center is set)
      if (centerSystem && maxDistLY < 500) {
        const dist = s.distance_from_center;
        if (dist != null && dist > maxDistLY) return false;
      }
      // Threat % filter
      if (minThreatPct > 0) {
        const ratio = s.undermine_ratio ?? 0;
        if (ratio * 100 < minThreatPct) return false;
      }
      return true;
    });
  }, [systems, centerSystem, maxDistLY, minThreatPct]);

  const positions = useMemo(() => normalizeCoords(filteredSystems, layoutMode, centerObj), [filteredSystems, layoutMode, centerObj]);
  const fortifySet = useMemo(() => new Set((recommendations?.fortify ?? []).map((r) => r.system_name)), [recommendations]);
  const expandSet  = useMemo(() => new Set((recommendations?.expand  ?? []).map((r) => r.system_name)), [recommendations]);

  const hiddenCount = systems.length - filteredSystems.length;

  return (
    <div style={{ fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', color: "#e6edf3", background: "#0d1117", minHeight: "calc(100vh - 44px)" }}>
      {/* Row 1: Controls */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", padding: "12px 20px", borderBottom: "1px solid #30363d" }}>
        <PowerSelector value={powerName} onChange={setPower} />
        <CenterSystemSelector value={centerSystem} onChange={setCenter} />
        <LayoutModeSelector value={layoutMode} onChange={setLayoutMode} />
        {loading && <span style={{ fontSize: 13, color: "#8b949e" }}>Loading…</span>}
        {systems.length > 0 && !loading && (
          <span style={{ fontSize: 12, color: "#8b949e" }}>
            {filteredSystems.length}{hiddenCount > 0 ? ` / ${systems.length}` : ""} systems
          </span>
        )}
      </div>

      {/* Row 2: Two separate filter sliders */}
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap", alignItems: "flex-end", padding: "10px 20px", background: "#161b22", borderBottom: "1px solid #21262d" }}>
        <FilterSlider
          label="Max Distance from Center (LY)"
          value={maxDistLY}
          min={10} max={500} step={10}
          unit=" LY"
          onChange={setMaxDistLY}
          disabled={!centerSystem}
        />
        <FilterSlider
          label="Min Threat Level (Undermine %)"
          value={minThreatPct}
          min={0} max={100} step={5}
          unit="%"
          onChange={setMinThreatPct}
        />
        {hiddenCount > 0 && (
          <span style={{ fontSize: 12, color: "#57606a", alignSelf: "center" }}>
            {hiddenCount} system{hiddenCount !== 1 ? "s" : ""} hidden
          </span>
        )}
        {(maxDistLY < 500 || minThreatPct > 0) && (
          <button
            onClick={() => { setMaxDistLY(500); setMinThreatPct(0); }}
            style={{ padding: "4px 10px", fontSize: 11, borderRadius: 4, border: "1px solid #555", background: "#21262d", color: "#8b949e", cursor: "pointer", alignSelf: "center" }}
          >
            Reset Filters
          </button>
        )}
      </div>

      {/* Row 3: Legend */}
      <div style={{ display: "flex", gap: 12, padding: "6px 20px", flexWrap: "wrap", alignItems: "center", borderBottom: "1px solid #30363d", background: "#161b22" }}>
        {PP_STATES_ORDERED.map((state) => (
          <span key={state} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, color: "#8b949e" }}>
            <span style={{ width: 9, height: 9, borderRadius: "50%", background: ppStateColor(state), display: "inline-block", flexShrink: 0 }} />
            {PP_STATE_LABELS[state] ?? state}
          </span>
        ))}
        <span style={{ fontSize: 11, color: "#8b949e", marginLeft: 4 }}>
          · <span style={{ color: "#FFD700" }}>★</span> center · <span style={{ color: "#D94A4A" }}>●</span> Fortify · <span style={{ color: "#4A90D9" }}>●</span> Expand · Drag to rotate · Scroll to zoom
        </span>
      </div>

      {powerName && filteredSystems.length > 0 ? (
        <div style={{ height: "calc(100vh - 175px)", background: "#030310" }}>
          <Canvas camera={{ position: [0, 30, 80], fov: 60 }}>
            <Scene systems={filteredSystems} positions={positions} fortifySet={fortifySet} expandSet={expandSet}
              centerSystemId={centerSystem?.id} onHover={setHoveredSystem} />
          </Canvas>
        </div>
      ) : (
        <div style={{ padding: "32px 20px" }}>
          {!powerName && <p style={{ color: "#8b949e", fontSize: 14 }}>Select a Power to render the 3D map.</p>}
          {powerName && loading && <p style={{ color: "#8b949e", fontSize: 14 }}>Loading systems…</p>}
          {powerName && !loading && systems.length === 0 && <p style={{ color: "#8b949e", fontSize: 14 }}>No system data found. Run a Spansh ingest first.</p>}
          {powerName && !loading && systems.length > 0 && filteredSystems.length === 0 && (
            <p style={{ color: "#8b949e", fontSize: 14 }}>
              All {systems.length} systems filtered out. Adjust the sliders above.
            </p>
          )}
        </div>
      )}

      {hoveredSystem && (
        <div style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", background: "rgba(10,10,26,0.92)", color: "#fff", padding: "8px 20px", borderRadius: 8, fontSize: 13, border: "1px solid #3b82d4", pointerEvents: "none", zIndex: 100, display: "flex", gap: 16 }}>
          <strong>{hoveredSystem.name}</strong>
          {hoveredSystem.power_state && <span style={{ color: ppStateColor(hoveredSystem.power_state) }}>{PP_STATE_LABELS[hoveredSystem.power_state] ?? hoveredSystem.power_state}</span>}
          {hoveredSystem.reinforcement != null && <span>R: {hoveredSystem.reinforcement.toLocaleString()}</span>}
          {hoveredSystem.undermining != null && <span style={{ color: hoveredSystem.undermining > 0 ? "#D94A4A" : undefined }}>U: {hoveredSystem.undermining.toLocaleString()}</span>}
          {hoveredSystem.undermine_ratio != null && <span>Threat: {(hoveredSystem.undermine_ratio * 100).toFixed(0)}%</span>}
          {hoveredSystem.distance_from_center != null && <span>Dist: {hoveredSystem.distance_from_center.toFixed(1)} LY</span>}
        </div>
      )}
    </div>
  );
}
