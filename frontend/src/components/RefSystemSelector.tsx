import { useState, useEffect, useRef, useCallback } from "react";
import { searchSystems, SystemSearchResult } from "../api/systems";
import { SelectedSystem } from "../hooks/useSelectionState";

interface Props {
  value: SelectedSystem | null;
  onChange: (system: SelectedSystem | null) => void;
}

export default function RefSystemSelector({ value, onChange }: Props) {
  const [query, setQuery] = useState(value?.name ?? "");
  const [results, setResults] = useState<SystemSearchResult[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setQuery(value?.name ?? ""); }, [value]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const search = useCallback((q: string) => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    setLoading(true);
    searchSystems(q)
      .then((r) => { setResults(r); setOpen(true); })
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
  }, []);

  function handleInput(e: React.ChangeEvent<HTMLInputElement>) {
    const q = e.target.value;
    setQuery(q);
    if (!q) { onChange(null); setResults([]); setOpen(false); return; }
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => search(q), 300);
  }

  function handleSelect(item: SystemSearchResult) {
    onChange({ id: item.system_id64, name: item.name });
    setQuery(item.name);
    setOpen(false);
    setResults([]);
  }

  function handleClear() {
    onChange(null);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block", minWidth: 240 }}>
      <div style={{ display: "flex", alignItems: "center", border: "1px solid #30363d", borderRadius: 6, background: "#161b22", padding: "0 8px" }}>
        <span style={{ fontSize: 11, color: "#8b949e", whiteSpace: "nowrap", marginRight: 4, userSelect: "none" }}>
          📍 Ref:
        </span>
        <input
          value={query}
          onChange={handleInput}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Reference system (optional)..."
          style={{
            flex: 1, border: "none", outline: "none", fontSize: 13,
            padding: "7px 4px", background: "transparent",
            fontFamily: "inherit", color: "#e6edf3",
          }}
        />
        {loading && <span style={{ fontSize: 12, color: "#8b949e" }}>…</span>}
        {value && !loading && (
          <button
            onClick={handleClear}
            title="Clear reference system"
            style={{ border: "none", background: "none", cursor: "pointer", color: "#8b949e", fontSize: 16, lineHeight: 1, padding: "0 2px" }}
          >×</button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul style={{
          position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0,
          background: "#161b22", border: "1px solid #30363d", borderRadius: 6,
          listStyle: "none", margin: 0, padding: "4px 0", zIndex: 999,
          maxHeight: 200, overflowY: "auto", boxShadow: "0 4px 12px rgba(0,0,0,.4)",
        }}>
          {results.map((r) => (
            <li
              key={r.system_id64}
              onMouseDown={() => handleSelect(r)}
              style={{ padding: "7px 14px", cursor: "pointer", fontSize: 13, color: "#e6edf3" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#21262d")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <strong>{r.name}</strong>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
