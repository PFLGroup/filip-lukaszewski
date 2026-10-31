import { randomBytes } from "node:crypto";
import { describe, expect, it } from "vitest";
import {
  DecryptionError,
  createKeyring,
  decryptField,
  decryptFields,
  encryptField,
  encryptFields,
  isEncrypted,
  needsRotation,
  parseKey,
  reencrypt,
} from "./fieldEncryption.js";

// Klucze generowane w locie — w repozytorium nie ma żadnego klucza.
const k1 = randomBytes(32).toString("hex");
const k2 = randomBytes(32).toString("hex");
const ring = createKeyring({ "2026-01": k1 }, "2026-01");

describe("encryptField / decryptField", () => {
  it("roundtrip z polskimi znakami", () => {
    const token = encryptField("ul. Żółkiewskiego 5/12, Łódź", ring);
    expect(isEncrypted(token)).toBe(true);
    expect(token.startsWith("v1.2026-01.")).toBe(true);
    expect(decryptField(token, ring)).toBe("ul. Żółkiewskiego 5/12, Łódź");
  });

  it("losowy IV — ta sama wartość daje różne szyfrogramy", () => {
    expect(encryptField("wartosc-testowa", ring)).not.toBe(encryptField("wartosc-testowa", ring));
  });

  it("wykrywa modyfikację szyfrogramu", () => {
    const parts = encryptField("PL00 0000 0000", ring).split(".");
    const ct = Buffer.from(parts[4]!, "base64url");
    ct[0] = ct[0]! ^ 0xff;
    parts[4] = ct.toString("base64url");
    expect(() => decryptField(parts.join("."), ring)).toThrow(DecryptionError);
  });

  it("AAD wiąże wartość z rekordem — przeniesienie do innego rekordu się nie uda", () => {
    const token = encryptField("12345", ring, "employee:1:salary");
    expect(decryptField(token, ring, "employee:1:salary")).toBe("12345");
    expect(() => decryptField(token, ring, "employee:2:salary")).toThrow(DecryptionError);
  });

  it("zły klucz i nieznany format", () => {
    const other = createKeyring({ "2026-01": k2 }, "2026-01");
    const token = encryptField("tajne", ring);
    expect(() => decryptField(token, other)).toThrow(DecryptionError);
    expect(() => decryptField("plaintext", ring)).toThrow("nieznany format");
    expect(() => decryptField("v1.brak.a.b.c", ring)).toThrow('brak klucza "brak"');
  });

  it("komunikat błędu nie zawiera treści", () => {
    const token = encryptField("sekretna-wartosc", ring, "a");
    try {
      decryptField(token, ring, "b");
    } catch (e) {
      expect(String(e)).not.toContain("sekretna");
    }
  });
});

describe("keyring i rotacja", () => {
  it("waliduje klucze", () => {
    expect(() => parseKey("abc")).toThrow();
    expect(() => createKeyring({ "2026-01": k1 }, "2026-02")).toThrow("brak bieżącego klucza");
    expect(() => createKeyring({ "Zły KID": k1 }, "Zły KID")).toThrow("niepoprawny identyfikator");
  });

  it("stare wartości czytelne po rotacji i przeszyfrowywane nowym kluczem", () => {
    const old = encryptField("dane", ring, "x");
    const rotated = createKeyring({ "2026-01": k1, "2026-07": k2 }, "2026-07");
    expect(decryptField(old, rotated, "x")).toBe("dane");
    expect(needsRotation(old, rotated)).toBe(true);
    const fresh = reencrypt(old, rotated, "x");
    expect(fresh.split(".")[1]).toBe("2026-07");
    expect(needsRotation(fresh, rotated)).toBe(false);
    expect(decryptField(fresh, rotated, "x")).toBe("dane");
  });
});

describe("encryptFields / decryptFields", () => {
  it("szyfruje tylko wskazane, niepuste pola", () => {
    const record = { id: "7", name: "Jan", taxId: "TAX-ID-DEMO", iban: null as string | null };
    const ctx = { entity: "employee", id: "7" };
    const enc = encryptFields(record, ["taxId", "iban"], ring, ctx);
    expect(enc.name).toBe("Jan");
    expect(enc.iban).toBeNull();
    expect(isEncrypted(enc.taxId)).toBe(true);
    expect(decryptFields(enc, ["taxId", "iban"], ring, ctx)).toEqual(record);
    expect(() => decryptFields(enc, ["taxId"], ring, { entity: "employee", id: "8" })).toThrow(DecryptionError);
  });
});
