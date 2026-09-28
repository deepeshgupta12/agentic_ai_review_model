# Prompts

Reviewed prompt templates for the model-backed agents (A01–A11), one file per agent and version. Step 08 adds the first real templates; this directory exists from Step 03 so the layout in [docs/01](../docs/01-architecture-and-stack.md) is complete.

- File name: `<agent>.<major>.<minor>.md` with the agent ID in lower case, for example `a07_findings_synthesiser.1.0.md`. The name without `.md` is the `prompt_version` every `ai_agent_runs` record stores (pattern `^[a-z0-9_]+\.\d+\.\d+$`, [operations schema](../contracts/v1/operations.schema.json)).
- A published version is never edited. A change is a new version, reviewed like code and checked by the evaluations in [evals/](../evals/).
- Templates hold instructions only. Model IDs come from configuration by role (D10), and output shapes come from the agent schemas in [contracts/v1/agents.schema.json](../contracts/v1/agents.schema.json).
- No credentials, personal data or raw source text belong here.
