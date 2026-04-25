import { writable } from "svelte/store";

const KEY = "kerotrack-theme";

type Theme = "dark" | "light";

function detectInitial(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    const stored = window.localStorage?.getItem?.(KEY);
    if (stored === "dark" || stored === "light") return stored;
  } catch {
    /* storage unavailable */
  }
  return "dark";
}

function createTheme() {
  const { subscribe, set } = writable<Theme>(detectInitial());

  function apply(theme: Theme) {
    if (typeof document === "undefined") return;
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
  }

  function toggle() {
    update((t) => (t === "dark" ? "light" : "dark"));
  }

  function update(fn: (t: Theme) => Theme) {
    let next: Theme = "dark";
    subscribe((t) => {
      next = fn(t);
    })();
    setTheme(next);
  }

  function setTheme(theme: Theme) {
    set(theme);
    apply(theme);
    if (typeof window !== "undefined") {
      try {
        window.localStorage?.setItem?.(KEY, theme);
      } catch {
        /* ignore */
      }
    }
  }

  if (typeof window !== "undefined") {
    apply(detectInitial());
  }

  return { subscribe, set: setTheme, toggle };
}

export const theme = createTheme();
