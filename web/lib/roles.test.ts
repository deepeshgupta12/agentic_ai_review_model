import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { can, OPERATION_ROLES } from "./roles";

type Route = { operation_id: string; access: string; roles: string[] };

const contract = JSON.parse(readFileSync(join(__dirname, "..", "..", "contracts", "v1", "routes.json"), "utf8")) as {
  all_roles: string[];
  routes: Route[];
};

describe("console role map", () => {
  it("equals the route contract for every session operation", () => {
    const expected: Record<string, string[]> = {};
    for (const route of contract.routes) {
      if (route.access !== "session") continue;
      expected[route.operation_id] = route.roles.includes("all") ? contract.all_roles : route.roles;
    }
    expect(Object.fromEntries(Object.entries(OPERATION_ROLES).map(([k, v]) => [k, [...v]]))).toEqual(expected);
  });

  it("answers per role", () => {
    expect(can(["analyst"], "decideFinding")).toBe(false);
    expect(can(["moderator", "analyst"], "decideFinding")).toBe(true);
    expect(can(["moderator"], "publish")).toBe(false);
    expect(can(undefined, "listProjects")).toBe(false);
  });
});
