import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, onUnauthorised, setCsrfToken } from "$lib/api";

describe("typed api client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfToken(null);
  });

  it("attaches X-CSRF-Token to mutating verbs when set", async () => {
    setCsrfToken("token-123");
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      new Response(JSON.stringify({ key: "x", value: 1 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await api.setSetting("x", 1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "token-123",
    );
    expect(init.credentials).toBe("include");
  });

  it("does not attach CSRF on GET requests", async () => {
    setCsrfToken("token-123");
    const fetchMock = vi.fn(async (..._args: Parameters<typeof fetch>) =>
      new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await api.health();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("calls the unauthorised callback on 401", async () => {
    const cb = vi.fn();
    onUnauthorised(cb);
    vi.stubGlobal(
      "fetch",
      async () => new Response("", { status: 401 }),
    );
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(cb).toHaveBeenCalled();
  });

  it("surfaces 422 field-level errors", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({
            error: "invalid_int",
            message: "expected int",
            field: "mqtt.port",
          }),
          { status: 422 },
        ),
    );
    try {
      await api.setSetting("mqtt.port", "abc");
      expect.fail("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const e = err as ApiError;
      expect(e.status).toBe(422);
      expect(e.code).toBe("invalid_int");
      expect(e.field).toBe("mqtt.port");
    }
  });
});
