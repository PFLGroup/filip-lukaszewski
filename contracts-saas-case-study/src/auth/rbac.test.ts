import { describe, expect, it } from "vitest";
import { AccessError, type Principal, type ScopedResource, can, decide, guard, isAuthBypassAllowed } from "./rbac.js";

const hr: Principal = { userId: "u1", role: "HR", companyIds: ["c1"] };
const manager: Principal = { userId: "u2", role: "Manager", companyIds: ["c1"], departmentId: "d1" };
const employee: Principal = { userId: "u3", role: "Employee", companyIds: ["c1"], employeeId: "e1" };
const viewer: Principal = { userId: "u4", role: "Viewer", companyIds: ["c1"] };

const contract: ScopedResource = { companyId: "c1", departmentId: "d1", ownerEmployeeId: "e1" };

describe("macierz uprawnień", () => {
  it("tylko Admin zarządza konfiguracją", () => {
    expect(can("Admin", "setup:manage")).toBe(true);
    expect(can("HR", "setup:manage")).toBe(false);
  });
  it("Viewer nie widzi danych osobowych ani nie pobiera plików", () => {
    expect(can("Viewer", "pii:read")).toBe(false);
    expect(can("Viewer", "file:download")).toBe(false);
  });
});

describe("decide — rola + zakres", () => {
  it("brak sesji => UNAUTHENTICATED", () => {
    expect(decide(null, "contract:read")).toEqual({ allowed: false, reason: "UNAUTHENTICATED" });
  });

  it("HR w swojej firmie — tak; w cudzej — COMPANY_FORBIDDEN (IDOR / cross-tenant)", () => {
    expect(decide(hr, "contract:write", contract).allowed).toBe(true);
    expect(decide(hr, "contract:write", { ...contract, companyId: "c2" })).toEqual({
      allowed: false,
      reason: "COMPANY_FORBIDDEN",
    });
  });

  it("Manager tylko w swoim dziale", () => {
    expect(decide(manager, "contract:read", contract).allowed).toBe(true);
    expect(decide(manager, "contract:read", { ...contract, departmentId: "d2" })).toEqual({
      allowed: false,
      reason: "DEPARTMENT_FORBIDDEN",
    });
  });

  it("Employee tylko własne dokumenty, nawet w tej samej firmie", () => {
    expect(decide(employee, "contract:pdf", contract).allowed).toBe(true);
    expect(decide(employee, "contract:pdf", { ...contract, ownerEmployeeId: "e2" })).toEqual({
      allowed: false,
      reason: "OWNERSHIP_FORBIDDEN",
    });
  });

  it("rola bez uprawnienia => ROLE_FORBIDDEN niezależnie od zasobu", () => {
    expect(decide(viewer, "contract:write", contract)).toEqual({ allowed: false, reason: "ROLE_FORBIDDEN" });
  });
});

describe("guard (np. preHandler)", () => {
  type Ctx = { principal?: Principal | null; params: { id: string } };
  const db: Record<string, ScopedResource> = { k1: contract, k2: { companyId: "c2" } };
  const load = async (ctx: Ctx) => db[ctx.params.id] ?? null;

  it("przepuszcza uprawniony dostęp", async () => {
    await expect(guard<Ctx>("contract:read", load)({ principal: hr, params: { id: "k1" } })).resolves.toBeUndefined();
  });

  it("401 bez sesji, 403 dla cudzej firmy", async () => {
    await expect(guard<Ctx>("contract:read", load)({ principal: null, params: { id: "k1" } })).rejects.toMatchObject({
      statusCode: 401,
    });
    await expect(guard<Ctx>("contract:read", load)({ principal: hr, params: { id: "k2" } })).rejects.toMatchObject({
      statusCode: 403,
      reason: "COMPANY_FORBIDDEN",
    });
  });

  it("nieistniejący zasób => 403, nie 404 (bez wycieku informacji o istnieniu ID)", async () => {
    const err = await guard<Ctx>("contract:read", load)({ principal: hr, params: { id: "nope" } }).catch((e) => e);
    expect(err).toBeInstanceOf(AccessError);
    expect(err.statusCode).toBe(403);
  });
});

describe("isAuthBypassAllowed — fail-closed", () => {
  it("w produkcji zawsze false", () => {
    expect(isAuthBypassAllowed({ APP_ENV: "production", DEV_NO_AUTH: "1" })).toBe(false);
    expect(isAuthBypassAllowed({ APP_ENV: "production-test", DEV_NO_AUTH: "1" })).toBe(false);
  });
  it("brak zmiennych środowiska traktujemy jak produkcję", () => {
    expect(isAuthBypassAllowed({ DEV_NO_AUTH: "1" })).toBe(false);
  });
  it("lokalnie tylko jawnie włączone", () => {
    expect(isAuthBypassAllowed({ APP_ENV: "development", DEV_NO_AUTH: "1" })).toBe(true);
    expect(isAuthBypassAllowed({ APP_ENV: "development" })).toBe(false);
  });
});
