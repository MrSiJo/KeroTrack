import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "$lib/api";
import { formatSaveErrors, settings } from "$lib/stores/settings";

describe("settings.save", () => {
  beforeEach(() => {
    vi.spyOn(api, "settingsSchema").mockResolvedValue({
      catalogue: [
        { key: "notifications.apprise_urls", label: "Apprise URLs" },
        { key: "notifications.gotify_token", label: "Gotify token" },
      ],
    } as never);
    vi.spyOn(api, "settings").mockResolvedValue({
      items: [],
      groups: {},
    } as never);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reports ok when every key saved", async () => {
    vi.spyOn(api, "bulkSetSettings").mockResolvedValue({
      saved: ["notifications.apprise_urls"],
    });
    const result = await settings.save({ "notifications.apprise_urls": ["x"] });
    expect(result.ok).toBe(true);
    expect(result.saved).toEqual(["notifications.apprise_urls"]);
    expect(result.errors).toEqual([]);
  });

  it("treats a non-empty errors list as a failure, keeping saved keys", async () => {
    vi.spyOn(api, "bulkSetSettings").mockResolvedValue({
      saved: ["notifications.gotify_token"],
      errors: [
        { key: "notifications.apprise_urls", message: "targets internal address" },
      ],
    });
    const result = await settings.save({
      "notifications.gotify_token": "t",
      "notifications.apprise_urls": ["x"],
    });
    expect(result.ok).toBe(false);
    expect(result.saved).toEqual(["notifications.gotify_token"]);
    expect(result.errors).toEqual([
      {
        key: "notifications.apprise_urls",
        label: "Apprise URLs",
        message: "targets internal address",
      },
    ]);
  });

  it("formats a message naming each failed setting by label", () => {
    const text = formatSaveErrors([
      { key: "a", label: "Apprise URLs", message: "bad host" },
      { key: "b", label: "Port", message: "too big" },
    ]);
    expect(text).toBe("Not saved: Apprise URLs (bad host); Port (too big)");
  });
});
