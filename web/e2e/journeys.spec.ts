import { expect, type Page, test } from "@playwright/test";

// Console and public-page journeys (Step 09.7, docs/10). Seeded by backend/tests/e2e_seed.py: the fictional
// Quillon Residences project waits at findings review with pending findings and first-person reviews. The journeys
// never start a run and select reviews only for content, so nothing reaches a paid provider.

const PASSWORD = process.env.E2E_PASSWORD ?? "";
const PROJECT = process.env.E2E_PROJECT_ID ?? "";
const SLUG = process.env.E2E_SLUG ?? "";
const MODERATOR = "e2e-moderator@example.test";
const ANALYST = "e2e-analyst@example.test";

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto("/console/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("signed-in-user")).toBeVisible();
}

async function confirmDialog(page: Page, button: string, reason?: string) {
  const dialog = page.getByRole("dialog");
  if (reason) await dialog.getByRole("textbox").first().fill(reason);
  await dialog.getByRole("button", { name: button, exact: true }).click();
  await expect(dialog).toBeHidden();
}

test.describe.serial("console to public page", () => {
  test.beforeAll(() => {
    expect(PASSWORD.length, "E2E_PASSWORD").toBeGreaterThanOrEqual(12);
    expect(PROJECT, "E2E_PROJECT_ID").toMatch(/^prj_/);
  });

  test("the portfolio lists projects and a researcher adds one; starting a run asks first", async ({ page }) => {
    await signIn(page, MODERATOR);
    const quillon = page.getByTestId("portfolio-row").filter({ hasText: "Quillon Residences" });
    await expect(quillon).toBeVisible();
    await expect(quillon).toContainText("waiting for a decision"); // the next step (D68): the seeded reviews
    const form = page.getByTestId("add-project-form");
    const name = `Journey Heights ${Date.now() % 100000}`;
    await form.getByLabel("Project name (required)").fill(name);
    await form.getByLabel("Locality (required)").fill("Hinjewadi");
    await form.getByLabel("City (required)").fill("Pune");
    await form.getByLabel("State").fill("Maharashtra");
    await form.getByRole("button", { name: "Add project" }).click();
    await expect(page).toHaveURL(/\/console\/projects\/prj_[0-9A-Z]+\/runs$/);
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByTestId("next-step")).toContainText("Start the first run");
    await expect(page.getByText("Reddit", { exact: true })).toBeVisible();
    await page.getByTestId("start-run").click();
    await expect(page.getByRole("dialog")).toContainText("paid services");
    await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByText("No run yet.")).toBeVisible();
  });

  test("findings are decided beside their evidence; reviews are approved in the author's words", async ({ page }) => {
    await signIn(page, MODERATOR);
    await page.goto(`/console/projects/${PROJECT}/findings`);
    const finding = page.getByTestId("finding").first();
    await expect(finding.getByText("open the source").first()).toBeVisible();
    await finding.getByTestId("reject").click();
    await confirmDialog(page, "Reject", "Not specific enough for the page");
    await expect(page.getByTestId("finding").first()).toContainText("rejected");

    await page.goto(`/console/projects/${PROJECT}/reviews`);
    const count = await page.getByTestId("review").count();
    expect(count).toBeGreaterThan(0);
    for (let left = count; left > 0; left--) {
      // wait until the page shows the previous decision before taking the next one
      await expect(page.getByTestId("approve")).toHaveCount(left);
      const review = page.getByTestId("review").filter({ has: page.getByTestId("approve") }).first();
      await review.getByTestId("approve").click();
      await confirmDialog(page, "Approve");
    }
    await expect(page.getByTestId("approve")).toHaveCount(0);
  });

  test("content from approved reviews is generated, approved, published and verified on the public page", async ({ page }) => {
    await signIn(page, MODERATOR);
    await page.goto(`/console/projects/${PROJECT}/content`);
    await expect(page.getByText("Reviews only: no model is called")).toBeVisible();
    await page.getByTestId("generate").click();
    await expect(page.getByText("Generating in the background")).toBeVisible();
    // the form follows the run and opens the draft when it is ready
    await expect(page).toHaveURL(/\/content\/rev_[^/]+$/, { timeout: 60_000 });
    await expect(page.getByText("Person 1", { exact: true })).toBeVisible();
    await page.getByTestId("final-approve").click();
    const dialog = page.getByRole("dialog", { name: "Final approval" });
    await expect(dialog).toContainText("payload hash");
    await dialog.getByLabel("Also publish it now (two separate, audited actions)").check();
    await dialog.getByRole("button", { name: "Approve and publish" }).click();
    await expect(page).toHaveURL(/\/publishing$/);
    await expect(async () => {
      await page.reload();
      await expect(page.getByRole("table", { name: "Publication operations" })).toContainText("verified", { timeout: 2_000 });
    }).toPass({ timeout: 60_000 });

    await page.goto(`/projects/${SLUG}`);
    const insights = page.locator("[data-insights-state='active']");
    await expect(insights).toHaveAttribute("data-insights-revision", /^rev_/);
    await expect(insights).toHaveAttribute("data-insights-hash", /^sha256:/);
    // D69: each review under "Person N" in the author's words; no credit, intro or disclosure line of ours.
    const reviews = page.getByTestId("public-review");
    await expect(reviews.first()).toContainText("Person 1");
    await expect(reviews.first().locator("blockquote")).toContainText("Quillon Residences");
    await expect(insights).not.toContainText("From a");
    await expect(insights).not.toContainText("the client");
  });

  test("an edit is a new revision that needs its own approval; the page keeps serving the approved one", async ({ page }) => {
    await signIn(page, MODERATOR);
    await page.goto(`/projects/${SLUG}`);
    const served = await page.locator("[data-insights-state='active']").getAttribute("data-insights-revision");
    await page.goto(`/console/projects/${PROJECT}/content`);
    await page.getByRole("link", { name: "revision 1", exact: true }).click();
    await page.getByLabel("Heading").fill("Buyers on Quillon Residences");
    await page.getByLabel("Reason for the edit (required)").fill("shorter heading");
    await page.getByTestId("save-revision").click();
    await expect(page.getByRole("heading", { name: "Revision 2" })).toBeVisible();
    await expect(page.getByTestId("final-approve")).toBeVisible();
    await page.goto(`/projects/${SLUG}`);
    await expect(page.locator("[data-insights-state='active']")).toHaveAttribute("data-insights-revision", served ?? "");
  });

  test("a reader reports a correction and a moderator resolves it", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto(`/projects/${SLUG}`);
    await page.getByRole("button", { name: "Report a correction" }).click();
    await page.getByLabel("What should be corrected?").fill("Journey check: the review date looks wrong.");
    await page.getByRole("button", { name: "Send report" }).click();
    await expect(page.getByText("Our editors will review your report")).toBeVisible();
    await signIn(page, MODERATOR);
    await page.goto("/console/corrections");
    const row = page.getByRole("row").filter({ hasText: "Journey check" });
    await row.getByRole("button", { name: "Resolve" }).click();
    await confirmDialog(page, "Resolve", "Checked the source date");
    await expect(page.getByRole("row").filter({ hasText: "Journey check" })).toContainText("resolved");
  });

  test("an analyst reads findings but has no decision controls", async ({ page }) => {
    await signIn(page, ANALYST);
    await page.goto(`/console/projects/${PROJECT}/findings`);
    await expect(page.getByTestId("finding").first()).toBeVisible();
    await expect(page.getByTestId("approve")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Edit as a new revision" })).toHaveCount(0);
  });
});
