import { useSearchParams } from "react-router-dom";

export interface SelectedSystem {
  id: number;
  name: string;
}

export interface SelectionState {
  powerName: string | null;
  refSystem: SelectedSystem | null;          // renamed from centerSystem
  systemList: string[];                      // user-supplied list of system names to focus on
  setPower: (name: string | null) => void;
  setRef: (system: SelectedSystem | null) => void;   // renamed from setCenter
  setSystemList: (names: string[]) => void;
}

export function useSelectionState(): SelectionState {
  const [params, setParams] = useSearchParams();

  const powerName = params.get("power");
  const refId     = params.get("ref_id");
  const refName   = params.get("ref_name");
  const refSystem: SelectedSystem | null =
    refId && refName ? { id: Number(refId), name: refName } : null;

  // System list stored as comma-separated names in URL (url-encoded)
  const listParam = params.get("systems");
  const systemList: string[] = listParam
    ? listParam.split(",").map(s => s.trim()).filter(Boolean)
    : [];

  function setPower(name: string | null) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (name) next.set("power", name);
      else next.delete("power");
      return next;
    });
  }

  function setRef(system: SelectedSystem | null) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (system) {
        next.set("ref_id",   String(system.id));
        next.set("ref_name", system.name);
      } else {
        next.delete("ref_id");
        next.delete("ref_name");
      }
      return next;
    });
  }

  function setSystemList(names: string[]) {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (names.length > 0) next.set("systems", names.join(","));
      else next.delete("systems");
      return next;
    });
  }

  return { powerName, refSystem, systemList, setPower, setRef, setSystemList };
}
