# Moderator operating guide

For the people who run the console: researchers, moderators and publishers. Sign in at `http://localhost:3000/console` with your console account. One person may hold several roles; the console shows only the actions your roles allow, and the backend checks every action again.

The console runs the real system. Starting a run collects from the live sources and runs the Claude review curator within the model budget, so it spends paid credits. Nothing else in the console starts paid work: a page built from reviews calls no model (only the full analysis's findings use the page writer and checker, both Claude agents).

Every project follows four steps, and a banner above its tabs (and the **Next step** column of the portfolio) says which one it is at and what to do: **1 Run → 2 Approve reviews → 3 Build the page → 4 Approve and publish.** The tabs are in that order (Runs, Reviews, Page, Publishing), followed by Sources, Videos and Setup; Findings appears only when the full analysis is on.

## 1. Add a project and run it (researcher)

1. **Portfolio → Add a project.** Name, locality and city are required; give the state so the right RERA portal is used. Alternate names help matching; RERA numbers are optional (one per line: `number | registered name`).
2. You land on the project's **Runs** tab. Choose where to look (review pages on the web: MagicBricks, 99acres, Housing.com, NoBroker, Quora and forums found by Brave; YouTube; Reddit; and any optional source enabled in Setup; each shows its connectors' status) and how many days back, then **Start run**. The dialog reminds you that the run uses paid services; confirm only when you mean it.
3. The run page follows the stages: collecting, reading reviews, awaiting decisions. Its coverage table updates while it works and says, per source, what was searched, read, matched and analysed. "Access pending", "partial" and "unavailable" mean a source was not fully read; they are not zero discussion. "Nothing usable found" is a valid result: nothing is invented to fill the page. When the run reaches its review, a button takes you to the reviews to decide.
4. **Setup** holds the configuration (sources, languages, refresh, negative keywords) and the construction status. Keep the status right: a review that says "we live here" in a project that is not handed over is flagged and cannot be approved.

## 2. Review what was found (moderator)

- **Reviews** are one person's review each, from a portal, Reddit, Quora, a forum or YouTube, in their own words. Each shows the text as the page will show it, its word count, the author's original words when it was shortened or translated, the source line (who, platform, date) and the source link (for you only; the public page shows neither). Approve the real reviews of this project; reject the rest. Positive and negative reviews are decided the same way. Approval is disabled while a review is flagged or its words do not match the original. A review outside 30 to 80 words can be approved but not shown on the page; **Choose other spans or fix the translation** can shorten it to whole sentences.
- **Findings** (full analysis only) are pros, cons and neutral points written from the claims, with the exact evidence beside them and any contradicting evidence marked. Approve only what the evidence supports. "Independent origins" counts how many separate sources say it, which is spread, not proof.
- **Edit as a new revision** when wording needs to change. The backend refuses to turn an opinion into a fact, to add numbers the claims do not contain or to drop a required caveat. Earlier decisions stay on record as "superseded".
- **Evidence** lists every source with its date and match; open one to read the full text with the evidence highlighted, accept or reject the project match, or withdraw the source (its words are erased and everything built on it is re-checked; a published page stops showing it).
- **Videos** shows which videos were analysed and which are metadata only; a title or description is never evidence of what is said in a video.

## 3. Build the page (moderator)

1. **Page → Build the page.** Up to 20 approved reviews of 30 to 80 words are ticked for you, positive, negative and mixed in proportion; change the selection if you like, then **Generate draft**. No model is called; the draft opens when it is ready. The public page shows the reviews as Person 1, Person 2 and so on, in the authors' own words, with no other line of ours.
2. In the draft, the heading, search title and description can be edited, and reviews reordered, removed or added from the approved ones (any approved review of the project, within the limits). Give a reason and **Save and run QA**: every save is a new revision, and an earlier approval never carries over. A review's words cannot be changed here; fix a review on the Reviews tab. QA issues sit on the block they concern; a blocking issue keeps the revision a draft.
3. After the first draft, the page changes only by editing its latest revision; **Build the page** returns when a new run reaches its review.
4. **Preview** shows the revision in the real public template, privately.
5. **Approve revision N** shows exactly what you approve: revision number, payload and manifest hashes, evidence epoch and state version. If anything changed since you loaded the page, the approval is refused and nothing is approved. With the publisher role you may tick "Also publish it now"; approval and publication are still two separate, audited actions.

## 4. Publish (publisher)

- **Publishing** shows three things separately: the approved revision, the active one (what the page serves) and the one verified on the rendered page. Publication is successful only when verified; "delivery pending" or "failed" means the page has not been confirmed to show it.
- **Roll back** to an earlier revision only works if it is still eligible and its approval holds at the current evidence epoch; withdrawn content never returns. **Unpublish** shows the empty state.

## 5. Corrections, operations and administration

- **Corrections**: readers' reports from the public page. Resolve or dismiss with a reason; a substantive correction goes through an edit and a new approval.
- **Operations**: connector status and quotas, jobs (failed ones first), model usage and cost by agent, evaluation results. Keys and raw source text are never shown.
- **Administration** (admin): users and roles, source policy versions (a new version narrows or widens rights; narrowing re-checks everything built on that source family), and the audit record of every decision.
