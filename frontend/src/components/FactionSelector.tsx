import { useState, useEffect, useRef, useCallback } from "react";
import { searchFactions, FactionListItem } from "../api/factions";

interface Props {
  value: string | null;
  onChange: (name: string | null) => void;
}

export default function FactionSelector({ value, onChange }: Props) {
  const [query, setQuery] = useState(value ?? "");
  const [results, setResults] = useState<FactionListItem[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Sync input text when external value changes
  useEffect(() => { setQuery(value ?? ""); }, [value]);

  // Close dropdown on outside click
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
    searchFactions(q)
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

  function handleSelect(item: FactionListItem) {
    onChange(item.name);
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
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block", minWidth: 280 }}>
      <div style={{ display: "flex", alignItems: "center", border: "1px solid #e5e7eb", borderRadius: 6, background: "#fff", padding: "0 8px" }}>
        <input
          value={query}
          onChange={handleInput}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search faction..."
          style={{ flex: 1, border: "none", outline: "none", fontSize: 14, padding: "7px 4px", background: "transparent", fontFamily: "inherit" }}
        />
        {loading && <span style={{ fontSize: 12, color: "#57606a" }}>…</span>}
        {value && !loading && (
          <button onClick={handleClear} style={{ border: "none", background: "none", cursor: "pointer", color: "#57606a", fontSize: 16, lineHeight: 1, padding: "0 2px" }}>×</button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul style={{ position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 6, listStyle: "none", margin: 0, padding: "4px 0", zIndex: 999, maxHeight: 220, overflowY: "auto", boxShadow: "0 4px 12px rgba(0,0,0,.08)" }}>
          {results.map((r) => (
            <li
              key={r.name}
              onMouseDown={() => handleSelect(r)}
              style={{ padding: "7px 14px", cursor: "pointer", fontSize: 13, color: "#1f2328" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "#f7f8fa")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <strong>{r.name}</strong>
              <span style={{ marginLeft: 8, color: "#57606a", fontSize: 12 }}>{r.allegiance ?? ""} · {r.system_count} systems</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
