import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/client";
import { clearApiCache } from "@/lib/api/cache";
import { fakeFetchResponse, resetCoordinationFixtures } from "@/test/fixtures";
import { invalidateCoordination, useCoordinationVersion, useMutation, useTaskSummary } from "./use-coordination";

const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => fakeFetchResponse(String(input), init));
const summaryCalls = () => fetchMock.mock.calls.filter(([u]) => new URL(String(u)).pathname.endsWith("/follow-up-tasks/summary"));

beforeEach(() => {
  resetCoordinationFixtures();
  clearApiCache();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  fetchMock.mockClear();
  vi.unstubAllGlobals();
});

function useProbe() {
  const version = useCoordinationVersion();
  return { version, ...useMutation() };
}

describe("useMutation", () => {
  it("returns the result and invalidates coordination reads on success", async () => {
    const { result } = renderHook(() => useProbe());
    const before = result.current.version;
    let out: number | null = null;
    await act(async () => {
      out = await result.current.run(async () => 42);
    });
    expect(out).toBe(42);
    expect(result.current.version).toBe(before + 1);
    expect(result.current.error).toBeNull();
    expect(result.current.pending).toBe(false);
  });

  it("keeps the backend's own reason on failure and does not invalidate", async () => {
    const { result } = renderHook(() => useProbe());
    const before = result.current.version;
    let out: unknown = "unset";
    await act(async () => {
      out = await result.current.run(() =>
        Promise.reject(new ApiError("The API responded 422 for /x.", 422, "/x", "contact_not_permitted", "Contact consent was withdrawn."))
      );
    });
    expect(out).toBeNull();
    expect(result.current.error).toBe("Contact consent was withdrawn.");
    expect(result.current.version).toBe(before);
    act(() => result.current.reset());
    expect(result.current.error).toBeNull();
  });

  it("explains a 403 as a role limit, not with the server text", async () => {
    const { result } = renderHook(() => useProbe());
    await act(async () => {
      await result.current.run(() => Promise.reject(new ApiError("Your role does not have access to /x (403).", 403, "/x", "forbidden", "Forbidden.")));
    });
    expect(result.current.error).toBe("Your role does not have access to /x (403).");
  });
});

describe("coordination cache invalidation", () => {
  it("refetches every mounted coordination read after a write or a cache reset", async () => {
    const { result } = renderHook(() => useTaskSummary({}, 0));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    expect(summaryCalls()).toHaveLength(1);

    act(() => invalidateCoordination());
    // The last data stays on screen while the same read refetches (forms and rows survive a write).
    expect(result.current.status).toBe("ready");
    await waitFor(() => expect(summaryCalls()).toHaveLength(2));

    act(() => clearApiCache());
    await waitFor(() => expect(summaryCalls()).toHaveLength(3));
  });
});
