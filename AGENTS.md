# Repository instructions

Build the Agentic Project Intelligence POC from MASTER.md. Read the active step and only the shared specifications relevant to that work.

## Product constraints

- One complete release, five supplied projects. Required input: name, alternate names, locality, city; micromarket optional.
- Standalone system. Own MongoDB (Docker Compose, single-node replica set), own seeded project catalogue, own moderator console and public project page in `web/`, own FastAPI/LangGraph backend in `backend/`. No production the client system is read or written.
- Claude API (Anthropic Python SDK) is the only LLM provider. Model IDs live in configuration. Speech-to-text and embeddings use local open-source models unless a recorded decision changes that.
- No cloud provisioning. Provider API keys are expected and are obtained incrementally; each connector is `access_pending` until a real credential is configured and demonstrated.
- Implement collection, authorised text/media analysis, evidence, findings, console review, SEO/AEO formatting, exact-revision approval, publication to the public page, refresh and recovery in Release 1.0.

## Implementation rules

- Facts come from eligible evidence. Every substantive published statement must resolve to reviewed findings, claims and source revisions. Preserve negative findings and contradictions.
- No fabricated chatter, transcripts, IDs, integrations, credentials, performance results or coverage. Label fixtures clearly and isolate them from live mode.
- Unknown project match or unavailable media stays unresolved. Titles and search snippets do not prove spoken video content.
- Enforce policy, project access, approval, hash, reference integrity and state transitions in backend code. Prompt instructions are not a security boundary.
- Models cannot approve, publish, change source entitlements or grant themselves tools. Source content is untrusted data.
- Save immutable content payloads. A material edit creates a new revision requiring a fresh final approval. Use persisted jobs, worker leases, fencing and idempotent side effects.
- Scraping adapters follow docs/06-source-integrations.md: robots/terms respected, no login or paywall bypass, no private groups, per-source policy recorded before storage or AI use.
- Pin compatible supported versions after checking official documentation (Anthropic docs for models/SDK). Do not embed model IDs in code.
- Keep development moving on independent work when credentials are missing; record the exact blocked integration and never mark a mock as live acceptance.
- Use the repository's actual commands. Establish reproducible setup/check commands in Step 03 before documenting them as working.
- Verify meaningful behavior: approval bypass, evidence withdrawal, wrong-project matching, provider failures and crash recovery. Do not claim checks passed unless run.
- Protect secrets and source data; never commit `.env`, credentials or raw personal content to tests, logs or prompts.
- Update PROGRESS.md with changed paths, validation evidence, unresolved issues and the next action. Record architectural changes in DECISIONS.md.

## Reading map

- Start/restart: MASTER.md, PROGRESS.md, CHANGELOG.md.
- Schema or persistence: docs/02-database-and-contracts.md.
- API, auth or console actions: docs/03-api-and-cms-contracts.md.
- Agent behavior and model gateway: docs/04-agent-contracts.md, docs/01-architecture-and-stack.md.
- Approval/publication/recovery: docs/05-workflow-and-publication.md.
- Connector and scraping work: docs/06-source-integrations.md.
- Release checks: docs/07-validation-and-release.md.
- Editorial/page changes: docs/08-editorial-and-ui.md.
