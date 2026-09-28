# Screen specifications: console and public page

Step 02 design for the moderator console (`web/app/console/*`, built in Step 09) and the public project page (`web/app/projects/[slug]`, Step 11). It fixes each screen's route, roles, data, actions and states against the API in [contracts/v1/routes.json](../contracts/v1/routes.json). An operation is written as `op:` plus its operation ID, for example `op:listProjects`; `scripts/check_contracts.py` fails if a reference does not exist, or if a user-facing operation appears on no screen. Journeys and state machines: [10-journeys-and-states.md](10-journeys-and-states.md).

## Design direction (proposed, I15 / D25)

**Character.** The console is a calm, dense workbench for checking evidence: information first, few colours, nothing decorative. The public module is a quiet editorial block that reads like a well-sourced article section, clearly labelled as a the client summary of public discussion.

**Typography.** Inter for interface text; Noto Sans Devanagari for Hindi, loaded only on pages that need it; JetBrains Mono for IDs, hashes and timestamps. Console body 14/20 px, tables 13/18 px. Public module body 17/28 px with a 68-character measure.

**Colour tokens** (light theme required; dark theme optional later, same token names):

| Token | Value | Use |
|---|---|---|
| `--ink` / `--ink-muted` | `#0F172A` / `#475569` | Text |
| `--surface` / `--surface-sunken` / `--line` | `#FFFFFF` / `#F8FAFC` / `#E2E8F0` | Backgrounds, panels, rules |
| `--accent` | `#0F766E` | Primary actions and focus rings |
| `--ok` | `#15803D` | live, verified, approved |
| `--warn` | `#B45309` | access_pending, delivery_pending, stale, partial |
| `--danger` | `#B91C1C` | failed, rejected, withdrawn, blocking QA |
| `--idle` | `#64748B` | unavailable, superseded, not started |
| `--fixture` | `#A21CAF` | Fixture-mode banner only |

Advantages and considerations are **not** green and red: both use neutral ink with a text label and icon, so the page never looks like a rating. Every status shows text as well as colour (WCAG 2.2 AA contrast).

**Density and layout.** 8 px spacing grid; 36 px table rows; evidence shown side by side with the finding at 1280 px and wider, stacked below that. Components: shadcn/ui primitives on Tailwind, TanStack Table for lists, TipTap in a controlled mode for edits.

## Shared behaviour

- **States on every screen**: loading (skeleton), empty (says why and what to do), access_pending (names the connector and what unlocks it), partial (shows what is missing), error (safe message and request ID), stale (data older than the freshness threshold), forbidden (role missing; no hint of hidden records).
- **Conflicts**: a `409 version_conflict` opens a reload dialog that shows the current version and a diff of the user's pending change. Nothing is overwritten silently.
- **Roles**: buttons are hidden or disabled by role (from `op:getMe`), and the backend enforces every role again.
- **Fixture mode**: a `--fixture` banner on every console screen; fixture data can never publish.
- **Keyboard**: every action is reachable by keyboard. Review lists support next/previous; approve and reject always open a confirmation or reason dialog, never act on a single key.

## Console screens

### Login — `/console/login`

Any user. `op:login` starts the session; `op:getMe` loads roles; `op:logout` ends it. Wrong credentials and rate limiting show distinct messages. There is no self-registration.

### Portfolio — `/console`

All roles. Data: `op:listProjects`, `op:getOpsSummary`. One row per project: name, locality, latest run stage, coverage by connector, pending review counts (findings, links, alias proposals, corrections), approved vs active revision, delivery status, stale flag, 30-day spend. Researchers and admins see an import action (`op:importProjects`) that shows created vs updated projects.

### Project setup — `/console/projects/[projectId]/setup`

Read: all roles. Edit: researcher. Data: `op:getProject`, `op:listAliasProposals`. Actions: `op:updateProjectConfig` (languages, refresh, enabled sources, negative keywords, at the expected version).

- Shows the input fields as supplied (name, alternate names, locality, city, micromarket, developer, RERA registrations with registered names), the generated slug and the the client reference.
- **Approved aliases** with origin (input file, RERA name, approved proposal) and mode (standalone or context-required).
- **Alias proposals** (D17): each shows the alias, target (project or phase), the cited evidence excerpt with the strong identifier highlighted, independent-origin count and the collision result. Researchers and moderators approve (choosing standalone or context-required), reject or revoke with `op:decideAliasProposal`. A colliding or generic alias only offers context-required.

### Runs — `/console/projects/[projectId]/runs` and `/console/runs/[runId]`

Read: all roles. Start and cancel: researcher. Data: `op:listRuns`, `op:getRun`, `op:streamRunEvents` (falls back to polling `op:getRun`). Actions: `op:startRun` (window and connectors within entitlements), `op:cancelRun` (reason required).

The run page shows the stage timeline and a coverage table per connector: attempted queries, fetched, matched, analysed, metadata-only, last success and a note. `access_pending`, `partial` and `unavailable` are labelled, never shown as zero discussion. An `insufficient_evidence` result says so plainly and shows the coverage behind it.

### Evidence explorer — `/console/projects/[projectId]/evidence`

Read: all roles. Data: `op:listSources` (filters: platform, kind, aspect, language, date), `op:getSourceRevision`. Shows the original text with the exact excerpt highlighted (UTF-16 offsets from the API), the translation beside it when there is one, the source date (or "date unknown"), policy, origin cluster, conflicting evidence and eligibility with reasons.

