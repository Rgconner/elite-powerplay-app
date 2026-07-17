import React, { useState, useEffect, useMemo, useRef } from "react";
import { Canvas, useFrame, ThreeEvent } from "@react-three/fiber";
import { OrbitControls, Stars, Html } from "@react-three/drei";
import * as THREE from "three";
import { getFactionSystems, FactionSystemEntry } from "../api/factions";
import { getRecommendations, RecommendationsResponse } from "../api/recommendations";
import { useSelectionState } from "../hooks/useSelectionState";
import { ppStateColor } from "../constants/ppColors";
import FactionSelector from "../components/FactionSelector";
import CenterSystemSelector from "../components/CenterSystemSelector";
import LayoutModeSelector, { LayoutMode } from "../components/LayoutModeSelector";

// ── Coordinate normalisation ──────────────────────────────────────────────────
function normalizeCoords(
  systems: FactionSystemEntry[],
  mode: LayoutMode,
  centerSystem: FactionSystemEntry | null
): Map<number, THREE.Vector3> {
  const out = new Map<number, THREE.Vector3>();
  if (systems.length === 0) return out;

  if (mode === "actual") {
    // Normalise to fit within ±50 units
    const maxAbs = systems.reduce(
      (m, s) => Math.max(m, Math.abs(s.x), Math.abs(s.y), Math.abs(s.z)),
      1
    );
    const scale = 50 / maxAbs;
    systems.forEach((s) => out.set(s.system_id64, new THREE.Vector3(s.x * scale, s.y * scale, s.z * scale)));
    return out;
  }

  if (mode === "radial") {
    const cx = centerSystem?.x ?? 0;
    const cy = centerSystem?.y ?? 0;
    const cz = centerSystem?.z ?? 0;
    systems.forEach((s, i) => {
      const dist = s.distance_from_center ?? Math.sqrt((s.x - cx) ** 2 + (s.y - cy) ** 2 + (s.z - cz) ** 2);
      const phi = Math.acos(-1 + (2 * i) / systems.length);
      const theta = Math.sqrt(systems.length * Math.PI) * phi;
      out.set(s.system_id64, new THREE.Vector3(
        dist * Math.sin(phi) * Math.cos(theta),
        dist * Math.cos(phi),
        dist * Math.sin(phi) * Math.sin(theta)
      ));
    });
    // Normalise
    const maxR = Math.max(...Array.from(out.values()).map((v) => v.length()), 1);
    const scale = 50 / maxR;
    out.forEach((v) => v.multiplyScalar(scale));
    return out;
  }

  // Force-directed 3D
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

// ── Individual system sphere ──────────────────────────────────────────────────
interface SphereProps {
  system: FactionSystemEntry;
  position: THREE.Vector3;
  isCenter: boolean;
  recoType: "fortify" | "expand" | null;
  onHover: (sys: FactionSystemEntry | null) => void;
}

function SystemSphere({ system, position, isCenter, recoType, onHover }: SphereProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const [hovered, setHovered] = useState(false);
  const color = ppStateColor(system.pp_state);
  const radius = isCenter ? 1.8 : 0.7 + (system.influence ?? 0) * 0.8;

  useFrame(() => {
    if (meshRef.current && isCenter) {
      meshRef.current.rotation.y += 0.01;
    }
  });

  return (
    <group position={position}>
      {/* Recommendation ring */}
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

      {/* System sphere */}
      <mesh
        ref={meshRef}
        onPointerEnter={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); setHovered(true); onHover(system); }}
        onPointerLeave={() => { setHovered(false); onHover(null); }}
      >
        <sphereGeometry args={[radius, 16, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={isCenter ? "#FFD700" : color}
          emissiveIntensity={isCenter ? 1.5 : hovered ? 0.5 : 0.1}
          roughness={0.6}
          metalness={0.2}
        />
      </mesh>

      {/* Hover label */}
      {hovered && (
        <Html distanceFactor={30} style={{ pointerEvents: "none" }}>
          <div style={{ background: "rgba(10,10,26,0.92)", color: "#fff", padding: "6px 10px", borderRadius: 5, fontSize: 11, border: "1px solid #3b82d4", whiteSpace: "nowrap" }}>
            <strong>{system.system_name}</strong>
            {system.pp_state && <div style={{ color: ppStateColor(system.pp_state) }}>{system.pp_state}</div>}
            {system.influence != null && <div>{(system.influence * 100).toFixed(1)}% influence</div>}
          </div>
        </Html>
      )}
    </group>
  );
}

// ── Scene ─────────────────────────────────────────────────────────────────────
interface SceneProps {
  systems: FactionSystemEntry[];
  positions: Map<number, THREE.Vector3>;
  fortifySet: Set<string>;
  expandSet: Set<string>;
  centerSystemId?: number;
  onHover: (sys: FactionSystemEntry | null) => void;
}

function Scene({ systems, positions, fortifySet, expandSet, centerSystemId, onHover }: SceneProps) {
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
        const recoType: "fortify" | "expand" | null = fortifySet.has(sys.system_name)
          ? "fortify"
          : expandSet.has(sys.system_name)
          ? "expand"
          : null;
        return (
          <SystemSphere
            key={sys.system_id64}
            system={sys}
            position={pos}
            isCenter={sys.system_id64 === centerSystemId}
            recoType={recoType}
            onHover={onHover}
          />
        );
      })}
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function Map3DView() {
  const { factionName, centerSystem, setFaction, setCenter } = useSelectionState();

  const [systems, setSystems] = useState<FactionSystemEntry[]>([]);
  const [recommendations, setRecommendations] = useState<RecommendationsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("actual");
  const [hoveredSystem, setHoveredSystem] = useState<FactionSystemEntry | null>(null);

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

  const centerSystemObj = useMemo(
    () => systems.find((s) => s.system_id64 === centerSystem?.id) ?? null,
    [systems, centerSystem?.id]
  );

  const positions = useMemo(
    () => normalizeCoords(systems, layoutMode, centerSystemObj),
    [systems, layoutMode, centerSystemObj]
  );

  const fortifySet = useMemo(() => new Set((recommendations?.fortify ?? []).map((r) => r.system_name)), [recommendations]);
  const expandSet = useMemo(() => new Set((recommendations?.expand ?? []).map((r) => r.system_name)), [recommendations]);

  return (
    <div style={{ fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', color: "#1f2328" }}>
      {/* Controls */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center", padding: "12px 24px", borderBottom: "1px solid #e5e7eb" }}>
        <FactionSelector value={factionName} onChange={setFaction} />
        <CenterSystemSelector value={centerSystem} onChange={setCenter} />
        <LayoutModeSelector value={layoutMode} onChange={setLayoutMode} />
        {loading && <span style={{ fontSize: 13, color: "#57606a" }}>Loading…</span>}
        {systems.length > 0 && !loading && (
          <span style={{ fontSize: 12, color: "#57606a" }}>{systems.length} systems</span>
        )}
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, padding: "6px 24px", flexWrap: "wrap", borderBottom: "1px solid #e5e7eb", background: "#f7f8fa" }}>
        {[
          { color: "#4AD94A", label: "Fortified" },
          { color: "#D94A4A", label: "Undermined" },
          { color: "#FF8C00", label: "Turmoil" },
          { color: "#4A90D9", label: "Expansion" },
          { color: "#D9D94A", label: "Contested" },
          { color: "#FFD700", label: "Center" },
        ].map((l) => (
          <span key={l.label} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#57606a" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: l.color, display: "inline-block" }} />
            {l.label}
          </span>
        ))}
        <span style={{ fontSize: 12, color: "#57606a" }}>Red ring = Fortify · Blue ring = Expand · Drag to rotate · Scroll to zoom</span>
      </div>

      {/* 3D Canvas */}
      {factionName && systems.length > 0 ? (
        <div style={{ height: "calc(100vh - 170px)", background: "#030310" }}>
          <Canvas camera={{ position: [0, 30, 80], fov: 60 }}>
            <Scene
              systems={systems}
              positions={positions}
              fortifySet={fortifySet}
              expandSet={expandSet}
              centerSystemId={centerSystem?.id}
              onHover={setHoveredSystem}
            />
          </Canvas>
        </div>
      ) : (
        <div style={{ padding: "32px 24px" }}>
          {!factionName && <p style={{ color: "#57606a", fontSize: 14 }}>Select a faction to render the 3D map.</p>}
          {factionName && loading && <p style={{ color: "#57606a", fontSize: 14 }}>Loading systems…</p>}
          {factionName && !loading && systems.length === 0 && <p style={{ color: "#57606a", fontSize: 14 }}>No system data found. Run a Spansh ingest first.</p>}
        </div>
      )}

      {/* Hovering system info bar */}
      {hoveredSystem && (
        <div style={{ position: "fixed", bottom: 16, left: "50%", transform: "translateX(-50%)", background: "rgba(10,10,26,0.92)", color: "#fff", padding: "8px 20px", borderRadius: 8, fontSize: 13, border: "1px solid #3b82d4", pointerEvents: "none", zIndex: 100, display: "flex", gap: 16 }}>
          <strong>{hoveredSystem.system_name}</strong>
          {hoveredSystem.pp_state && <span style={{ color: ppStateColor(hoveredSystem.pp_state) }}>{hoveredSystem.pp_state}</span>}
          {hoveredSystem.pp_power && <span>{hoveredSystem.pp_power}</span>}
          {hoveredSystem.influence != null && <span>{(hoveredSystem.influence * 100).toFixed(1)}% influence</span>}
          {hoveredSystem.is_controlling && <span style={{ color: "#4AD94A" }}>Controlling</span>}
        </div>
      )}
    </div>
  );
}
