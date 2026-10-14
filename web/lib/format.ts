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

/** What each connector is, for people who did not build it. */
export const CONNECTOR_NAMES: Record<string, string> = {
  brave_search: "Brave web search",
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
    detail: "Brave finds the project's pages on MagicBricks, 99acres, Housing.com, NoBroker, Quora and forums; the web reader keeps each person's review.",
    connectors: ["brave_search", "web_fetch"],
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
