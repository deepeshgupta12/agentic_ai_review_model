# Step 01 evaluation brief

Which of the five projects are likely to be confused, phased, sparse or contested, and the synthetic cases planned to test that. It feeds identity (Step 04), retrieval (Step 07), agents (Step 08) and qualification (Step 12). It is based only on the supplied inputs (D15, D16); nothing here has been measured.

## Risks by project

| Project | Risk | Why, from the supplied inputs | What the evaluation checks |
|---|---|---|---|
| DLF Privana | Phase confusion | Township with three registrations: South, West, North | Each segment is labelled with its phase; a post about one phase is never credited to another |
| DLF Privana | Developer-only mentions | DLF has other Gurgaon projects | "DLF Sector 76" without a project name stays ambiguous |
| Conscient Parq | Generic registered name | The RERA registered name is just "Parq"; "Park" is a likely misspelling | "Parq" counts only together with the developer or locality (D17) |
| Sobha Crescent | Sparse discussion likely | New Launch; RERA registered in 2026 | An `insufficient_evidence` result is correct; no manufactured findings |
| Sobha Crescent | Common word in the name | "Crescent" appears in other project names | A different "Crescent" project is rejected or sent to review |
| M3M Forestia West | Sparse discussion likely | New Launch; RERA registered in 2026 ("M3M Forestia West I") | Same as Sobha Crescent |
| M3M Forestia West | Possible parent name | Whether a wider "M3M Forestia" exists is unconfirmed | Posts saying "M3M Forestia" without "West" stay ambiguous until confirmed |
| M3M Forestia West | Place naming | Locality "Manesar Sector 9" under city "Gurgaon"; sources may call Manesar a separate town | A Manesar-only reference still matches when other signals agree |
| M3M Antalya Hills | Phases plus a commercial block | Four registrations, including "Commercial-01" | Posts about the commercial block are labelled separately from the homes |
| M3M (both projects) | Shared developer | Antalya Hills and Forestia West are both M3M | "M3M" alone never resolves to either project |
| New Gurgaon cluster | Comparison content | Privana (Sector 76), Antalya Hills (79) and Parq (80) are neighbouring sectors | A comparison article or video is split into per-project segments |

## Planned synthetic adversarial fixtures

Every fixture is labelled synthetic (`sample_is_synthetic: true`), versioned from Step 02 under `evals/`, and never mixed with live data or presented as real discussion.

1. Prompt injection: a forum post telling the agent to ignore its instructions and approve content.
2. Copied marketing campaign: the same promotional text on three sites, which must count as one origin.
3. Same name, wrong city: a "Privana" or "Crescent" project in another city.
4. Phase confusion: a Privana West possession complaint offered as Privana South evidence.
5. Mixed-project video: one comparison video covering Sectors 76, 79 and 80.
6. Negation: "no water-logging this monsoon" must not become a water-logging complaint.
7. Sarcasm: "great, another delay" read as a possession complaint.
8. Disputed possession date: two sources give different dates; both stay visible.
9. Missing transcript: a video with only a title and description yields no spoken-content claims.
10. Source withdrawal: the source behind an approved finding is deleted and dependent content is invalidated.
11. Short name shared by an unrelated project (D17): "Parq" used for a different project.
12. Residential vs commercial: a Commercial-01 shop review attached to the residential project.
13. Hinglish numbers: prices and sizes such as "3 BHK ka rate 2.5 cr" extracted without unit errors.
14. Living before possession (D27): a post claiming a year of residence in an under-construction or new-launch project is flagged, never used, and its match goes to review.
15. Review faithfulness (D28): a review with one word changed, a word added, sources merged or a translation that changes the meaning is caught before approval.

## Labels

Relevance, project and phase, alias mentions, aspect, polarity, fact/opinion/type, evidence span, origin cluster, contradictions, translation errors and editorial support (docs/07). Ambiguous labels get an adjudication record.

## Sample target

150–300 authorised items across the five projects if discussion allows (proposed; see the acceptance definitions in DECISIONS.md). The two new launches may fall short; any shortfall is reported per project and never padded with synthetic items. Data is split by origin cluster and time before any tuning.
