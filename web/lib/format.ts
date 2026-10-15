/** Display helpers for the console and the public page (display timezone Asia/Kolkata, seed/operating_defaults). */

const TIME_ZONE = "Asia/Kolkata";

export function formatTime(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { timeZone: TIME_ZONE, dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function formatDay(value: string | null | undefined): string {
  if (!value) return "date unknown";
  const date = new Date(value.length === 10 ? `${value}T00:00:00Z` : value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-IN", { timeZone: TIME_ZONE, day: "numeric", month: "short", year: "numeric" }).format(date);
}

type Dated = { status: string; value: string | null; precision?: string | null } | null | undefined;

/** A DatedValue: unknown stays unknown (docs/02 item 5). */
export function formatDated(value: Dated): string {
  if (!value || value.status === "unknown" || !value.value) return "date unknown";
  const day = formatDay(value.value);
  return value.status === "approximate" ? `about ${day}` : day;
}

export function shortHash(hash: string | null | undefined): string {
  if (!hash) return "none";
  return hash.replace("sha256:", "").slice(0, 12);
}

export function label(value: string | null | undefined): string {
  return (value ?? "").replaceAll("_", " ");
}

/** Video moment as m:ss or h:mm:ss. */
export function moment(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  const total = Math.floor(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** Run stages in the words of the review-first flow (the stored names stay as the contract has them). */
export const STAGE_LABELS: Record<string, string> = {
  collecting: "collecting",
  analysing: "reading reviews",
  findings_review: "awaiting decisions",
  formatting: "building the page",
  final_review: "page approval",
  approved: "approved",
  publishing: "publishing",
  published: "published",
  insufficient_evidence: "nothing usable found",
  cancelled: "cancelled",
};

export function stageLabel(stage: string | null | undefined): string {
  return STAGE_LABELS[stage ?? ""] ?? label(stage);
}

type RunLike = { stage: string; outcome_note?: string | null; content_revision_id?: string | null; updated_at?: string };

/** Whether the system is working on a run right now, so a page showing it refreshes itself (audit, 14 Oct 2026):
 * collecting; analysing unless it stopped; building the page until its draft exists; publishing only for a few
 * minutes (a failed delivery leaves the run publishing). Stages that wait for a person never refresh by themselves. */
export function runIsWorking(run: RunLike | null | undefined): boolean {
  if (!run) return false;
  if (STOPPED.test(run.outcome_note ?? "")) return false;
  switch (run.stage) {
    case "collecting":
    case "analysing":
      return true;
    case "formatting":
      return !run.content_revision_id;
    case "publishing":
      return !!run.updated_at && Date.now() - Date.parse(run.updated_at) < 10 * 60_000;
    default:
      return false;
  }
}

/** A run whose analysis or page building stopped and waits for someone to continue it. */
export const STOPPED = /^(Analysis|Page building) stopped/;

type Coverage = { status: string; note: string | null };

/** A coverage entry as people read it: "queued" before its source starts, "running" while it works (the backend
 * writes "in progress: ..." with its counts so far), then its final status. Once the run has left collecting, an
 * entry still queued or running did not finish: it says so, never "running" (audit, 14 Oct 2026). */
export function coverageState(c: Coverage, stage?: string): { status: string; text: string; detail: string | null } {
  const note = c.note ?? "";
  const open = c.status === "partial" && (note === "queued" || note.startsWith("in progress: "));
  if (open && stage && stage !== "collecting") {
    return { status: "partial", text: "not finished", detail: note.startsWith("in progress: ") ? note.slice(13) : null };
  }
  if (c.status === "partial" && note === "queued") return { status: "queued", text: "queued", detail: null };
  if (c.status === "partial" && note.startsWith("in progress: ")) {
    return { status: "running", text: "running", detail: note.slice("in progress: ".length) };
  }
  return { status: c.status, text: c.status === "complete_for_query" ? "complete" : label(c.status), detail: c.note };
}

/** What a working source says it is doing, split from its counts so far ("24 of up to 80 pages read; fetched: 20;
 * refused: 4"), with the step it is on when the note names one ("search 3 of 9", "thread 2 of 10", "post 4 of up
 * to 12"). The numbers come from the backend's own note (Collector.progress); nothing is estimated. */
export function activity(detail: string | null | undefined): {
  doing: string;
  step: { done: number; total: number; upTo: boolean } | null;
  counts: { key: string; value: string }[];
} {
  const parts = (detail ?? "").split("; ").filter(Boolean);
  const isCount = (part: string) => /^[^:]+(:[^:]+)?: .+$/.test(part) && !/ of /.test(part);
  const lead = parts.findIndex(isCount);
  const said = lead === -1 ? parts : parts.slice(0, lead);
  const doing = said.join("; ");
  const match = doing.match(/(\d+) of (up to )?(\d+)/);
  const step = match ? { done: Number(match[1]), total: Number(match[3]), upTo: Boolean(match[2]) } : null;
  const counts = parts.slice(said.length).map((part) => {
    const at = part.lastIndexOf(": ");
    return at > 0 ? { key: part.slice(0, at), value: part.slice(at + 2) } : { key: part, value: "" };
  });
  return { doing, step, counts };
}

/** A note's count key in words: "not_collected:linkedin" reads "not collected · linkedin". */
export function countLabel(key: string): string {
  return label(key).replace(":", " · ");
}

/** A span of time in minutes and hours ("under a minute", "7 min", "2 h 5 min", "3 days"). */
export function duration(ms: number): string {
  if (!Number.isFinite(ms) || ms < 60_000) return "under a minute";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
  return `${Math.floor(hours / 24)} days`;
}

/** Milliseconds from `start` to `end` (now when omitted). */
export function since(start: string, end?: string): number {
  return (end ? Date.parse(end) : Date.now()) - Date.parse(start);
}

/** How long ago, for "updated 3 min ago". */
export function ago(value: string | null | undefined, now = Date.now()): string {
  if (!value) return "never";
  const at = Date.parse(value);
  if (Number.isNaN(at)) return value;
  const span = now - at;
  return span < 60_000 ? "just now" : `${duration(span)} ago`;
}

/** A run's stage as a badge: a stage the system works in shows as working only while it does; a stopped analysis
 * says "stopped" (the stored stage stays analysing or formatting until someone continues it). */
export function runBadge(run: RunLike): { status: string; text: string } {
  if (STOPPED.test(run.outcome_note ?? "")) return { status: "partial", text: "stopped" };
  if (["collecting", "analysing", "formatting", "publishing"].includes(run.stage) && !runIsWorking(run)) {
    return { status: run.stage === "formatting" ? "needs_review" : "partial", text: stageLabel(run.stage) };
  }
  return { status: run.stage, text: stageLabel(run.stage) };
}

/** What each connector is, for people who did not build it. */
export const CONNECTOR_NAMES: Record<string, string> = {
  brave_search: "Brave web search",
  firecrawl_search: "Firecrawl web search",
  web_fetch: "Web reader",
  firecrawl: "Firecrawl page renderer",
  playwright_fetch: "Browser page renderer",
  youtube_data_api: "YouTube",
  reddit_public: "Reddit (PullPush archive)",
  reddit_api: "Reddit official API",
  instagram_public: "Instagram",
  spoken_video_transcripts: "Spoken video transcripts",
  harera_registry: "State RERA registry",
  x_api: "X",
  meta_graph_api: "Facebook and Instagram official API",
  listening_provider: "Social listening provider",
};

export function connectorName(id: string): string {
  return CONNECTOR_NAMES[id] ?? label(id);
}

/** The sources a run can use, as people think of them. A group runs its enabled connectors together: the web reader
 * reads what Brave finds, so they are one choice. Firecrawl and the browser renderer only help the web reader. */
export const RUN_SOURCES = [
  {
    key: "web",
    label: "Review pages on the web",
    detail:
      "Brave and Firecrawl search find the project's pages on MagicBricks, 99acres, Housing.com, NoBroker, Quora and forums, and the portals' project pages; the web reader keeps each person's review.",
    connectors: ["brave_search", "firecrawl_search", "web_fetch"],
  },
  { key: "youtube", label: "YouTube", detail: "Videos about the project and their comments.", connectors: ["youtube_data_api"] },
  { key: "reddit", label: "Reddit", detail: "Posts and comments naming the project, through the free PullPush archive.", connectors: ["reddit_public", "reddit_api"] },
  { key: "instagram", label: "Instagram", detail: "Public posts, read through Scrapfly.", connectors: ["instagram_public"] },
  { key: "transcripts", label: "Spoken video transcripts", detail: "What is said in the videos found.", connectors: ["spoken_video_transcripts"] },
  { key: "registry", label: "State RERA registry", detail: "Registration records; the reviews-only analysis does not use them.", connectors: ["harera_registry"] },
] as const;

export const HELPER_CONNECTORS = ["firecrawl", "playwright_fetch"];

const SPEAKERS: Record<string, string> = {
  a_buyer: "a buyer",
  a_resident: "a resident",
  an_owner_awaiting_possession: "an owner awaiting possession",
  a_site_visitor: "a site visitor",
  a_prospective_buyer: "a prospective buyer",
  a_viewer: "a viewer",
  a_video_creator: "a video creator",
  an_owner: "an owner",
  a_user: "a user",
};

const LANGUAGES: Record<string, string> = { hi: "Hindi", "hi-Latn": "Hinglish", en: "English" };

type Credit = {
  speaker_label: string;
  platform: string;
  kind: string;
  published: Dated;
  timestamp_ms: number | null;
  translated_from: string | null;
};

/** The credit line under a first-person review (D28): who, platform, date, video moment, translation. */
export function creditLine(credit: Credit): string {
  const who = SPEAKERS[credit.speaker_label] ?? label(credit.speaker_label);
  const where =
    credit.kind === "comment"
      ? `'s comment on ${credit.platform}`
      : credit.kind === "video"
        ? ` in a ${credit.platform} video`
        : credit.kind === "review"
          ? `'s review on ${credit.platform}`
          : ` on ${credit.platform}`;
  const at = credit.kind === "video" && credit.timestamp_ms !== null ? ` at ${moment(credit.timestamp_ms)}` : "";
  const translated = credit.translated_from ? ` (translated from ${LANGUAGES[credit.translated_from] ?? credit.translated_from})` : "";
  return `From ${who}${where}${at}, ${formatDated(credit.published)}${translated}`;
}
