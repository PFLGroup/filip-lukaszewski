import { describe, expect, it } from "vitest";
import { isVulnerableToCve202529927, stripUntrustedHeaders } from "./nextMiddlewareBypass.js";

describe("stripUntrustedHeaders", () => {
  it("usuwa nagłówek niezależnie od wielkości liter, resztę zostawia", () => {
    const out = stripUntrustedHeaders({
      "X-Middleware-Subrequest": "middleware:middleware:middleware:middleware:middleware",
      cookie: "session=abc",
      host: "app.example.com",
    });
    expect(out).toEqual({ cookie: "session=abc", host: "app.example.com" });
  });
});

describe("isVulnerableToCve202529927", () => {
  it.each([
    ["11.1.4", true],
    ["12.3.4", true],
    ["12.3.5", false],
    ["13.5.8", true],
    ["13.5.9", false],
    ["14.2.24", true],
    ["14.2.25", false],
    ["15.0.3", true],
    ["15.2.2", true],
    ["15.2.3", false],
    ["15.2.3-canary.1", true],
    ["15.5.0", false],
    ["11.1.3", false],
    ["v14.1.0", true],
  ])("%s => %s", (version, expected) => {
    expect(isVulnerableToCve202529927(version)).toBe(expected);
  });

  it("odrzuca nierozpoznany zapis", () => {
    expect(() => isVulnerableToCve202529927("latest")).toThrow();
  });
});
