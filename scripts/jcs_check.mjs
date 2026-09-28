#!/usr/bin/env node
// Cross-language check (D23, D24): an independent JavaScript implementation of the
// canonical hash and the text-anchor offsets must agree with the Python-generated
// fixtures. No npm packages; Node's built-in crypto only.
//
//   node scripts/jcs_check.mjs          # exit 0 when everything matches
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const fixtures = join(dirname(fileURLToPath(import.meta.url)), "..", "contracts", "v1", "fixtures");
const load = (name) => JSON.parse(readFileSync(join(fixtures, name), "utf8"));

class CanonicalError extends Error {}

// RFC 8785: ECMAScript number and string serialisation, keys sorted by UTF-16 code units.
// Same preconditions as the Python side: integers in the safe range only, NFC text only.
function canonicalize(value) {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new CanonicalError(`not a safe integer: ${value}`);
    return JSON.stringify(value);
  }
  if (typeof value === "string") {
    if (value.normalize("NFC") !== value) throw new CanonicalError("text not in NFC");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((key) => {
      if (key.normalize("NFC") !== key) throw new CanonicalError("key not in NFC");
      return `${JSON.stringify(key)}:${canonicalize(value[key])}`;
    })
    .join(",")}}`;
}

const sha = (text) => `sha256:${createHash("sha256").update(Buffer.from(text, "utf8")).digest("hex")}`;
const problems = [];
let checked = 0;

const hashing = load("hashing.json");
for (const c of hashing.cases) {
  checked += 1;
  let canonical;
  try {
    canonical = canonicalize(c.value);
  } catch (err) {
    problems.push(`hashing ${c.name}: rejected unexpectedly (${err.message})`);
    continue;
  }
  if (canonical !== c.canonical) problems.push(`hashing ${c.name}: canonical form differs from Python`);
  if (sha(canonical) !== c.sha256) problems.push(`hashing ${c.name}: sha256 differs from Python`);
}
for (const r of hashing.rejects) {
  checked += 1;
  try {
    canonicalize(r.value);
    problems.push(`hashing reject ${r.name}: accepted but must be rejected (${r.reason})`);
  } catch (err) {
    if (!(err instanceof CanonicalError)) throw err;
  }
}

for (const c of load("anchors.json").cases) {
  checked += 1;
  const points = Array.from(c.text); // code points
  if (points.slice(c.start, c.end).join("") !== c.excerpt) problems.push(`anchor ${c.name}: code-point slice differs`);
  if (c.text.slice(c.utf16_start, c.utf16_end) !== c.excerpt) problems.push(`anchor ${c.name}: UTF-16 slice differs`);
  if (points.slice(0, c.start).join("").length !== c.utf16_start) problems.push(`anchor ${c.name}: start conversion differs`);
  if (points.slice(0, c.end).join("").length !== c.utf16_end) problems.push(`anchor ${c.name}: end conversion differs`);
}

for (const c of load("content.json").cases) {
  if (c.expect !== "valid" || !c.schema.endsWith("/ContentRevision")) continue;
  checked += 1;
  const rev = c.instance;
  if (sha(canonicalize(rev.payload)) !== rev.payload_sha256) problems.push(`content ${c.name}: payload hash differs`);
  if (sha(canonicalize(rev.manifest)) !== rev.manifest_sha256) problems.push(`content ${c.name}: manifest hash differs`);
}

console.log(JSON.stringify({ node: process.version, checked, problems }, null, 2));
process.exit(problems.length ? 1 : 0);
