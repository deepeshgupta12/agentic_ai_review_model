import { describe, expect, it } from "vitest";

import { errorMessage, readCookie, safeNextPath } from "./paths";

describe("safeNextPath", () => {
  it("keeps console paths", () => {
    expect(safeNextPath("/console/operations")).toBe("/console/operations");
  });

  it.each(["https://evil.example", "//evil.example", "/\\evil.example", "/projects/x", "", null, undefined])(
    "refuses %s and falls back to the console",
    (value) => {
      expect(safeNextPath(value)).toBe("/console");
    },
  );

  it("never sends a signed-in user back to the login page", () => {
    expect(safeNextPath("/console/login?next=/console")).toBe("/console");
  });
});

describe("readCookie", () => {
  it("reads one cookie among several", () => {
    expect(readCookie("a=1; sy_csrf=abc%3D; b=2", "sy_csrf")).toBe("abc=");
  });

  it("returns null when missing", () => {
    expect(readCookie("a=1", "sy_csrf")).toBeNull();
  });
});

describe("errorMessage", () => {
  it("uses the contract envelope message", () => {
    expect(errorMessage({ error: { message: "Email or password is incorrect" } }, "fallback")).toBe(
      "Email or password is incorrect",
    );
  });

  it("falls back for anything else", () => {
    expect(errorMessage("oops", "fallback")).toBe("fallback");
    expect(errorMessage({ error: {} }, "fallback")).toBe("fallback");
  });
});
