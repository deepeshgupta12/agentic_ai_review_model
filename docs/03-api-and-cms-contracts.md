# API, authentication and console/page contracts

Use versioned REST JSON and generated OpenAPI. The backend is the single authority for identity, roles, approvals and publication; the Next.js app is a client of it. There is no external CMS: the moderator console and the public page both live in `web/`.

## Authentication and roles

- Own identity store: `users` collection with argon2 (or bcrypt) password hashes, `roles[]`, `active` flag, created/updated timestamps. Seeded by `scripts/seed_users.py`; no self-registration in the POC.
- Login issues a signed, HTTP-only, SameSite=Lax session cookie from the backend; the console calls the API with that cookie. Mutations require a CSRF token bound to the session. Sessions expire; logout revokes.
- Roles: `admin`, `researcher`, `moderator`, `publisher`, `analyst`. One person may hold several; every action still records which role authorised it. Derive actor and project permissions server-side; never trust actor IDs in request bodies.
- Fixture mode may use a seeded fixture user, never an auth bypass.

## Common behavior

- IDs are opaque strings externally; UTC timestamps include timezone. Paginate with an opaque cursor and bounded limit, using a stable sort (date plus ID).
- Mutations that can repeat use scoped `Idempotency-Key`; same key and request digest returns the existing result, a different digest returns `409`.
- Mutable configuration/editor targets use `If-Match` or `expected_version`; stale writes return `409` with the current version.
- Return `202` and an operation/run ID for collection, generation, publication and rollback. Do not keep an HTTP request open during transcription or long model work.
- Consistent errors: `error.code`, `error.message`, `error.request_id`, safe field details and `retryable`. Use `401`, `403`, `404`, `409`, `422`, `429`, `503`; avoid leaking inaccessible record existence.
- Restrict CORS to the web app origin.

## Endpoints to implement

| Endpoint | Inputs / response | Minimum permission |
|---|---|---|
| `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /v1/auth/me` | Session lifecycle | Any user |
| `POST /v1/projects/import` | Five-project input file; creates/updates catalogue records; returns generated IDs and slugs | Researcher/admin |
| `GET /v1/projects` | Paginated portfolio with run/review/coverage summary | Analyst |
| `GET/PATCH /v1/projects/{id}` | Config; changes require expected version | Analyst / researcher |
| `POST /v1/projects/{id}/runs` | Refresh window/source selection within entitlement; durable run ID | Researcher |
| `GET /v1/runs/{id}` | State, coverage, progress, errors, cost | Analyst |
| `GET /v1/runs/{id}/events` | SSE events with event ID and resume cursor | Analyst |
| `POST /v1/runs/{id}/cancel` | Reason; cooperative cancellation | Researcher |
| `GET /v1/projects/{id}/sources` | Platform/kind/aspect/date/language filters, cursor | Analyst |
| `GET /v1/sources/{id}/revisions/{revision}` | Permitted detail and project-scoped associations | Analyst |
| `GET /v1/projects/{id}/media` | Video/short library, access/analysis status and segments | Analyst |
| `POST /v1/project-source-links/{id}/decisions` | Match/phase/split correction, expected version, reason | Moderator |
| `GET /v1/projects/{id}/alias-proposals` | Proposed/approved/rejected/revoked names with target, evidence and collision result | Analyst |
| `POST /v1/alias-proposals/{id}/decisions` | Approve (standalone or context-required, target project/phase), reject or revoke, with reason and expected version | Researcher/moderator |
| `GET /v1/projects/{id}/findings` | Exact revisions, claims, conflicts and eligibility | Analyst |
| `POST /v1/findings/{id}/revisions` | Edited finding plus source refs; new revision | Moderator |
| `POST /v1/findings/{id}/decisions` | Target revision and approve/reject/changes_requested with reason | Moderator |
| `POST /v1/projects/{id}/content-revisions` | Generate from selected approved findings, or save validated edited draft | Moderator |
| `GET /v1/content-revisions/{id}` | Immutable payload, lineage, checks and private preview data | Moderator |
| `POST /v1/content-revisions/{id}/approvals` | Exact revision/hash/version; server verifies and records decision | Moderator |
| `POST /v1/content-revisions/{id}/decisions` | Reject or request changes to the exact final revision | Moderator |
| `POST /v1/publications` | Project/locale/revision/hash, expected state version, idempotency key | Publisher |
| `GET /v1/publications/{id}` | Activation vs delivery status, receipt and verified revision | Publisher |
| `POST /v1/publications/{id}/rollback` | Eligible prior revision, reason and expected version | Publisher |
| `POST /v1/projects/{id}/unpublish` | Reason, current revision and expected version | Publisher |
| `POST /v1/sources/{id}/withdrawals` | Source revision/scope and reason; dependent review job | Moderator/admin |
| `GET /v1/connectors/health` | Entitlements, last success, quota and safe errors | Researcher |
| `POST /v1/webhooks/{provider}` | Verified signature/replay window/event ID | Trusted provider |
| `GET /v1/public/projects/{slug}/insights` | **Public read.** Returns only the active, eligible revision payload plus revision ID/hash marker, or `404`/empty-state when none is active. Never returns drafts. Cacheable. | None (rate-limited) |
| `POST /v1/public/projects/{slug}/corrections` | **Public write.** Correction/report form → moderation queue. Rate-limited, honeypot/turnstile protected, no personal data required | None |

Route details, response schemas and role names are frozen in Step 02 in [contracts/v1/routes.json](../contracts/v1/routes.json) (47 operations; OpenAPI generated from it) and generated from code from Step 03 onward, with a contract test comparing the two. Step 02 added the operations the console screens need beyond the table above: run lists, content revision lists, publication state, the corrections queue, operations views and administration ([screen specifications](09-screen-specifications.md)). SSE needs authenticated reconnection and bounded retention; polling the run endpoint is a valid UI fallback.

## Page-renderer adapter (replaces the former CMS adapter)

The publication service owns delivery to the public page through these adapter methods:

- `render_private_preview(revision_id)` — the console renders the exact page template with the draft payload, behind authentication, `noindex`.
- `request_page_refresh(slug, revision_id)` — calls the web app's signed revalidation route (`POST /api/revalidate` with a shared secret) to invalidate the ISR cache for `/projects/[slug]`. Store the acknowledgement.
- `get_delivery_status(operation_id)` — persisted state of the delivery job.
- `read_rendered_revision(slug)` — fetches the public page (or its render endpoint) and reads the embedded revision marker (`data-insights-revision`, `data-insights-hash`). Delivery is verified only when the marker equals the activated revision and hash.

The public page's server component calls `GET /v1/public/projects/{slug}/insights` at render time; the backend answers from `ai_publication_state.active_revision_id` and the serving gate, never from the newest draft. A successful revalidation acknowledgement is not proof the page shows the new revision; verification is.

## Contract tests

Test the role matrix, CSRF, wrong-project access, stale versions, reused idempotency keys with different bodies, pagination consistency, unsupported schema versions, safe error messages, webhook signature/replay failure, disconnected SSE recovery, and that the public read endpoint never exposes drafts, withdrawn content or private notes. Generate TypeScript types from OpenAPI; never let web and backend maintain conflicting status enums independently.
