import { useSearchParams } from "react-router-dom";

export interface SelectedSystem {
  id: number;
  name: string;
}

export interface SelectionState {
  factionName: string | null;
  centerSystem: SelectedSystem | null;
  setFaction: (name: string | null) => void;
  setCenter: (system: SelectedSystem | null) => void;
}

export function useSelectionState(): SelectionState {
  const [params, setParams] = useSearchParams();

  const factionName = params.get("faction");
  const centerId = params.get("center_id");
  const centerName = params.get("center_name");
  const centerSystem: SelectedSystem | null =
    centerId && centerName
      ? { id: Number(centerId), name: centerName }
      : null;

  function setFaction(name: string | null) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (name) next.set("faction", name);
      else next.delete("faction");
      return next;
    });
  }

  function setCenter(system: SelectedSystem | null) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (system) {
        next.set("center_id", String(system.id));
        next.set("center_name", system.name);
      } else {
        next.delete("center_id");
        next.delete("center_name");
      }
      return next;
    });
  }

  return { factionName, centerSystem, setFaction, setCenter };
}
