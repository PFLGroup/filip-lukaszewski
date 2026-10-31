/**
 * Szyfrowanie pojedynczych pól z danymi osobowymi (PII) — AES-256-GCM.
 *
 * Format tokenu zapisywanego w kolumnie bazy (tekst):
 *
 *   v1.<kid>.<iv>.<tag>.<ciphertext>      (części binarne w base64url)
 *
 * - `kid` (key id) pozwala rotować klucze: nowe zapisy idą bieżącym kluczem,
 *   stare dalej da się odczytać, a `needsRotation()` wskazuje rekordy do przeszyfrowania.
 * - losowy 96-bitowy IV dla każdego zapisu (nigdy nie używamy IV ponownie z tym samym kluczem),
 * - tag GCM wykrywa każdą modyfikację szyfrogramu,
 * - AAD (additional authenticated data) wiąże szyfrogram z rekordem i polem,
 *   np. `employee:42:pesel` — skopiowanie zaszyfrowanej wartości do innego rekordu
 *   lub innej kolumny kończy się błędem odszyfrowania.
 *
 * Klucz główny pochodzi z sekretu środowiska / sejfu — nigdy z repozytorium.
 */
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

const VERSION = "v1";
const ALGORITHM = "aes-256-gcm";
const IV_BYTES = 12;
const TAG_BYTES = 16;
const KID_RE = /^[a-z0-9-]{1,32}$/;

export interface Keyring {
  readonly current: string;
  readonly keys: ReadonlyMap<string, Buffer>;
}

export class DecryptionError extends Error {
  constructor(message = "nie udało się odszyfrować wartości") {
    super(message);
    this.name = "DecryptionError";
  }
}

export function parseKey(hex: string): Buffer {
  if (!/^[0-9a-fA-F]{64}$/.test(hex)) {
    throw new Error("klucz musi mieć 32 bajty zapisane jako 64 znaki hex");
  }
  return Buffer.from(hex, "hex");
}

export function createKeyring(keysHex: Record<string, string>, current: string): Keyring {
  const keys = new Map<string, Buffer>();
  for (const [kid, hex] of Object.entries(keysHex)) {
    if (!KID_RE.test(kid)) throw new Error(`niepoprawny identyfikator klucza: ${kid}`);
    keys.set(kid, parseKey(hex));
  }
  if (!keys.has(current)) throw new Error(`brak bieżącego klucza "${current}" w keyringu`);
  return { current, keys };
}

const b64 = (buf: Buffer): string => buf.toString("base64url");
const unb64 = (s: string): Buffer => Buffer.from(s, "base64url");

export function encryptField(plaintext: string, keyring: Keyring, aad = ""): string {
  const key = keyring.keys.get(keyring.current)!;
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGORITHM, key, iv, { authTagLength: TAG_BYTES });
  cipher.setAAD(Buffer.from(aad, "utf8"));
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  return [VERSION, keyring.current, b64(iv), b64(cipher.getAuthTag()), b64(ciphertext)].join(".");
}

export function isEncrypted(value: unknown): value is string {
  return typeof value === "string" && value.startsWith(`${VERSION}.`) && value.split(".").length === 5;
}

export function decryptField(token: string, keyring: Keyring, aad = ""): string {
  const parts = token.split(".");
  if (parts.length !== 5 || parts[0] !== VERSION) throw new DecryptionError("nieznany format tokenu");
  const [, kid, ivB64, tagB64, ctB64] = parts as [string, string, string, string, string];
  const key = keyring.keys.get(kid);
  if (!key) throw new DecryptionError(`brak klucza "${kid}"`);
  const iv = unb64(ivB64);
  const tag = unb64(tagB64);
  if (iv.length !== IV_BYTES || tag.length !== TAG_BYTES) throw new DecryptionError("uszkodzony token");
  try {
    const decipher = createDecipheriv(ALGORITHM, key, iv, { authTagLength: TAG_BYTES });
    decipher.setAAD(Buffer.from(aad, "utf8"));
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(unb64(ctB64)), decipher.final()]).toString("utf8");
  } catch {
    // Celowo bez szczegółów: komunikat błędu nie może ujawniać nic o treści.
    throw new DecryptionError();
  }
}

/** Czy wartość zaszyfrowano kluczem innym niż bieżący (kandydat do przeszyfrowania). */
export function needsRotation(token: string, keyring: Keyring): boolean {
  return isEncrypted(token) && token.split(".")[1] !== keyring.current;
}

/** Przeszyfrowanie bieżącym kluczem (zadanie w tle po rotacji). */
export function reencrypt(token: string, keyring: Keyring, aad = ""): string {
  return needsRotation(token, keyring) ? encryptField(decryptField(token, keyring, aad), keyring, aad) : token;
}

/**
 * Szyfruje wskazane pola obiektu, wiążąc każde z rekordem przez AAD `${entity}:${id}:${field}`.
 * Pola puste (null/undefined) zostają bez zmian.
 */
export function encryptFields<T extends Record<string, unknown>>(
  record: T,
  fields: readonly (keyof T & string)[],
  keyring: Keyring,
  context: { entity: string; id: string },
): T {
  const out: Record<string, unknown> = { ...record };
  for (const field of fields) {
    const value = record[field];
    if (value === null || value === undefined) continue;
    out[field] = encryptField(String(value), keyring, `${context.entity}:${context.id}:${field}`);
  }
  return out as T;
}

export function decryptFields<T extends Record<string, unknown>>(
  record: T,
  fields: readonly (keyof T & string)[],
  keyring: Keyring,
  context: { entity: string; id: string },
): T {
  const out: Record<string, unknown> = { ...record };
  for (const field of fields) {
    const value = record[field];
    if (!isEncrypted(value)) continue;
    out[field] = decryptField(value, keyring, `${context.entity}:${context.id}:${field}`);
  }
  return out as T;
}
