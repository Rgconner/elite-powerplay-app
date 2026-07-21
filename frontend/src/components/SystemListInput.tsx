import { useState, useRef, useEffect } from "react";
import { searchSystems } from "../api/systems";

interface Props {
  value: string[];                          // currently confirmed system names
  onChange: (names: string[]) => void;
  powerName: string | null;                 // used for context in placeholder
}

// ---------------------------------------------------------------------------
// Name parser — extracts plausible system names from free-form text.
//
// Strategy: word-by-word analysis with consecutive grouping.
//
//   1. Split raw text into segments on newlines, commas, etc.
//   2. For each segment:
//      a. Strip leading markers (bullets, dashes, etc.)
//      b. Unwrap matching quotes / brackets / braces
//      c. Strip parenthetical annotations like "(undermined)", "(home system)"
//      d. Split into words and keep only "plausible" words (≥2 chars,
//         not a URL, not a common English/powerplay word)
//      e. Group consecutive plausible words into multi-word candidates
//   3. Deduplicate, preserve order
// ---------------------------------------------------------------------------

const COMMON_WORDS = new Set([
  "the","and","or","for","with","from","into","onto","over","under","near",
  "this","that","these","those","then","than","when","where","which","while",
  "have","has","had","been","being","are","was","were","will","would","could",
  "should","may","might","must","shall","also","but","not","all","any","both",
  "each","few","more","most","other","some","such","very","just","like",
  "now","here","there","yes","no","hi","ok","please","thanks","note","see",
  "per","via","etc","system","systems","power","powers","state","status",
  "fortify","fortified","exploit","exploited","stronghold","unoccupied",
  "merit","merits","reinforce","reinforcement","undermine","undermining",
  "upgrade","upgraded",
  "a","i",
]);

