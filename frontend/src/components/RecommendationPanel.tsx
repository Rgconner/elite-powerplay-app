import { useState } from "react";
import { RecommendationsResponse, RecommendationItem } from "../api/recommendations";
import { ContestedSystemInfo, parseConflictProgress } from "../api/contested";
import { ppStateColor, PP_STATE_LABELS } from "../constants/ppColors";

interface Props {
  recommendations: RecommendationsResponse | null;
  loading: boolean;
  contested: ContestedSystemInfo[];
  loadingContested: boolean;
}

// ── Urgency band helpers ───────────────────────────────────────────────────

function urgencyBand(item: RecommendationItem): {
  label: string; bg: string; fg: string; border: string;
} {
  if (item.type === "expand") return { label: "Expand", bg: "#0d2a4a", fg: "#4A90D9", border: "#1f6feb" };
  const s = item.score;
  const d = item.days_to_failure;
  if (s >= 950 || d === 0)       return { label: "CRITICAL",  bg: "#3d0000", fg: "#FF4444", border: "#D94A4A" };
  if (s >= 750 || (d != null && d < 2))  return { label: "URGENT",    bg: "#3d1a00", fg: "#FF8C00", border: "#FF8C00" };
  if (s >= 550 || (d != null && d < 5))  return { label: "WARNING",   bg: "#2a2000", fg: "#D9A84A", border: "#D9A84A" };
  if (s >= 250)                  return { label: "MONITOR",   bg: "#1a1a2e", fg: "#8899AA", border: "#444" };
  if (s >= 100)                  return { label: "REINFORCE", bg: "#0d2e17", fg: "#4AD94A", border: "#238636" };
  return                                { label: "LOW",        bg: "#161b22", fg: "#8b949e", border: "#30363d" };
}

function DaysBar({ progress, daysToFailure }: { progress: number | null; daysToFailure: number | null }) {
  if (progress == null) return null;
  const pct = Math.max(0, Math.min(1, progress)) * 100;

  // Color the progress bar: red if failing, amber if low, green if healthy
  const barColor = progress <= 0   ? "#D94A4A"
                 : progress < 0.2  ? "#FF8C00"
                 : progress < 0.5  ? "#D9A84A"
                 : progress < 1.0  ? "#4AD94A"
                 : "#00E5CC";   // >= 1.0 = upgrade ready

  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#8b949e", marginBottom: 2 }}>
        <span>Progress: {(progress * 100).toFixed(1)}%</span>
        {daysToFailure === 0     && <span style={{ color: "#D94A4A", fontWeight: 700 }}>Failing NOW</span>}
        {daysToFailure != null && daysToFailure > 0 && daysToFailure < 7 &&
          <span style={{ color: daysToFailure < 2 ? "#FF4444" : daysToFailure < 5 ? "#FF8C00" : "#D9A84A", fontWeight: 600 }}>
            ~{daysToFailure.toFixed(1)}d to downgrade
          </span>
        }
        {progress >= 1.0 && <span style={{ color: "#00E5CC", fontWeight: 600 }}>Upgrade threshold crossed ✓</span>}
      </div>
      <div style={{ height: 4, borderRadius: 2, background: "#21262d", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 2, transition: "width 0.3s" }} />
      </div>
    </div>
  );
}

// Absolute merit thresholds (must match backend scoring.py)
const MERIT_ACQUIRE    = 120_000;
const MERIT_FORTIFIED  = 333_000;
const MERIT_STRONGHOLD = 667_000;

function fmt(n: number): string {
  return n.toLocaleString();
}

