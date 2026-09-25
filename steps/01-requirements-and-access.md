# Step 01: Requirements, source access and acceptance definition

**Release:** 1.0, complete five-project POC. **Initial status:** not started.

Register the five projects, define the incremental source-access plan, set editorial and operating defaults, write the initial source policies and freeze acceptance definitions. Because the POC is standalone, there is no existing catalogue, CMS or website to inspect.

## Prerequisites

None. Begin with the master guide and the five-project input file.

Read [MASTER.md](../MASTER.md), [CHANGELOG.md](../CHANGELOG.md), the relevant entries in [DECISIONS.md](../DECISIONS.md), and these specifications:

- [Architecture and stack](../docs/01-architecture-and-stack.md)
- [Source integrations](../docs/06-source-integrations.md)
- [Validation and release](../docs/07-validation-and-release.md)

## Original requirements covered (revised)

1.1 Register the five supplied projects with project names, alternate names, locality and city (micromarket and other enrichment optional); confirm languages, refresh frequency, history window and user roles.

1.2 Define the project record and slug conventions for the POC's own catalogue.

1.3 Note which supplied projects are likely to be ambiguous (common names, multiple phases) or sparse, for evaluation coverage.

1.4 Agree the source matrix and distinguish mandatory sources from desired coverage; record every connector as `access_pending`.

1.5 Plan credential acquisition in the suggested order (Anthropic → Brave → Firecrawl → YouTube → others) and record where each secret will live.

1.6 Define evidence thresholds, review policy, source retention, initial source policies and correction ownership.

1.7 Agree measurable release acceptance criteria and freeze product scope.

Deliverables: registered scope, connector matrix, seed catalogue file, initial source-policy set, evaluation brief and dependency register.

## Detailed implementation

### 01.1 Register the five inputs

Validate `contracts/five-project-input-template.json`: non-empty `project_name`, `locality`, `city`; `alternate_names` array; optional `micromarket`, `developer`, `phase`, `rera_ids`, `reference_url`. Record unresolved placeholders. Retain the user's spellings and add normalised search forms separately. Define the slug rule (city + locality + name, lower-kebab, unique) and the generated project ID format.

### 01.2 Write the source-access plan

Create the connector matrix from docs/06 with every row `access_pending`, the credential location (`.env` key name), the demonstration required to flip it to live, and whether it is mandatory for the demo. Record the product owner's answers for I04 (mandatory sources) and I05 (video transcript route) or mark them open.

### 01.3 Set editorial and operating defaults

Confirm languages (I07), output locale, history window and refresh cadence (I08), seeded users and roles (I09), evidence recurrence standard, freshness policy and correction owner. Defaults from MASTER.md remain provisional until recorded as accepted.

### 01.4 Draft the initial source-policy set

For each platform family, write the initial `ai_source_policies` entry: collection allowed, AI processing allowed, quotation allowed, derived publication allowed, attribution required, retention. Base it on the platform's public terms and the scraping policy in docs/06. Policies are data loaded by a seed script, not code constants.

### 01.5 Prepare evaluation coverage

Identify, among the five projects, likely ambiguous names, multiple phases, sparse chatter and conflicting reports. Plan labelled synthetic fixtures for the adversarial cases in docs/04.

### 01.6 Freeze acceptance definitions

Agree metrics, sample limits, source coverage and the single-release boundary. Record approval owners in DECISIONS.md. The coding assistant cannot grant data rights or claim stakeholder sign-off.

## Required deliverables

- Validated five-project input file (or a precise list of missing fields) and the slug/ID convention.
- Connector matrix with `access_pending` rows and credential plan; initial source-policy seed data.
- Updated DECISIONS.md: accepted defaults, acceptance definitions, open inputs with owners.

## Acceptance checks

- [ ] Every project row validates or is explicitly unresolved with the missing field named.
- [ ] Every connector has a row with status `access_pending`, credential location and demonstration criteria.
- [ ] Initial source policies exist as seed data for every platform family in the matrix.
- [ ] No extra project inputs or separate product release has been introduced.
- [ ] [PROGRESS.md](../PROGRESS.md) records changed paths, decisions, evidence, unresolved dependencies and the next action.

## Missing access or information

If the input file is still a template, complete the conventions, matrix and policies with clearly synthetic placeholder projects and keep real registration blocked. Credentials come through `.env` (local) or GitHub Actions secrets, never Markdown.

## Coding prompt

```text
Implement Step 01 from steps/01-requirements-and-access.md in this repository.
Read MASTER.md, CHANGELOG.md, PROGRESS.md, this step and its linked specifications.
This is a fresh standalone repository: validate the five-project input file, define the
catalogue/slug conventions, create the connector matrix with every source access_pending,
draft the initial source-policy seed data and record accepted defaults and open inputs in
DECISIONS.md. Do not invent project data, platform access or passing test results.
Update PROGRESS.md with changed paths, actual results, decisions, blockers and the next
executable action.
```

## Completion and handoff

Mark this step complete only when its deliverables and applicable acceptance checks have evidence. Next: [Step 02: UX, architecture and contracts](02-ux-architecture-and-contracts.md)
