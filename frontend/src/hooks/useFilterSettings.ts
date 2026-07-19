/**
 * useFilterSettings — centralised filter state with optional cookie persistence.
 *
 * All TableView sliders/filters live here.  Adding a new filter:
 *   1. Add a field to FilterSettings with a default value in DEFAULTS.
 *   2. Expose a setter.
 *   3. The cookie read/write is automatic — no other changes needed.
 *
 * Cookie name: "pp_filter_settings"
 * Cookie lifetime: 365 days (rolling — refreshed on every change).
 * If the cookie exists on mount, saveEnabled is initialised to true and
 * values are loaded from the cookie.  If the cookie does not exist,
 * saveEnabled is false and DEFAULTS are used.
 */

import { useState, useEffect, useCallback } from "react";

// ── Shape of persisted settings ────────────────────────────────────────────

export interface FilterSettings {
  /** Expand distance filter — hide expand targets anchored from a Fortified system > N LY */
  expandFortDist: number;
  /** Expand distance filter — hide expand targets anchored from a Stronghold system > N LY */
  expandShDist: number;
  /** Expansion merit filter — hide expand targets with fewer than N merits needed */
  expandMinMerits: number;
  /** Contested gap filter — hide contested systems where top power leads next by > N % */
  contestedMaxGap: number;
}

// ── Defaults (used when no cookie present) ────────────────────────────────

export const FILTER_DEFAULTS: FilterSettings = {
  expandFortDist:  20,
  expandShDist:    30,
  expandMinMerits: 0,
  contestedMaxGap: 100,   // 100 = effectively "show all"
};

// ── Cookie helpers ─────────────────────────────────────────────────────────

const COOKIE_NAME = "pp_filter_settings";
const COOKIE_DAYS = 365;

function readCookie(): FilterSettings | null {
  const match = document.cookie
    .split("; ")
    .find(row => row.startsWith(COOKIE_NAME + "="));
  if (!match) return null;
  try {
    const raw = decodeURIComponent(match.split("=").slice(1).join("="));
    const parsed = JSON.parse(raw) as Partial<FilterSettings>;
    // Merge with defaults so new fields added later get their default values
    return { ...FILTER_DEFAULTS, ...parsed };
  } catch {
    return null;
  }
}

function writeCookie(settings: FilterSettings): void {
  const expires = new Date();
  expires.setDate(expires.getDate() + COOKIE_DAYS);
  document.cookie =
    `${COOKIE_NAME}=${encodeURIComponent(JSON.stringify(settings))}` +
    `; expires=${expires.toUTCString()}; path=/; SameSite=Lax`;
}

function deleteCookie(): void {
  document.cookie = `${COOKIE_NAME}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/`;
}

// ── Hook ───────────────────────────────────────────────────────────────────

export interface UseFilterSettingsReturn {
  settings: FilterSettings;
  saveEnabled: boolean;
  setSaveEnabled: (v: boolean) => void;
  set: <K extends keyof FilterSettings>(key: K, value: FilterSettings[K]) => void;
}

export function useFilterSettings(): UseFilterSettingsReturn {
  // Initialise from cookie if one exists
  const [saveEnabled, setSaveEnabledState] = useState<boolean>(() => {
    return readCookie() !== null;
  });

  const [settings, setSettings] = useState<FilterSettings>(() => {
    return readCookie() ?? { ...FILTER_DEFAULTS };
  });

  // Persist whenever settings change AND saveEnabled is true
  useEffect(() => {
    if (saveEnabled) {
      writeCookie(settings);
    }
  }, [settings, saveEnabled]);

  // When saveEnabled is toggled
  const setSaveEnabled = useCallback((v: boolean) => {
    setSaveEnabledState(v);
    if (!v) {
      deleteCookie();
    } else {
      // Write immediately with current settings
      writeCookie(settings);
    }
  }, [settings]);

  const set = useCallback(<K extends keyof FilterSettings>(
    key: K,
    value: FilterSettings[K],
  ) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  }, []);

  return { settings, saveEnabled, setSaveEnabled, set };
}
