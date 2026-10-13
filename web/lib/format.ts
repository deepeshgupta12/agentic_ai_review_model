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

const SPEAKERS: Record<string, string> = {
  a_buyer: "a buyer",
  a_resident: "a resident",
  an_owner_awaiting_possession: "an owner awaiting possession",
  a_site_visitor: "a site visitor",
  a_prospective_buyer: "a prospective buyer",
  a_viewer: "a viewer",
  a_video_creator: "a video creator",
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
  const where = credit.kind === "comment" ? `'s comment on ${credit.platform}` : credit.kind === "video" ? ` in a ${credit.platform} video` : ` on ${credit.platform}`;
  const at = credit.kind === "video" && credit.timestamp_ms !== null ? ` at ${moment(credit.timestamp_ms)}` : "";
  const translated = credit.translated_from ? ` (translated from ${LANGUAGES[credit.translated_from] ?? credit.translated_from})` : "";
  return `From ${who}${where}${at}, ${formatDated(credit.published)}${translated}`;
}
