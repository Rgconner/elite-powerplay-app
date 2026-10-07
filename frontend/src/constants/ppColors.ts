/** Map Power Play 2.0 state strings to display colors.
 *
 * Actual PP 2.0 states as returned by Spansh API (confirmed July 2026):
 *   Stronghold   — maximally defended (best possible state for controlling power)
 *   Fortified    — reinforced above threshold
 *   Exploited    — basic controlled state, actively being worked
 *   Unoccupied   — PP bubble presence but no controlling power (expansion target)
 *
 * Legacy / extra states kept for forward compatibility with possible future states.
 */
export function ppStateColor(state: string | null | undefined): string {
  switch (state) {
    case "Stronghold":       return "#00E5CC";   // teal — max defense
    case "Fortified":        return "#4AD94A";   // green — reinforced
    case "Exploited":        return "#8899AA";   // blue-grey — basic controlled
    case "Unoccupied":       return "#7c5cd8";   // purple — no controller, expand target
    // Legacy / forward-compat states
    case "Turmoil":          return "#FF4500";
    case "Undermined":       return "#D94A4A";
    case "Contested":        return "#D9A84A";
    case "Expansion":        return "#4A90D9";
    case "InPrepareRadius":  return "#B06AF0";
    case "Prepared":         return "#C890FF";
    case "HomeSystem":       return "#FFD700";
    default:                 return "#555566";
  }
}

export const PP_STATE_LABELS: Record<string, string> = {
  Stronghold:      "Stronghold",
  Fortified:       "Fortified",
  Exploited:       "Exploited",
  Unoccupied:      "Unoccupied",
  // Legacy
  Turmoil:         "Turmoil",
  Undermined:      "Undermined",
  Contested:       "Contested",
  Expansion:       "Expansion",
  InPrepareRadius: "Prepare Radius",
  Prepared:        "Prepared",
  HomeSystem:      "Home System",
};

/** Ordered list of active PP 2.0 states for legend rendering (confirmed live states first). */
export const PP_STATES_ORDERED = [
  "Stronghold", "Fortified", "Exploited", "Unoccupied",
] as const;

// ── Per-power brand colors ───────────────────────────────────────────────────
// Source: canonical Elite Dangerous lore / community design guides.

export const POWER_COLORS: Record<string, string> = {
  "Arissa Lavigny-Duval": "#9B59B6",  // Purple  (Empire)
  "Zemina Torval":        "#3498DB",  // Blue    (Empire)
  "Aisling Duval":        "#00BCD4",  // Cyan    (Empire)
  "Denton Patreus":       "#BB8FCE",  // Light Purple (Empire)
  "Felicia Winters":      "#F1C40F",  // Gold    (Federation)
  "Edmund Mahon":         "#27AE60",  // Green   (Alliance)
  "Li Yong-Rui":          "#82E0AA",  // Light Green (Independent)
  "Archon Delaine":       "#E74C3C",  // Red     (Independent)
  "Pranav Antal":         "#F39C12",  // Yellow  (Independent)
  "Yuri Grom":            "#E67E22",  // Orange  (Independent)
};

/**
 * Return the brand color for a named power, with a neutral fallback
 * for any power not in the table (forward-compat for future additions).
 */
export function powerColor(name: string | null | undefined): string {
  if (!name) return "#8b949e";
  return POWER_COLORS[name] ?? "#8b949e";
}

// ── Merit decay color ───────────────────────────────────────────────────────
/** Distinctive purple for CP Decay display (unique from R=green, U=red). */
export const CP_DECAY_COLOR = "#B388FF";
