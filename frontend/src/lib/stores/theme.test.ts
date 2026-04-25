import { afterEach, describe, expect, it } from "vitest";
import { get } from "svelte/store";

import { theme } from "$lib/stores/theme";

describe("theme store", () => {
  afterEach(() => {
    document.documentElement.classList.remove("light", "dark");
  });

  it("toggles between dark and light", () => {
    theme.set("dark");
    theme.toggle();
    expect(get(theme)).toBe("light");
    theme.toggle();
    expect(get(theme)).toBe("dark");
  });

  it("applies the .dark class to <html>", () => {
    theme.set("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("applies the .light class on switch", () => {
    theme.set("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