Actions: moderators correct project matches with `op:decideSourceLink` (accept, reject, split into segments, remap), reason required except for accept. Moderators and admins withdraw a source with `op:withdrawSource`; the dialog lists the affected findings and content before confirming.

### Video library — `/console/projects/[projectId]/videos`

Read: all roles. Data: `op:listMedia`, `op:getSourceRevision`. One row per video or Short: channel, project match, format (video, Short or unknown, with its basis), access status (discovered, access_pending, metadata_only, transcribed, analysed, error) and analysed segments with timestamp links. A metadata-only video says it provides no spoken-content evidence.

### Findings review — `/console/projects/[projectId]/findings`

Read: all roles. Decide and edit: moderator. Data: `op:listFindings`, with evidence opened through `op:getSourceRevision`. Each finding shows kind (pro, con, neutral), aspect, wording, attribution (reported opinion or verified fact), exact claims, supporting and contradicting evidence side by side, independent-origin count (labelled as spread, not proof) and eligibility.

Actions: `op:decideFinding` (approve, reject with reason, request changes with reason) on the exact revision shown; `op:reviseFinding` edits as a new revision, and earlier decisions are then labelled superseded. Negative findings use the same controls as positive ones. Pros and cons may be unequal or empty.

### Content editor — `/console/projects/[projectId]/content`

Moderators edit and approve; publishers read. Data: `op:listContentRevisions`, `op:getContentRevision`. Actions: `op:createContentRevision` (generate from selected approved findings, or save an edit as a new revision), `op:decideContentRevision` (reject or request changes with a reason) and `op:approveContentRevision`.

- Left: the approved findings used. Right: block-by-block editor where every substantive block lists its finding and claim references; QA issues are pinned to their block, blocking ones first.
- **Preview** at `/console/projects/[projectId]/content/[revisionId]/preview` renders the real public template with this revision's payload, behind login and `noindex`.
- **Final approval dialog** shows the revision number, short payload hash, manifest hash, evidence epoch and state version, and sends exactly those values. A `409` says what changed (new revision, new evidence epoch or new state version) and nothing is approved.
- A user with both moderator and publisher roles may use an approve-and-publish button; it makes two separate calls (approve, then publish), each audited (docs/05).

### Publishing — `/console/projects/[projectId]/publishing`

Read: all roles. Act: publisher. Data: `op:getPublicationState`, `op:getPublication`. Shows approved, active and verified-delivered revisions separately; serving state; pending invalidation; recent operations with activation time and verified time.

Actions: `op:publish` (approved revision, its hash and the expected state version), `op:rollbackPublication` (only revisions that are still eligible are offered; a reason is required), `op:unpublishProject` (reason required). `delivery_pending` and delivery failure are shown as such, never as success.

### Corrections — `/console/corrections`

Moderator. Data: `op:listCorrections`. Action: `op:decideCorrection` (resolve or dismiss, with a reason). Each item links to the revision the reader saw and to the related findings so a correction can go through the normal edit and approval path.

### Operations — `/console/operations`

Researchers and admins see everything; other roles see the summary. Data: `op:getConnectorHealth` (status, last verified, quota, safe last error), `op:listJobs` (filter by status; failed and retry_wait first), `op:getOpsSummary` (freshness, delivery backlog, deletion backlog, model usage and cost by agent), `op:listEvaluations` (metrics with sample sizes). Credentials and raw source payloads are never shown.

### Administration — `/console/admin`

Admin (policies are also readable by researchers). Users: `op:listUsers`, `op:createUser`, `op:updateUser`. Source policies: `op:listSourcePolicies`, `op:createSourcePolicyVersion` (a new immutable version; narrowing rights starts dependency invalidation). Audit: `op:listAuditEvents`.

## Public project page — `/projects/[slug]`

Server-rendered. At render time it calls `op:getPublicInsights`, which returns only the active, eligible revision. The page never calls a model and never reads drafts.

**Module structure**, in order:

1. Heading (from the payload) with the evidence window and "Last reviewed" date.
2. Attribution line, for example "Compiled by the editorial team from public discussions and official records; reviewed by our editorial team." The module is never presented as user reviews and shows no star ratings or scores.
3. Overview.
4. Advantages and considerations, as separate lists that may be unequal or empty, each item with its caveat.
5. Buyer questions with short answers.
6. Sources: title, platform, date or "date unknown", and video timestamp links. External links use `rel="nofollow ugc noopener"`.
7. Coverage note (what was and was not covered).
8. "Report a correction" link opening a short form that posts to `op:submitCorrection` (message, optional contact, hidden honeypot field; rate-limited).

**Delivery markers.** The module root carries `data-insights-state="active"`, `data-insights-revision="<revision id>"` and `data-insights-hash="<payload sha256>"`. With nothing active it renders a short empty state with `data-insights-state="empty"` and no revision attributes, and the rest of the page stays usable. The publication worker verifies delivery by reading these attributes (docs/03, docs/05).

**Revalidation route** (web app, called only by the backend): `POST /api/revalidate` with body `{slug, revision_id}` and an HMAC-SHA256 signature of the body in `X-Revalidate-Signature`, using the shared `REVALIDATION_SECRET`. It revalidates `/projects/[slug]` and returns `{revalidated: true}`. An acknowledgement is not proof of delivery; the marker check is.

**Metadata.** Title and description come from the payload; the canonical path is `/projects/[slug]`; robots is `noindex` for the POC (accepted, I14). JSON-LD is rendered exactly as stored in the approved payload.

**Layout.** Tested at 360 px and 1280 px wide, with long project names, Hindi text, empty optional sections and escaped user-facing text.
