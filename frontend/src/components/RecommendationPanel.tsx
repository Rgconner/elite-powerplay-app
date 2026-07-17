import React, { useState } from "react";
import { RecommendationsResponse, RecommendationItem } from "../api/recommendations";
import { ppStateColor } from "../constants/ppColors";

interface Props {
  recommendations: RecommendationsResponse | null;
  loading: boolean;
}

function Badge({ state }: { state: string | null }) {
  if (!state) return null;
  return (
    <span style={{ background: ppStateColor(state), color: "#fff", borderRadius: 4, padding: "2px 7px", fontSize: 11, fontWeight: 600, whiteSpace: "nowrap" }}>
      {state}
    </span>
  );
}

function ItemRow({ item }: { item: RecommendationItem }) {
  return (
    <div style={{ padding: "8px 0", borderBottom: "1px solid #f0f0f0", display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 600, fontSize: 13, color: "#1f2328" }}>{item.system_name}</span>
        <Badge state={item.pp_state} />
        <span style={{ marginLeft: "auto", fontWeight: 600, fontSize: 13, color: item.type === "fortify" ? "#D94A4A" : "#3b82d4" }}>
          {item.score.toFixed(0)} pts
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#57606a" }}>
        {item.reasons.join(" · ")}
        {item.distance_from_center != null && (
          <span style={{ marginLeft: 8 }}>· {item.distance_from_center.toFixed(1)} LY</span>
        )}
        {item.influence != null && (
          <span style={{ marginLeft: 8 }}>· {(item.influence * 100).toFixed(1)}% influence</span>
        )}
      </div>
    </div>
  );
}

function Section({ title, items, color }: { title: string; items: RecommendationItem[]; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 260 }}>
      <h4 style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.04em" }}>{title}</h4>
      {items.length === 0
        ? <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>No recommendations.</p>
        : items.slice(0, 10).map((item) => <ItemRow key={item.system_id64} item={item} />)
      }
    </div>
  );
}

export default function RecommendationPanel({ recommendations, loading }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div style={{ background: "#f7f8fa", border: "1px solid #e5e7eb", borderRadius: 8, margin: "12px 0", overflow: "hidden" }}>
      {/* Header */}
      <div
        style={{ display: "flex", alignItems: "center", padding: "10px 16px", cursor: "pointer", userSelect: "none" }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span style={{ fontWeight: 600, fontSize: 14, color: "#1f2328", flex: 1 }}>Recommendations</span>
        {loading && <span style={{ fontSize: 12, color: "#57606a", marginRight: 12 }}>Loading…</span>}
        {!loading && recommendations && (
          <span style={{ fontSize: 12, color: "#57606a", marginRight: 12 }}>
            {recommendations.fortify.length} fortify · {recommendations.expand.length} expand
          </span>
        )}
        <span style={{ color: "#57606a", fontSize: 13 }}>{collapsed ? "▼ Show" : "▲ Hide"}</span>
      </div>

      {!collapsed && (
        <div style={{ padding: "0 16px 16px" }}>
          {/* LLM summary */}
          {recommendations?.llm_summary && (
            <p style={{ fontStyle: "italic", fontSize: 13, color: "#57606a", margin: "0 0 16px", lineHeight: 1.6, borderLeft: "3px solid #3b82d4", paddingLeft: 12 }}>
              {recommendations.llm_summary}
            </p>
          )}

          {!recommendations && !loading && (
            <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>Select a faction to see recommendations.</p>
          )}

          {recommendations && (
            <div style={{ display: "flex", gap: 32, flexWrap: "wrap" }}>
              <Section title="Fortify Priorities" items={recommendations.fortify} color="#D94A4A" />
              <Section title="Expansion Targets" items={recommendations.expand} color="#3b82d4" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
