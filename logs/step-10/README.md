# Step 10 logs

Steps 09 and 10 were built together (the product owner asked for the whole frontend end to end in these steps) and share one check script, mutation check and browser journeys. Their plan and results are in [logs/step-09/README.md](../step-09/README.md).

Step 10 specifics:

- Generation, deterministic QA, A08 and A09, edits, final approval and the publication core: `backend/app/content/`, `backend/app/publication/`, the analysis graph's `format` node (D64, D66).
- Prompt caching (D65): `backend/app/agents/gateway.py`, `backend/app/agents/spend.py`.
- Evidence: `backend/tests/test_content.py` and the content and caching mutants in `logs/step-09/mutation-check-*.log`.
- Not yet done live: A08 and A09 have not been called with a real key (no credit spend by the product owner's instruction, 13 Oct 2026). Their first live call happens when a moderator generates a page that includes findings.
