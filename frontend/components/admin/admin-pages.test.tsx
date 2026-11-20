import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AssignmentsAdmin, AuditAdmin, UsersAdmin } from "./admin-pages";

const MEMBERS = [
  { user_id: "U-ADMIN", email: "admin@x.invalid", full_name: "Ada Admin", preferred_language: "en", account_active: true, role: "SYSTEM_ADMIN", patient_access: "organization", membership_active: true, password_set: true },
  { user_id: "U-COORD", email: "coord@x.invalid", full_name: "Cora Coordinator", preferred_language: "en", account_active: true, role: "CARE_COORDINATOR", patient_access: "assigned", membership_active: true, password_set: true },
];
const calls: { method: string; path: string; body: unknown }[] = [];

function backend(method: string, path: string, body: unknown): unknown {
  calls.push({ method, path, body });
  if (path === "/admin/users" && method === "GET") return { total: MEMBERS.length, limit: 25, offset: 0, items: MEMBERS };
  if (path === "/admin/users" && method === "POST")
    return { member: { ...MEMBERS[1], user_id: "U-NEW", full_name: "New Person" }, activation: { purpose: "activation", token: "ACT-123", expires_at: "2099-01-01T00:00:00Z", delivery: "out_of_band" } };
  if (path.startsWith("/admin/users/") && method === "PATCH") return { ...MEMBERS[1], ...(body as object) };
  if (path === "/admin/assignments/staff" && method === "GET")
    return { items: [{ user_id: "U-COORD", full_name: "Cora Coordinator", role: "CARE_COORDINATOR" }] };
  if (path === "/admin/assignments" && method === "GET") return { total: 0, limit: 25, offset: 0, items: [] };
  if (path === "/admin/assignments" && method === "POST") return { assignment_id: "AS1", organization_id: "O", staff_user_id: "U-COORD", patient_id: "SYNTH-PAT-1", is_active: true, created_at: "2026-11-20T00:00:00Z", created_by: "U-ADMIN" };
  if (path === "/audit-events")
    return { total: 1, limit: 25, offset: 0, items: [{ event_id: "E1", occurred_at: "2026-11-20T10:00:00Z", request_id: null, actor_user_id: "U-COORD", actor_role: "CARE_COORDINATOR", organization_id: "O", permission: "users.read", action: "authz.denied", resource_type: "endpoint", resource_id: "GET /admin/users", patient_id: null, outcome: "denied", status_code: 403, details: {} }] };
  throw new Error(`unexpected ${method} ${path}`);
}

const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
  const u = new URL(url);
  const body = init?.body ? JSON.parse(String(init.body)) : undefined;
  return new Response(JSON.stringify(backend(init?.method ?? "GET", u.pathname.replace("/api/v1", ""), body)), { status: 200, headers: { "Content-Type": "application/json" } });
});

vi.mock("@/lib/auth/auth-context", () => ({
  useAuth: () => ({
    can: () => true,
    state: { status: "signed_in", me: { user: { user_id: "U-ADMIN" }, role: "SYSTEM_ADMIN", permissions: [] } },
  }),
}));

beforeEach(() => {
  calls.length = 0;
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(cleanup);

describe("Administration", () => {
  it("lists members, never offers to change your own role, and updates another member's role", async () => {
    render(<UsersAdmin />);
    const row = (await screen.findByText("Cora Coordinator")).closest("tr")!;
    expect(within(screen.getByText("Ada Admin").closest("tr")!).queryByRole("combobox")).toBeNull();
    fireEvent.change(within(row).getByRole("combobox", { name: /Role for Cora/ }), { target: { value: "CLINICIAN" } });
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH" && c.path === "/admin/users/U-COORD")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")!.body).toEqual({ role: "CLINICIAN" });
  });

  it("creates a staff account and shows the one-time activation code", async () => {
    render(<UsersAdmin />);
    fireEvent.click(await screen.findByRole("button", { name: /New staff account/ }));
    const form = screen.getByRole("form", { name: "New staff account" });
    const submit = within(form).getByRole("button", { name: "Create account" }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(form).getByLabelText("Full name"), { target: { value: "New Person" } });
    fireEvent.change(within(form).getByLabelText("Work e-mail"), { target: { value: "new@x.invalid" } });
    fireEvent.click(submit);
    expect(await screen.findByText("ACT-123")).toBeTruthy();
    expect(calls.find((c) => c.method === "POST")!.body).toEqual({ full_name: "New Person", email: "new@x.invalid", role: "CARE_COORDINATOR", patient_access: "assigned" });
  });

  it("assigns a patient to a staff member", async () => {
    render(<AssignmentsAdmin />);
    const form = screen.getByRole("form", { name: "New assignment" });
    await within(form).findByRole("option", { name: /Cora Coordinator/ });
    fireEvent.change(within(form).getByLabelText("Staff member"), { target: { value: "U-COORD" } });
    fireEvent.change(within(form).getByLabelText("Synthetic patient ID"), { target: { value: "SYNTH-PAT-1" } });
    fireEvent.click(within(form).getByRole("button", { name: /Assign/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ staff_user_id: "U-COORD", patient_id: "SYNTH-PAT-1" }));
    expect(calls.some((c) => c.path === "/admin/users")).toBe(false);
  });

  it("shows denied events and filters the audit log by outcome", async () => {
    render(<AuditAdmin />);
    expect(await screen.findByText("authz.denied")).toBeTruthy();
    expect(screen.getByText(/Denied · 403/)).toBeTruthy();
    fireEvent.change(screen.getByRole("combobox", { name: "Outcome" }), { target: { value: "denied" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).includes("outcome=denied"))).toBe(true));
  });
});
