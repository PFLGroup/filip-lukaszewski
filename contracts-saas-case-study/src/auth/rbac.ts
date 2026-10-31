/**
 * RBAC + zakres danych (tenant / dział / własność) — dwie warstwy w jednym miejscu.
 *
 * Sama rola nie wystarcza. Typowa luka IDOR wygląda tak: użytkownik ma prawo
 * `contract:read`, więc endpoint `/contracts/:id` zwraca KAŻDĄ umowę, której ID
 * poda. Dlatego każda decyzja sprawdza:
 *   1. czy rola ma uprawnienie,
 *   2. czy zasób należy do firmy (tenanta) użytkownika   -> COMPANY_FORBIDDEN,
 *   3. dla Managera — czy zasób jest z jego działu         -> DEPARTMENT_FORBIDDEN,
 *   4. dla Employee — czy to jego własny zasób            -> OWNERSHIP_FORBIDDEN.
 *
 * Plus bezpiecznik „fail-closed”: przełącznik deweloperski wyłączający auth jest
 * ignorowany w środowisku produkcyjnym, niezależnie od konfiguracji.
 */

export const ROLES = ["Admin", "HR", "Manager", "Employee", "Accountant", "Viewer"] as const;
export type Role = (typeof ROLES)[number];

export type Permission =
  | "contract:read"
  | "contract:write"
  | "contract:pdf"
  | "annex:write"
  | "employee:read"
  | "employee:write"
  | "pii:read"
  | "file:download"
  | "setup:manage"
  | "audit:read";

const MATRIX: Record<Role, readonly Permission[]> = {
  Admin: [
    "contract:read", "contract:write", "contract:pdf", "annex:write", "employee:read",
    "employee:write", "pii:read", "file:download", "setup:manage", "audit:read",
  ],
  HR: [
    "contract:read", "contract:write", "contract:pdf", "annex:write", "employee:read",
    "employee:write", "pii:read", "file:download",
  ],
  Manager: ["contract:read", "contract:pdf", "employee:read", "file:download"],
  Accountant: ["contract:read", "contract:pdf", "employee:read", "pii:read"],
  Employee: ["contract:read", "contract:pdf", "file:download"],
  Viewer: ["contract:read"],
};

export function can(role: Role, permission: Permission): boolean {
  return MATRIX[role]?.includes(permission) ?? false;
}

export interface Principal {
  userId: string;
  role: Role;
  companyIds: readonly string[];
  departmentId?: string;
  employeeId?: string;
}

export interface ScopedResource {
  companyId: string;
  departmentId?: string;
  ownerEmployeeId?: string;
}

export type DenyReason =
  | "UNAUTHENTICATED"
  | "ROLE_FORBIDDEN"
  | "COMPANY_FORBIDDEN"
  | "DEPARTMENT_FORBIDDEN"
  | "OWNERSHIP_FORBIDDEN";

export type AccessDecision = { allowed: true } | { allowed: false; reason: DenyReason };

export function decide(
  principal: Principal | null | undefined,
  permission: Permission,
  resource?: ScopedResource,
): AccessDecision {
  if (!principal) return { allowed: false, reason: "UNAUTHENTICATED" };
  if (!can(principal.role, permission)) return { allowed: false, reason: "ROLE_FORBIDDEN" };
  if (!resource) return { allowed: true };
  if (!principal.companyIds.includes(resource.companyId)) return { allowed: false, reason: "COMPANY_FORBIDDEN" };
  if (principal.role === "Manager" && resource.departmentId !== principal.departmentId) {
    return { allowed: false, reason: "DEPARTMENT_FORBIDDEN" };
  }
  if (principal.role === "Employee" && resource.ownerEmployeeId !== principal.employeeId) {
    return { allowed: false, reason: "OWNERSHIP_FORBIDDEN" };
  }
  return { allowed: true };
}

export class AccessError extends Error {
  readonly statusCode: 401 | 403;
  constructor(readonly reason: DenyReason) {
    super(reason);
    this.name = "AccessError";
    this.statusCode = reason === "UNAUTHENTICATED" ? 401 : 403;
  }
}

export function assertAccess(principal: Principal | null | undefined, permission: Permission, resource?: ScopedResource): void {
  const decision = decide(principal, permission, resource);
  if (!decision.allowed) throw new AccessError(decision.reason);
}

/**
 * Guard niezależny od frameworka (do użycia np. jako preHandler w Fastify).
 * Zasób jest ładowany PRZED decyzją, a decyzja zapada na jego rzeczywistych atrybutach
 * (firma/dział/właściciel z bazy), nigdy na parametrach przysłanych przez klienta.
 */
export function guard<Ctx extends { principal?: Principal | null }>(
  permission: Permission,
  loadResource?: (ctx: Ctx) => Promise<ScopedResource | null>,
) {
  return async (ctx: Ctx): Promise<void> => {
    if (!ctx.principal) throw new AccessError("UNAUTHENTICATED");
    if (!loadResource) return assertAccess(ctx.principal, permission);
    const resource = await loadResource(ctx);
    // Brak zasobu: najpierw sprawdzamy rolę, potem i tak 403 zamiast 404 —
    // nie zdradzamy, czy zasób o danym ID istnieje w innej firmie.
    if (!resource) {
      assertAccess(ctx.principal, permission);
      throw new AccessError("COMPANY_FORBIDDEN");
    }
    assertAccess(ctx.principal, permission, resource);
  };
}

/** Przełącznik „bez logowania” dla lokalnego developmentu — w produkcji zawsze wyłączony (fail-closed). */
export function isAuthBypassAllowed(env: Record<string, string | undefined>): boolean {
  const appEnv = (env.APP_ENV ?? env.NODE_ENV ?? "production").toLowerCase();
  if (appEnv.startsWith("prod")) return false;
  return env.DEV_NO_AUTH === "1";
}
