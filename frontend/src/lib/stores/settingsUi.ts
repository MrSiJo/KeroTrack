// frontend/src/lib/stores/settingsUi.ts
import { writable } from "svelte/store";

const KEY = "kerotrack.settings.activeGroup";

function loadInitial(): string {
  if (typeof localStorage === "undefined") return "tank";
  return localStorage.getItem(KEY) ?? "tank";
}

export const activeGroup = writable<string>(loadInitial());

activeGroup.subscribe((v) => {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(KEY, v);
  }
});

export const search = writable<string>("");
