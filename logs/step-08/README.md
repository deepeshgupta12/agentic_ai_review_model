# Step 08 test plan and logs

Step 08 connects the specialist agents into a durable workflow that turns eligible evidence into traceable draft findings and pauses for a person's decision ([step spec](../../steps/08-agents-and-master-workflow.md)). Operating decisions are in D53: live model spend is capped at $2 by the gateway, the HRERA registry reader is built so facts can be verified against dated official records, the product owner checks a sample of real outputs, and there is no results viewer before the Step 09 console.

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-10-09 | worktree | Implementer | identity evaluation after I19 (identity-rules.1.1; dataset 1.1.0, 40 cases) | Auto-accept precision 100% (25 pairs); relevant linked 97.0%; auto-accepted 75.8%; sent to review 26.5%; same name in another city rejected 100% (3); no regression against Step 04 | (console) |
| 2026-10-09 | worktree | Implementer | Instagram feasibility (I20): one Brave search and plain fetches of three public posts | Brave found 3 public posts; every instagram.com fetch failed certificate verification on this network (intercepted). Not worked around | (console) |