function MeritBar({ item }: { item: RecommendationItem }) {
  if (item.merit_position == null || item.control_progress == null) return null;

  const isExpand = item.type === "expand";

  if (isExpand) {
    // Expand items: show 0 → 120k acquisition scale
    const pos  = item.merit_position;
    const pct  = Math.min(100, Math.max(0, (pos / MERIT_ACQUIRE) * 100));
    const p    = item.control_progress;
    const barColor = pct >= 100 ? "#00E5CC"
                   : pct >= 75  ? "#4AD94A"
                   : pct >= 40  ? "#D9A84A"
                   : pct > 0   ? "#4A90D9"
                   : "#555";

    return (
      <div style={{ marginTop: 6 }}>
        {/* Scale bar: 0 → 120k */}
        <div style={{ position: "relative", height: 8, borderRadius: 4, background: "#21262d", overflow: "hidden", marginBottom: 2 }}>
          <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 4, transition: "width 0.3s" }} />
        </div>
        {/* Labels */}
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#555", marginBottom: 4 }}>
          <span>0</span>
          <span style={{ color: "#4A90D9", fontWeight: 700 }}>120k — Acquisition</span>
        </div>
        {/* Merit figures */}
        <div style={{ display: "flex", gap: 12, fontSize: 11, flexWrap: "wrap" }}>
          <span style={{ color: "#8b949e" }}>
            Acquired: <strong style={{ color: barColor }}>{fmt(pos)}</strong>
          </span>
          {item.merits_to_upgrade != null && item.merits_to_upgrade > 0 && (
            <span style={{ color: "#8b949e" }}>
              Still needed: <strong style={{ color: "#4A90D9" }}>{fmt(item.merits_to_upgrade)}</strong>
            </span>
          )}
          {p >= 1.0 && (
            <span style={{ color: "#00E5CC", fontWeight: 700 }}>🚀 Acquisition threshold met — claim now!</span>
          )}
        </div>
      </div>
    );
  }

  // Fortify items: full 0 → 667k scale
  const pos = item.merit_position;
  const pct = Math.min(100, Math.max(0, (pos / MERIT_STRONGHOLD) * 100));
  const p = item.control_progress;
  const barColor = p <= 0   ? "#D94A4A"
                 : p < 0.25 ? "#FF4444"
                 : p < 0.50 ? "#FF8C00"
                 : p < 0.75 ? "#D9A84A"
                 : p < 1.0  ? "#4AD94A"
                 : "#00E5CC";

  return (
    <div style={{ marginTop: 6 }}>
      {/* Scale bar */}
      <div style={{ position: "relative", height: 8, borderRadius: 4, background: "#21262d", overflow: "visible", marginBottom: 2 }}>
        {/* Threshold markers */}
        <div style={{ position: "absolute", left: `${(MERIT_ACQUIRE / MERIT_STRONGHOLD) * 100}%`, top: -2, bottom: -2, width: 1, background: "#4A90D9", opacity: 0.6 }} title="Acquire threshold (120k)" />
        <div style={{ position: "absolute", left: `${(MERIT_FORTIFIED / MERIT_STRONGHOLD) * 100}%`, top: -2, bottom: -2, width: 1, background: "#D9A84A", opacity: 0.6 }} title="Fortified threshold (333k)" />
        {/* Fill */}
        <div style={{ height: "100%", width: `${pct}%`, background: barColor, borderRadius: 4, transition: "width 0.3s" }} />
        {/* Position marker */}
        <div style={{ position: "absolute", left: `${pct}%`, top: -3, width: 2, height: 14, background: "#fff", borderRadius: 1, transform: "translateX(-50%)" }} />
      </div>
      {/* Labels */}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#555", marginBottom: 4 }}>
        <span>0</span>
        <span style={{ color: "#4A90D9" }}>120k</span>
        <span style={{ color: "#D9A84A" }}>333k</span>
        <span>667k</span>
      </div>
      {/* Merit figures */}
      <div style={{ display: "flex", gap: 12, fontSize: 11, flexWrap: "wrap" }}>
        <span style={{ color: "#8b949e" }}>
          Position: <strong style={{ color: "#e6edf3" }}>{fmt(pos)}</strong>
        </span>
        {item.buffer_merits != null && (
          <span style={{ color: "#8b949e" }}>
            Buffer: <strong style={{ color: p < 0.25 ? "#FF4444" : p < 0.5 ? "#FF8C00" : "#4AD94A" }}>{fmt(item.buffer_merits)}</strong>
          </span>
        )}
        {item.merits_to_safety != null && item.merits_to_safety > 0 && (
          <span style={{ color: "#8b949e" }}>
            To safety: <strong style={{ color: "#FF8C00" }}>{fmt(item.merits_to_safety)}</strong>
          </span>
        )}
        {item.merits_to_upgrade != null && item.merits_to_upgrade > 0 && (
          <span style={{ color: "#8b949e" }}>
            To upgrade: <strong style={{ color: "#4A90D9" }}>{fmt(item.merits_to_upgrade)}</strong>
          </span>
        )}
      </div>
    </div>
  );
}

