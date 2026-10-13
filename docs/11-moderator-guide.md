# Moderator operating guide

For the people who run the console: researchers, moderators and publishers. Sign in at `http://localhost:3000/console` with your console account. One person may hold several roles; the console shows only the actions your roles allow, and the backend checks every action again.

The console runs the real system. Starting a run collects from the live sources and runs the Claude agents within the model budget, so it spends paid credits. Nothing else in the console starts paid work, except generating page content from findings (the page writer and checker are Claude agents); a page built from reviews alone calls no model.

## 1. Add a project and run it (researcher)

1. **Portfolio → Add a project.** Name, locality and city are required; give the state so the right RERA portal is used. Alternate names help matching; RERA numbers are optional (one per line: `number | registered name`).
2. You land on the project's **Runs** tab. Choose the window (days back) and the sources, then **Start run**. The dialog reminds you that the run uses paid services; confirm only when you mean it.
3. The run page follows the stages: collecting, analysing, findings review. The coverage table says, per source, what was searched, fetched, matched and analysed. "Access pending", "partial" and "unavailable" mean a source was not fully read; they are not zero discussion. "Insufficient evidence" is a valid result: nothing is invented to fill the page.
4. **Setup** holds the configuration (sources, languages, refresh, negative keywords) and the construction status. Keep the status right: a review that says "we live here" in a project that is not handed over is flagged and cannot be approved.

## 2. Review what was found (moderator)

- **Reviews** are first-person posts and comments by real people, in their own words. Each shows the text as the page will show it, the author's original words when it was shortened or translated, the credit line (who, platform, date) and the source link (for you only; the public page never links to it). Approve, reject or request changes; positive and negative reviews are decided the same way. Approval is disabled while a review is flagged or its words do not match the original.
- **Findings** are pros, cons and neutral points written from the claims, with the exact evidence beside them and any contradicting evidence marked. Approve only what the evidence supports. "Independent origins" counts how many separate sources say it, which is spread, not proof.
- **Edit as a new revision** when wording needs to change. The backend refuses to turn an opinion into a fact, to add numbers the claims do not contain or to drop a required caveat. Earlier decisions stay on record as "superseded".
- **Evidence** lists every source with its date and match; open one to read the full text with the evidence highlighted, accept or reject the project match, or withdraw the source (its words are erased and everything built on it is re-checked; a published page stops showing it).
- **Videos** shows which videos were analysed and which are metadata only; a title or description is never evidence of what is said in a video.

## 3. Build the page (moderator)

1. **Content → Generate page content.** Tick the approved reviews (and findings, if any) to use. With reviews only, the page is assembled at once from the approved words; with findings, the page writer and checker run first.
2. Open the new revision. QA issues sit on the block they concern; a blocking issue keeps the revision a draft. Edit the blocks, give a reason and **Save and run QA**: every save is a new revision, and an earlier approval never carries over. You can remove a review from the page or move it, but not change its words.
3. **Preview** shows the revision in the real public template, privately.
4. **Approve revision N** shows exactly what you approve: revision number, payload and manifest hashes, evidence epoch and state version. If anything changed since you loaded the page, the approval is refused and nothing is approved. With the publisher role you may tick "Also publish it now"; approval and publication are still two separate, audited actions.

## 4. Publish (publisher)

- **Publishing** shows three things separately: the approved revision, the active one (what the page serves) and the one verified on the rendered page. Publication is successful only when verified; "delivery pending" or "failed" means the page has not been confirmed to show it.
- **Roll back** to an earlier revision only works if it is still eligible and its approval holds at the current evidence epoch; withdrawn content never returns. **Unpublish** shows the empty state.

## 5. Corrections, operations and administration

- **Corrections**: readers' reports from the public page. Resolve or dismiss with a reason; a substantive correction goes through an edit and a new approval.
- **Operations**: connector status and quotas, jobs (failed ones first), model usage and cost by agent, evaluation results. Keys and raw source text are never shown.
- **Administration** (admin): users and roles, source policy versions (a new version narrows or widens rights; narrowing re-checks everything built on that source family), and the audit record of every decision.
