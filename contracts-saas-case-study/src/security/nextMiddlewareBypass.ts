/**
 * CVE-2025-29927 — obejście middleware w Next.js przez nagłówek `x-middleware-subrequest`.
 *
 * Next.js używał tego wewnętrznego nagłówka, żeby nie uruchamiać middleware
 * rekurencyjnie. W wersjach podatnych klient mógł wysłać go sam — wtedy middleware
 * (a w nim np. przekierowanie niezalogowanych na /login) był pomijany.
 *
 * Wersje z poprawką: 12.3.5, 13.5.9, 14.2.25, 15.2.3.
 *
 * Obrona w głąb zastosowana w projekcie:
 *   1. reverse proxy usuwa nagłówek z KAŻDEGO żądania przychodzącego (patrz examples/Caddyfile),
 *   2. autoryzacja nie opiera się wyłącznie na middleware — API sprawdza sesję i uprawnienia
 *      przy każdym żądaniu (patrz src/auth/rbac.ts),
 *   3. aktualizacja Next.js do wersji z poprawką.
 *
 * Ten moduł zawiera: filtr nagłówków (dla własnego proxy/edge w Node) i sprawdzenie wersji
 * (np. jako krok CI, który blokuje build na podatnej wersji).
 */

export const UNTRUSTED_INTERNAL_HEADERS = ["x-middleware-subrequest"] as const;

/** Zwraca kopię nagłówków bez nagłówków wewnętrznych frameworka (porównanie bez wielkości liter). */
export function stripUntrustedHeaders(
  headers: Record<string, string | string[] | undefined>,
  blocked: readonly string[] = UNTRUSTED_INTERNAL_HEADERS,
): Record<string, string | string[] | undefined> {
  const deny = new Set(blocked.map((h) => h.toLowerCase()));
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !deny.has(name.toLowerCase())));
}

type Version = [number, number, number];

function parseVersion(version: string): Version {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(version.trim());
  if (!match) throw new Error(`nie rozpoznano wersji: ${version}`);
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function compare(a: Version, b: Version): number {
  for (let i = 0; i < 3; i++) {
    if (a[i]! !== b[i]!) return a[i]! - b[i]!;
  }
  return 0;
}

/** Zakresy podatne wg advisory: [od, do) — `do` to pierwsza wersja z poprawką. */
const VULNERABLE_RANGES: ReadonlyArray<[Version, Version]> = [
  [[11, 1, 4], [12, 3, 5]],
  [[13, 0, 0], [13, 5, 9]],
  [[14, 0, 0], [14, 2, 25]],
  [[15, 0, 0], [15, 2, 3]],
];

/**
 * Czy wersja Next.js jest podatna na CVE-2025-29927.
 * Wersje przedpremierowe (np. 15.2.3-canary.1) traktujemy zachowawczo jak wersję bazową
 * POPRZEDZAJĄCĄ wydanie, czyli jako podatne, jeśli bazowa jest pierwszą wersją z poprawką.
 */
export function isVulnerableToCve202529927(version: string): boolean {
  const v = parseVersion(version);
  const isPrerelease = /^v?\d+\.\d+\.\d+-/.test(version.trim());
  return VULNERABLE_RANGES.some(([from, to]) => {
    const belowFix = compare(v, to) < 0 || (isPrerelease && compare(v, to) === 0);
    return compare(v, from) >= 0 && belowFix;
  });
}
