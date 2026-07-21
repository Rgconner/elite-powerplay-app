import { useState } from "react";
import TableView from "./pages/TableView";
import TargetAnalysisView from "./pages/TargetAnalysisView";
import AdminPage from "./pages/AdminPage";

type Tab = "table" | "targets";

const TAB_LABELS: Record<Tab, string> = {
  table:   "📋 Overview",
  targets: "⚔ Target Analysis",
};

export default function App() {
  const [tab, setTab] = useState<Tab>("table");
  const [showAdmin, setShowAdmin] = useState(false);

  if (showAdmin) {
    return <AdminPage onClose={() => setShowAdmin(false)} />;
  }

  return (
    <div style={{ fontFamily: '-apple-system,"Segoe UI",system-ui,sans-serif', background: "#0d1117", minHeight: "100vh" }}>
      {/* Tab bar */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, height: 44,
        background: "#161b22", borderBottom: "1px solid #30363d",
        display: "flex", alignItems: "center", gap: 0, padding: "0 12px",
        zIndex: 1000,
      }}>
        {/* Logo / title */}
        <span style={{
          fontSize: 13, fontWeight: 700, color: "#ff8c00", letterSpacing: "0.03em",
          paddingRight: 20, borderRight: "1px solid #30363d", marginRight: 8,
          whiteSpace: "nowrap",
        }}>
          ⭐ Elite PP Analyzer
        </span>

        {/* Tab buttons */}
        {(["table", "targets"] as Tab[]).map((t) => {
          const active = tab === t;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: "0 16px", height: 44, fontSize: 13,
                fontWeight: active ? 600 : 400,
                color: active ? "#58a6ff" : "#8b949e",
                background: "none", border: "none",
                borderBottom: active ? "2px solid #58a6ff" : "2px solid transparent",
                cursor: "pointer", outline: "none",
                transition: "color 0.15s",
              }}
            >
              {TAB_LABELS[t]}
            </button>
          );
        })}

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Admin button */}
        <button
          onClick={() => setShowAdmin(true)}
          title="Admin panel — data ingestion, scoring weights"
          style={{
            padding: "5px 12px", fontSize: 12,
            color: "#8b949e", background: "none",
            border: "1px solid #30363d", borderRadius: 5,
            cursor: "pointer", transition: "color 0.15s, border-color 0.15s",
          }}
          onMouseEnter={e => {
            (e.currentTarget as HTMLButtonElement).style.color = "#e6edf3";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#58a6ff";
          }}
          onMouseLeave={e => {
            (e.currentTarget as HTMLButtonElement).style.color = "#8b949e";
            (e.currentTarget as HTMLButtonElement).style.borderColor = "#30363d";
          }}
        >
          ⚙ Admin
        </button>
      </div>

      {/* Page content — offset by tab bar height */}
      <div style={{ paddingTop: 44 }}>
        {tab === "table"   && <TableView />}
        {tab === "targets" && <TargetAnalysisView />}
      </div>
    </div>
  );
}
