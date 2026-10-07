import { useState, useEffect, useRef } from "react";
import { listPowers } from "../api/powers";
import { powerColor } from "../constants/ppColors";

interface Props {
  value: string | null;
  onChange: (name: string | null) => void;
}

// The Power list is small (12) and fixed for a session, so fetch it once and share it
// across every page that renders a selector.
let powersCache: Promise<string[]> | null = null;
function loadPowers(): Promise<string[]> {
  if (!powersCache) {
    powersCache = listPowers().catch((err) => {
      powersCache = null; // allow a retry on the next open
      throw err;
    });
  }
  return powersCache;
}

export default function PowerSelector({ value, onChange }: Props) {
  const [powers, setPowers] = useState<string[]>([]);
  const [error, setError] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    loadPowers().then((p) => { setPowers(p); setError(false); }).catch(() => setError(true));
  }, []);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  function openList() {
    if (error) {
      loadPowers().then((p) => { setPowers(p); setError(false); }).catch(() => setError(true));
    }
    setActive(Math.max(0, value ? powers.indexOf(value) : 0));
    setOpen(true);
  }

  function handleSelect(name: string) {
    onChange(name);
    setOpen(false);
  }

  function handleKey(e: React.KeyboardEvent) {
    if (!open) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") { e.preventDefault(); openList(); }
      return;
    }
    if (e.key === "Escape") { e.preventDefault(); setOpen(false); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(powers.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if ((e.key === "Enter" || e.key === " ") && active >= 0) { e.preventDefault(); handleSelect(powers[active]); }
  }

  const selectedColor = value ? powerColor(value) : undefined;

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block", minWidth: 260 }}>
      <div style={{
        display: "flex", alignItems: "center", borderRadius: 6, background: "#161b22", padding: "0 8px",
        border: selectedColor ? `1px solid ${selectedColor}88` : "1px solid #30363d",
      }}>
        <span style={{ fontSize: 11, color: "#8b949e", whiteSpace: "nowrap", marginRight: 4, userSelect: "none" }}>
          Power:
        </span>
        <button
          type="button"
          aria-haspopup="listbox"
          aria-expanded={open}
          onClick={() => (open ? setOpen(false) : openList())}
          onKeyDown={handleKey}
          style={{
            flex: 1, display: "flex", alignItems: "center", gap: 6, border: "none", background: "transparent",
            cursor: "pointer", fontSize: 14, padding: "7px 4px", fontFamily: "inherit", textAlign: "left",
            color: selectedColor ?? "#e6edf3", fontWeight: value ? 600 : 400,
          }}
        >
          {selectedColor && (
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: selectedColor, flexShrink: 0 }} />
          )}
          <span style={{ flex: 1 }}>{value ?? "Select a Power to begin"}</span>
          <span aria-hidden style={{ color: "#8b949e", fontSize: 11 }}>{open ? "▲" : "▼"}</span>
        </button>
        {value && (
          <button
            type="button"
            aria-label="Clear Power"
            onClick={() => onChange(null)}
            style={{ border: "none", background: "none", cursor: "pointer", color: "#8b949e", fontSize: 16, lineHeight: 1, padding: "0 2px" }}
          >×</button>
        )}
      </div>
      {open && (
        <ul role="listbox" style={{
          position: "absolute", top: "calc(100% + 2px)", left: 0, right: 0, background: "#161b22",
          border: "1px solid #30363d", borderRadius: 6, listStyle: "none", margin: 0, padding: "4px 0",
          zIndex: 999, maxHeight: 320, overflowY: "auto", boxShadow: "0 8px 24px rgba(0,0,0,.4)",
        }}>
          {error && (
            <li style={{ padding: "7px 14px", fontSize: 13, color: "#f85149" }}>Couldn't load Powers. Close and reopen to retry.</li>
          )}
          {!error && powers.length === 0 && (
            <li style={{ padding: "7px 14px", fontSize: 13, color: "#8b949e" }}>Loading Powers…</li>
          )}
          {powers.map((name, i) => {
            const pc = powerColor(name);
            const highlighted = i === active;
            return (
              <li
                key={name}
                role="option"
                aria-selected={name === value}
                onMouseDown={() => handleSelect(name)}
                onMouseEnter={() => setActive(i)}
                style={{
                  padding: "7px 14px", cursor: "pointer", fontSize: 13, display: "flex", alignItems: "center", gap: 8,
                  color: "#e6edf3", background: highlighted ? "#21262d" : "transparent",
                  fontWeight: name === value ? 600 : 400,
                }}
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