/** Check if a word is a plausible part of a system name. */
function isPlausibleWord(word: string): boolean {
  if (word.length < 1) return false;
  if (/^https?:\/\//i.test(word)) return false;
  if (COMMON_WORDS.has(word.toLowerCase())) return false;
  return true;
}

function parseNames(raw: string): string[] {
  const segments = raw.split(/[\n,;|\t]+/);
  const candidates: string[] = [];

  for (let seg of segments) {
    seg = seg.trim();
    if (!seg) continue;

    // Strip leading bullets, dashes, dots, asterisks
    seg = seg.replace(/^[\s\-•*·>]+/, "").trim();
    if (!seg) continue;

    // Unwrap matching quote/bracket/brace pairs around the whole segment
    if ((seg.startsWith('"') && seg.endsWith('"')) ||
        (seg.startsWith("'") && seg.endsWith("'")) ||
        (seg.startsWith("(") && seg.endsWith(")")) ||
        (seg.startsWith("[") && seg.endsWith("]")) ||
        (seg.startsWith("{") && seg.endsWith("}"))) {
      seg = seg.slice(1, -1).trim();
      if (!seg) continue;
    }

    // Strip parenthetical annotations like "(undermined)", "(home system)"
    seg = seg.replace(/\([^)]*\)/g, "").trim();
    if (!seg) continue;

    // Skip pure-number or URL leftovers
    if (/^\d+$/.test(seg)) continue;
    if (/^https?:\/\//i.test(seg)) continue;

    // Split into words and group consecutive plausible ones
    const words = seg.split(/\s+/);
    let group: string[] = [];

    for (const word of words) {
      const w = word.trim();
      if (!w) continue;

      if (isPlausibleWord(w)) {
        group.push(w);
      } else {
        // Non-plausible word → flush current group
        if (group.length > 0) {
          candidates.push(group.join(" "));
          group = [];
        }
      }
    }

    // Flush final group
    if (group.length > 0) {
      candidates.push(group.join(" "));
    }
  }

  // Deduplicate preserving order
  const seen = new Set<string>();
  return candidates.filter(t => {
    const key = t.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SystemListInput({ value, onChange, powerName }: Props) {
  const [open, setOpen]         = useState(false);
  const [raw, setRaw]           = useState("");
  const [parsed, setParsed]     = useState<string[]>([]);
  const [validating, setValidating] = useState(false);
  const [validated, setValidated]   = useState<{ name: string; found: boolean }[]>([]);
  const [error, setError]       = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  // Close panel when clicking outside
  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  // When raw text changes, re-parse immediately (no API call yet)
  function handleRawChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const text = e.target.value;
    setRaw(text);
    const names = parseNames(text);
    setParsed(names);
    setValidated([]);
    setError(null);
  }

  // Validate parsed names against the API — check each exists in the DB
  async function handleValidate() {
    if (parsed.length === 0) return;
    setValidating(true);
    setError(null);
    try {
      const results = await Promise.all(
        parsed.map(async (name) => {
          try {
            const hits = await searchSystems(name);
            // Exact match (case-insensitive)
            const exact = hits.find(h => h.name.toLowerCase() === name.toLowerCase());
            return { name: exact ? exact.name : name, found: !!exact };
          } catch {
            return { name, found: false };
          }
        })
      );
      setValidated(results);
    } catch {
      setError("Validation failed — check connection");
    } finally {
      setValidating(false);
    }
  }

  // Confirm — push only found names to parent
  function handleApply() {
    const confirmed = validated.filter(v => v.found).map(v => v.name);
    onChange(confirmed);
    setOpen(false);
  }

  // Clear the list
  function handleClear() {
    onChange([]);
    setRaw("");
    setParsed([]);
    setValidated([]);
  }

  const activeCount = value.length;

  return (
    <div ref={wrapRef} style={{ position: "relative", display: "inline-block" }}>
      {/* Trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        title="Filter view to a specific list of systems"
        style={{
          padding: "6px 12px", fontSize: 13, borderRadius: 6, cursor: "pointer",
          background: activeCount > 0 ? "#1f6feb22" : "#161b22",
          border: `1px solid ${activeCount > 0 ? "#1f6feb" : "#30363d"}`,
          color: activeCount > 0 ? "#58a6ff" : "#8b949e",
          fontFamily: "inherit", whiteSpace: "nowrap",
        }}
      >
        🗂 System List {activeCount > 0 ? `(${activeCount})` : ""}
      </button>
      {activeCount > 0 && (
        <button
          onClick={handleClear}
          title="Clear system list filter"
          style={{
            marginLeft: 4, padding: "4px 7px", fontSize: 12, borderRadius: 4,
            background: "none", border: "1px solid #30363d",
            color: "#8b949e", cursor: "pointer",
          }}
        >×</button>
      )}

      {/* Dropdown panel */}
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0,
          width: 420, background: "#161b22", border: "1px solid #30363d",
          borderRadius: 8, zIndex: 1000, boxShadow: "0 8px 24px rgba(0,0,0,.5)",
          padding: 14,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: "#e6edf3", marginBottom: 8 }}>
            Paste or type system names to filter the view
          </div>
          <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 8, lineHeight: 1.5 }}>
            Accepts any format — one per line, comma-separated, or pasted from game chat / spreadsheets.
            Extraneous text is automatically stripped.
          </div>
          <textarea
            value={raw}
            onChange={handleRawChange}
            placeholder={
              powerName
                ? `e.g.\nHR 943\nDeciat, Shinrarta Dezhra\nChamunda`
                : "Select a Power first, then paste system names here..."
            }
            rows={7}
            style={{
              width: "100%", boxSizing: "border-box", resize: "vertical",
              background: "#0d1117", border: "1px solid #30363d", borderRadius: 6,
              color: "#e6edf3", fontSize: 12, fontFamily: "monospace",
              padding: "8px 10px", outline: "none",
            }}
          />

          {/* Parsed preview */}
          {parsed.length > 0 && validated.length === 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>
                {parsed.length} name{parsed.length !== 1 ? "s" : ""} parsed — click Validate to check against database:
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {parsed.slice(0, 30).map(n => (
                  <span key={n} style={{
                    background: "#21262d", border: "1px solid #30363d",
                    borderRadius: 4, padding: "2px 7px", fontSize: 11, color: "#8b949e",
                  }}>{n}</span>
                ))}
                {parsed.length > 30 && (
                  <span style={{ fontSize: 11, color: "#555" }}>+{parsed.length - 30} more</span>
                )}
              </div>
            </div>
          )}

          {/* Validation results */}
          {validated.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: "#8b949e", marginBottom: 4 }}>
                <span style={{ color: "#4AD94A" }}>✓ {validated.filter(v => v.found).length} found</span>
                {validated.filter(v => !v.found).length > 0 && (
                  <span style={{ color: "#D94A4A", marginLeft: 8 }}>
                    ✗ {validated.filter(v => !v.found).length} not found
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, maxHeight: 100, overflowY: "auto" }}>
                {validated.map(v => (
                  <span key={v.name} style={{
                    background: v.found ? "#0d2e17" : "#2d1a1a",
                    border: `1px solid ${v.found ? "#238636" : "#d94a4a44"}`,
                    borderRadius: 4, padding: "2px 7px", fontSize: 11,
                    color: v.found ? "#4AD94A" : "#D94A4A",
                  }}>
                    {v.found ? "✓" : "✗"} {v.name}
                  </span>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div style={{ fontSize: 11, color: "#D94A4A", marginTop: 6 }}>{error}</div>
          )}

          {/* Action buttons */}
          <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "center" }}>
            {validated.length === 0 && parsed.length > 0 && (
              <button
                onClick={handleValidate}
                disabled={validating}
                style={{
                  padding: "6px 14px", fontSize: 12, borderRadius: 5, cursor: "pointer",
                  background: "#1f6feb", border: "none", color: "#fff",
                  fontFamily: "inherit", opacity: validating ? 0.6 : 1,
                }}
              >
                {validating ? "Validating…" : "Validate Names"}
              </button>
            )}
            {validated.filter(v => v.found).length > 0 && (
              <button
                onClick={handleApply}
                style={{
                  padding: "6px 14px", fontSize: 12, borderRadius: 5, cursor: "pointer",
                  background: "#238636", border: "none", color: "#fff",
                  fontFamily: "inherit",
                }}
              >
                Apply {validated.filter(v => v.found).length} System{validated.filter(v => v.found).length !== 1 ? "s" : ""}
              </button>
            )}
            <button
              onClick={() => setOpen(false)}
              style={{
                padding: "6px 12px", fontSize: 12, borderRadius: 5, cursor: "pointer",
                background: "none", border: "1px solid #30363d", color: "#8b949e",
                fontFamily: "inherit",
              }}
            >
              Cancel
            </button>
            {parsed.length > 0 && (
              <button
                onClick={() => { setRaw(""); setParsed([]); setValidated([]); }}
                style={{
                  marginLeft: "auto", padding: "4px 10px", fontSize: 11, borderRadius: 4,
                  background: "none", border: "1px solid #30363d", color: "#555",
                  cursor: "pointer", fontFamily: "inherit",
                }}
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
