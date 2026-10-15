/** Line icons for the console (24px grid, stroke drawn in the current text colour). Decorative: every place that shows
 * one also says the thing in words. */

const PATHS = {
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
    </>
  ),
  play: (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="4" />
      <path d="m10 9 5 3-5 3z" />
    </>
  ),
  chat: <path d="M20 11.5a8 8 0 0 1-11.7 7.1L4 20l1.3-4A8 8 0 1 1 20 11.5z" />,
  camera: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <path d="M17.5 6.5h.01" />
    </>
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </>
  ),
  landmark: <path d="M3 21h18M4 10h16M12 3 4 7v3h16V7zM6 10v8M10 10v8M14 10v8M18 10v8" />,
  radio: (
    <>
      <circle cx="12" cy="12" r="2" />
      <path d="M16.2 7.8a6 6 0 0 1 0 8.4M7.8 16.2a6 6 0 0 1 0-8.4M19.1 4.9a10 10 0 0 1 0 14.2M4.9 19.1a10 10 0 0 1 0-14.2" />
    </>
  ),
  page: (
    <>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5M9 13h6M9 17h4" />
    </>
  ),
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6 6 18" />,
  pin: (
    <>
      <path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </>
  ),
  external: <path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </>
  ),
  coins: (
    <>
      <ellipse cx="9" cy="7" rx="6" ry="3" />
      <path d="M3 7v5c0 1.7 2.7 3 6 3s6-1.3 6-3V7M3 12v5c0 1.7 2.7 3 6 3 1.3 0 2.5-.2 3.5-.5M15 12.5c3.3 0 6 1.3 6 3s-2.7 3-6 3-6-1.3-6-3" />
    </>
  ),
  layers: (
    <>
      <path d="m12 3 9 5-9 5-9-5z" />
      <path d="m3 13 9 5 9-5" />
    </>
  ),
  inbox: (
    <>
      <path d="M3 13h5l1.5 3h5L16 13h5" />
      <path d="M5.5 5h13L21 13v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5z" />
    </>
  ),
  quote: <path d="M7 7h4v4c0 3-1.5 5-4 6M15 7h4v4c0 3-1.5 5-4 6" />,
  stop: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5h.01" />
    </>
  ),
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18" />,
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name, className = "h-4 w-4", strokeWidth = 1.8 }: { name: IconName; className?: string; strokeWidth?: number }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={`shrink-0 ${className}`}
    >
      {PATHS[name]}
    </svg>
  );
}

/** Each source's icon and colour, so a list of sources reads at a glance (the name is always beside it). */
const SOURCES: Record<string, { icon: IconName; tint: string }> = {
  brave_search: { icon: "search", tint: "bg-orange-50 text-orange-600 ring-orange-200" },
  web_fetch: { icon: "globe", tint: "bg-teal-50 text-teal-700 ring-teal-200" },
  firecrawl_search: { icon: "search", tint: "bg-amber-50 text-amber-700 ring-amber-200" },
  firecrawl: { icon: "page", tint: "bg-amber-50 text-amber-700 ring-amber-200" },
  playwright_fetch: { icon: "page", tint: "bg-slate-50 text-slate-600 ring-slate-200" },
  youtube_data_api: { icon: "play", tint: "bg-red-50 text-red-600 ring-red-200" },
  reddit_public: { icon: "chat", tint: "bg-orange-50 text-orange-700 ring-orange-200" },
  reddit_api: { icon: "chat", tint: "bg-orange-50 text-orange-700 ring-orange-200" },
  instagram_public: { icon: "camera", tint: "bg-pink-50 text-pink-600 ring-pink-200" },
  meta_graph_api: { icon: "camera", tint: "bg-blue-50 text-blue-600 ring-blue-200" },
  spoken_video_transcripts: { icon: "mic", tint: "bg-violet-50 text-violet-600 ring-violet-200" },
  harera_registry: { icon: "landmark", tint: "bg-slate-50 text-slate-600 ring-slate-200" },
  state_registry: { icon: "landmark", tint: "bg-slate-50 text-slate-600 ring-slate-200" },
  listening_provider: { icon: "radio", tint: "bg-sky-50 text-sky-600 ring-sky-200" },
  x_api: { icon: "x", tint: "bg-zinc-50 text-zinc-700 ring-zinc-200" },
};

export function SourceIcon({ connectorId, size = "md" }: { connectorId: string; size?: "sm" | "md" }) {
  const source = SOURCES[connectorId] ?? { icon: "layers" as IconName, tint: "bg-slate-50 text-slate-600 ring-slate-200" };
  const box = size === "sm" ? "h-6 w-6 rounded-md" : "h-9 w-9 rounded-lg";
  return (
    <span aria-hidden="true" className={`inline-flex items-center justify-center ring-1 ring-inset ${box} ${source.tint}`}>
      <Icon name={source.icon} className={size === "sm" ? "h-3.5 w-3.5" : "h-[18px] w-[18px]"} />
    </span>
  );
}