function ItemRow({ item }: { item: RecommendationItem }) {
  const band = urgencyBand(item);
  const r = item.reinforcement ?? 0;
  const u = item.undermining ?? 0;
  const net = r - u;

  return (
    <div style={{
      padding: "10px 12px", marginBottom: 6, borderRadius: 6,
      background: band.bg, border: `1px solid ${band.border}`,
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
        <span style={{
          background: band.fg + "22", color: band.fg, borderRadius: 3,
          padding: "1px 7px", fontSize: 10, fontWeight: 800, letterSpacing: "0.06em",
          border: `1px solid ${band.fg}44`, flexShrink: 0,
        }}>
          {band.label}
        </span>
        <span style={{ fontWeight: 700, fontSize: 13, color: "#e6edf3", flex: 1 }}>{item.system_name}</span>
        {item.power_state && (
          <span style={{
            background: ppStateColor(item.power_state), color: "#fff",
            borderRadius: 4, padding: "2px 7px", fontSize: 10, fontWeight: 600, flexShrink: 0,
          }}>
            {PP_STATE_LABELS[item.power_state] ?? item.power_state}
          </span>
        )}
        <span style={{ fontWeight: 700, fontSize: 12, color: band.fg, flexShrink: 0, minWidth: 52, textAlign: "right" }}>
          {item.score.toFixed(0)} pts
        </span>
      </div>

      {/* Progress bar + days to failure (fortify only) */}
      {item.type === "fortify" && (
        <DaysBar progress={item.control_progress} daysToFailure={item.days_to_failure} />
      )}

      {/* Merit bar — shown for both fortify and expand */}
      <MeritBar item={item} />

      {/* Stats row — fortify */}
      {item.type === "fortify" && (r > 0 || u > 0) && (
        <div style={{ display: "flex", gap: 16, fontSize: 11, color: "#8b949e", marginTop: 5, flexWrap: "wrap" }}>
          <span>R: <strong style={{ color: "#4AD94A" }}>{r.toLocaleString()}</strong></span>
          <span>U: <strong style={{ color: u > r ? "#D94A4A" : "#8b949e" }}>{u.toLocaleString()}</strong></span>
          <span style={{ color: net >= 0 ? "#4AD94A" : "#D94A4A" }}>
            Net: <strong>{net >= 0 ? "+" : ""}{net.toLocaleString()}</strong>
          </span>
          {item.undermine_ratio != null && (
            <span>Threat: <strong style={{ color: item.undermine_ratio > 0.6 ? "#D94A4A" : item.undermine_ratio > 0.3 ? "#D9A84A" : "#4AD94A" }}>
              {(item.undermine_ratio * 100).toFixed(0)}%
            </strong></span>
          )}
          {item.distance_from_center != null && (
            <span>Dist: {item.distance_from_center.toFixed(1)} LY</span>
          )}
        </div>
      )}

      {/* Stats row — expand */}
      {item.type === "expand" && (
        <div style={{ display: "flex", gap: 16, fontSize: 11, color: "#8b949e", marginTop: 5, flexWrap: "wrap" }}>
          {/* Anchor type badge */}
          {item.anchor_type === "fortified" && (
            <span style={{ background: "#1a3a1a", color: "#4AD94A", border: "1px solid #4AD94A44", borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700 }}>
              ⬡ Fortified anchor
            </span>
          )}
          {item.anchor_type === "stronghold" && (
            <span style={{ background: "#1a2a3a", color: "#4A90D9", border: "1px solid #4A90D944", borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700 }}>
              ★ Stronghold anchor
            </span>
          )}
          {item.anchor_type === "both" && (
            <span style={{ background: "#1a2e1a", color: "#00E5CC", border: "1px solid #00E5CC44", borderRadius: 3, padding: "1px 6px", fontSize: 10, fontWeight: 700 }}>
              ★⬡ Stronghold + Fortified
            </span>
          )}
          {item.distance_from_center != null && (
            <span>Dist: {item.distance_from_center.toFixed(1)} LY</span>
          )}
        </div>
      )}

      {/* Reasons */}
      <div style={{ fontSize: 11, color: "#8b949e", marginTop: 5, lineHeight: 1.5 }}>
        {item.reasons.map((r, i) => (
          <div key={i}>{r}</div>
        ))}
        {item.threat_trend === "worsening" && (
          <div style={{ color: "#D94A4A" }}>↗ Trend worsening over time</div>
        )}
        {item.threat_trend === "improving" && (
          <div style={{ color: "#4AD94A" }}>↘ Trend improving over time</div>
        )}
      </div>
    </div>
  );
}

function Section({ title, items, color }: { title: string; items: RecommendationItem[]; color: string }) {
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <h4 style={{ margin: "0 0 10px", fontSize: 12, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {title} <span style={{ color: "#57606a", fontWeight: 400 }}>({items.length})</span>
      </h4>
      {items.length === 0
        ? <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>No recommendations.</p>
        : items.slice(0, 10).map((item) => <ItemRow key={item.system_id64} item={item} />)
      }
    </div>
  );
}

// ── Contested Systems section ──────────────────────────────────────────────

// Power colours for contest progress bars
const CONTEST_COLORS = ["#4A90D9", "#D94A4A", "#4AD94A", "#D9A84A", "#9A4AD9", "#4AD9D9"];

function ContestedRow({ item }: { item: ContestedSystemInfo }) {
  const conflictEntries = parseConflictProgress(item);
  // Acquisition threshold is 120,000 merits; progress > 1.0 means already acquired
  const ACQUIRE_THRESHOLD = 120_000;

  return (
    <div style={{
      padding: "10px 12px", marginBottom: 6, borderRadius: 6,
      background: "#1a1000", border: "1px solid #FF8C0055",
    }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
        <span style={{
          background: "#FF8C0022", color: "#FF8C00", borderRadius: 3,
          padding: "1px 7px", fontSize: 10, fontWeight: 800, letterSpacing: "0.06em",
          border: "1px solid #FF8C0044", flexShrink: 0,
        }}>
          ⚔ CONTESTED
        </span>
        <span style={{ fontWeight: 700, fontSize: 13, flex: 1 }}>
          <a
            href={`https://www.edsm.net/en/system/id/-/name/${encodeURIComponent(item.system_name)}`}
            target="_blank" rel="noreferrer"
            style={{ color: "#FF8C00", textDecoration: "none" }}
          >
            {item.system_name}
          </a>
        </span>
        {item.distance_from_power != null && (
          <span style={{ fontSize: 11, color: item.distance_from_power <= 15 ? "#FF8C00" : "#8b949e" }}>
            {item.distance_from_power.toFixed(1)} LY
          </span>
        )}
      </div>

      {/* Per-power conflict progress bars */}
      {conflictEntries.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {conflictEntries
            .slice()
            .sort((a, b) => b.progress - a.progress)
            .map((entry, idx) => {
              // progress is already normalised 0–1+ where 1.0 = 120k merits acquired
              const normPct = Math.min(100, Math.max(0, entry.progress * 100));
              const color = CONTEST_COLORS[idx % CONTEST_COLORS.length];
              const acquired = entry.progress >= 1.0;
              return (
                <div key={entry.power}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#8b949e", marginBottom: 2 }}>
                    <span style={{ color, fontWeight: 600 }}>{entry.power}</span>
                    <span style={{ color: acquired ? "#00E5CC" : color }}>
                      {acquired ? "🚀 Acquired!" : `${normPct.toFixed(1)}%`}
                    </span>
                  </div>
                  <div style={{ height: 5, borderRadius: 3, background: "#21262d", overflow: "hidden" }}>
                    <div style={{
                      height: "100%", width: `${normPct}%`,
                      background: acquired ? "#00E5CC" : color,
                      borderRadius: 3, transition: "width 0.3s",
                    }} />
                  </div>
                </div>
              );
            })}
        </div>
      ) : (
        /* Fallback: simple single bar when no conflict data */
        item.control_progress != null && (
          <div>
            <div style={{ fontSize: 10, color: "#8b949e", marginBottom: 2 }}>
              Progress: {(item.control_progress * 100).toFixed(1)}%
            </div>
            <div style={{ height: 4, borderRadius: 2, background: "#21262d", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${Math.min(100, item.control_progress * 100)}%`, background: "#FF8C00", borderRadius: 2 }} />
            </div>
          </div>
        )
      )}
    </div>
  );
}

function ContestedSection({ items, loading }: { items: ContestedSystemInfo[]; loading: boolean }) {
  if (!loading && items.length === 0) return null;
  return (
    <div style={{ flex: 1, minWidth: 280 }}>
      <h4 style={{ margin: "0 0 10px", fontSize: 12, fontWeight: 700, color: "#FF8C00", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        ⚔ Contested Systems{" "}
        <span style={{ color: "#57606a", fontWeight: 400 }}>
          {loading ? "(loading…)" : `(${items.length})`}
        </span>
      </h4>
      <p style={{ fontSize: 11, color: "#57606a", margin: "0 0 8px", lineHeight: 1.5 }}>
        Systems with <code style={{ fontSize: 10 }}>power_state = Contested</code> near your territory.
        Listed by proximity — no score applied.
      </p>
      {loading && <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>Loading…</p>}
      {!loading && items.slice(0, 20).map((item) => <ContestedRow key={item.system_id64} item={item} />)}
    </div>
  );
}

export default function RecommendationPanel({ recommendations, loading, contested, loadingContested }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  const criticalCount = recommendations?.fortify.filter(i => i.score >= 950 || i.days_to_failure === 0).length ?? 0;
  const urgentCount   = recommendations?.fortify.filter(i => i.score >= 750 && i.score < 950 && i.days_to_failure !== 0).length ?? 0;

  return (
    <div style={{ background: "#0d1117", border: "1px solid #30363d", borderRadius: 8, margin: "12px 0", overflow: "hidden" }}>
      {/* Header */}
      <div
        style={{ display: "flex", alignItems: "center", padding: "10px 16px", cursor: "pointer", userSelect: "none", borderBottom: collapsed ? "none" : "1px solid #21262d" }}
        onClick={() => setCollapsed((c) => !c)}
      >
        <span style={{ fontWeight: 700, fontSize: 14, color: "#e6edf3", flex: 1 }}>Recommendations</span>
        {loading && <span style={{ fontSize: 12, color: "#57606a", marginRight: 12 }}>Loading…</span>}
        {!loading && recommendations && (
          <div style={{ display: "flex", gap: 8, marginRight: 12, alignItems: "center" }}>
            {criticalCount > 0 && (
              <span style={{ background: "#3d0000", color: "#FF4444", border: "1px solid #D94A4A", borderRadius: 4, padding: "1px 8px", fontSize: 11, fontWeight: 700 }}>
                {criticalCount} CRITICAL
              </span>
            )}
            {urgentCount > 0 && (
              <span style={{ background: "#3d1a00", color: "#FF8C00", border: "1px solid #FF8C00", borderRadius: 4, padding: "1px 8px", fontSize: 11, fontWeight: 700 }}>
                {urgentCount} URGENT
              </span>
            )}
            <span style={{ fontSize: 12, color: "#57606a" }}>
              {recommendations.fortify.length} fortify · {recommendations.expand.length} expand
              {(contested.length > 0 || loadingContested) && (
                <span style={{ marginLeft: 6, color: "#FF8C00", fontWeight: 700 }}>
                  · {loadingContested ? "…" : contested.length} ⚔ contested
                </span>
              )}
            </span>
          </div>
        )}
        <span style={{ color: "#57606a", fontSize: 13 }}>{collapsed ? "▼ Show" : "▲ Hide"}</span>
      </div>

      {!collapsed && (
        <div style={{ padding: "12px 16px 16px" }}>
          {recommendations?.llm_summary && (
            <p style={{ fontStyle: "italic", fontSize: 13, color: "#79c0ff", margin: "0 0 16px", lineHeight: 1.6, borderLeft: "3px solid #1f6feb", paddingLeft: 12, background: "#051d2c", padding: "8px 8px 8px 14px", borderRadius: "0 4px 4px 0" }}>
              {recommendations.llm_summary}
            </p>
          )}
          {!recommendations && !loading && (
            <p style={{ fontSize: 13, color: "#57606a", margin: 0 }}>Select a Power to see recommendations.</p>
          )}
          {(recommendations || contested.length > 0 || loadingContested) && (
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {recommendations && (
                <>
                  <Section title="Fortify Priorities" items={recommendations.fortify} color="#D94A4A" />
                  <Section title="Expansion Targets"  items={recommendations.expand}  color="#4A90D9" />
                </>
              )}
              <ContestedSection items={contested} loading={loadingContested} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
