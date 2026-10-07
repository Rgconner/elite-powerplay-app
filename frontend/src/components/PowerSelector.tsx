import { useState, useEffect, useRef, useCallback } from "react";
import { searchPowers } from "../api/powers";
import { powerColor } from "../constants/ppColors";

interface Props {
  value: string | null;
  onChange: (name: string | null) => void;
}

export default function PowerSelector({ value, onChange }: Props) {
  const [query, setQuery] = useState(value ?? "");
  const [results, setResults] = useState<string[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => { setQuery(value ?? ""); }, [value]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  const search = useCallback((q: string) => {
    if (!q.trim()) { setResults([]); setOpen(false); return; }
    setLoading(true);
    searchPowers(q)
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

  function handleSelect(name: string) {
    onChange(name);
    setQuery(name);
    setOpen(false);
    setResults([]);
  }

  function handleClear() {
    onChange(null);
    setQuery("");
    setResults([]);
    setOpen(false);
  }

  const selectedColor = value ? powerColor(value) : undefined;

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block", minWidth: 240 }}>
      <div style={{
        display: "flex", alignItems: "center", borderRadius: 6, background: "#fff", padding: "0 8px",
        border: selectedColor ? `1px solid ${selectedColor}88` : "1px solid #e5e7eb",
      }}>
        {selectedColor && (
          <span style={{
            width: 8, height: 8, borderRadius: "50%", background: selectedColor,
            flexShrink: 0, marginRight: 6,
          }} />
        )}
        <input
          value={query}
          onChange={handleInput}
          onFocus={() => results.length > 0 && setOpen(true)}
          placeholder="Search Power (e.g. Aisling Duval, Jerome Archer)..."
          style={{
            flex: 1, border: "none", outline: "none", fontSize: 14, padding: "7px 4px",
            background: "transparent", fontFamily: "inherit",
            color: selectedColor ?? "inherit", fontWeight: value ? 600 : undefined,
          }}
        />
        {loading && <span style={{ fontSize: 12, color: "#57606a" }}>…</span>}
        {value && !loading && (
          <button onClick={handleClear} style={{ border: "none", background: "none", cursor: "pointer", color: "#57606a", fontSize: 16, lineHeight: 1, padding: "0 2px" }}>×</button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul style={{ position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 6, listStyle: "none", margin: 0, padding: "4px 0", zIndex: 999, maxHeight: 220, overflowY: "auto", boxShadow: "0 4px 12px rgba(0,0,0,.08)" }}>
          {results.map((name) => {
            const pc = powerColor(name);
            return (
              <li
                key={name}
                onMouseDown={() => handleSelect(name)}
                style={{ padding: "7px 14px", cursor: "pointer", fontSize: 13, color: "#1f2328", display: "flex", alignItems: "center", gap: 8 }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#f7f8fa")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: pc, flexShrink: 0 }} />
                {name}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
