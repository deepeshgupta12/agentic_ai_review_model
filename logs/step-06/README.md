# Step 06 test plan and logs

Step 06 turns what is said in project videos into timed, project-linked evidence, in the original language with an English translation alongside ([step spec](../../steps/06-video-and-language-processing.md)). It adds:

- the spoken-content policy (v2, applying D33);
- the transcript routes: captions first, else local speech-to-text;
- transcript windows on the original timeline;
- speech evidence and project matching;
- language flags;
- A04 translations with backend checks;
- the media library API;
- a separate media worker;
- a synthetic speech set for measuring the transcription path.

**Live status:**

- **Blocked:** live acquisition of captions and audio. From the demo machine's network, youtube.com is unreachable (TLS reset, I17); the YouTube Data API still works. Every attempt so far ended metadata-only with the reason `network_refused`, which is the designed outcome for a refusal.
- **Proven:**
  - the whole path with fakes;
  - the real Whisper model inside the media worker container, on the synthetic speech set;
  - the real A04 model on the same sentences.

The spec says live media analysis is not complete until a permitted real sample has been processed. That gate stays open until YouTube is reachable.

Run the commands from the repository root with the stack up (`make up`). In zsh, run `setopt interactivecomments` once if you paste commands that contain `#` comments.

## Run everything

```bash
git pull
make up
bash scripts/run_step06_checks.sh
bash scripts/run_step06_mutations.sh
```

The first build of the media worker image takes several minutes (about 2.3 GB). The first speech check downloads the Whisper model, about 1.6 GB.

The check script covers:

- the Steps 01–05 regression;
- the backend and web gates;
- the media worker's role, memory cap and kill priority;
- setup and seeding;
- the spoken-content policy;
- the media library API;
- the speech check with the real Whisper model;
- the A04 translation check (one Claude call);
- a bounded live attempt on five real project videos;
- the stored-data rules;
- hygiene.

It ends with `ALL CHECKS OK`.

The mutation script disables sixteen media rules one at a time; each must be caught by its own test.

## Try it yourself

```bash
make eval-language
make eval-media
make transcribe
make verify-collection
```

- `eval-language` sends the five non-English sentences to A04 once and shows what the backend keeps.
- `eval-media` transcribes the eight synthetic clips with the configured Whisper model; it takes several minutes on the CPU.
- `transcribe` queues up to 50 accepted project videos (one attempt per video per day) and waits for the media worker. While I17 is open, each ends metadata-only with `network_refused`.

## Use cases

| ID | Use case | What it proves | Tests |
|---|---|---|---|
| UC-41 | Windows on the original timeline | Cues group into windows of about 30 s without moving or changing a word. Long pauses close a window, and overlapping captions are clipped, so windows never overlap. A timestamp jump lands in the window holding those words | 3 |
| UC-42 | Language and flags | Tags: Devanagari Hindi `hi`, Latin-letter Hindi `hi-Latn`, English `en`. Flags: code-switching, music and low confidence. Numbers in machine-made text (auto captions or speech-to-text), including Hindi number words, are flagged for a person; human-made captions are trusted | 2 |
| UC-43 | Routes and access states | Captions come first and become segments with caption timing. Without captions, audio is transcribed locally and then deleted. A refusal is recorded and not worked around, with no spoken evidence. A long video without captions is not downloaded. Temporary failures retry, end in `error`, and can start again. Every change follows the `media_access` machine and is audited | 6 |
| UC-44 | Speech evidence and matching | A window that names no project inherits the video's match; a window naming another project gets its own and inherits nothing. Speech evidence carries a time anchor and the spoken-content policy. Undoing the video's match returns inherited windows to review. Withdrawing the video erases its transcript but keeps the timing | 3 |
| UC-45 | Which videos, which worker, the library | Only videos with an accepted match are queued, once per day. The general worker never takes media jobs. Duration alone does not make a Short. The media library lists each video with its state and ordered segments (contract) and refuses unknown filters. The collection checks accept transcripts and catch broken ones | 5 |
| UC-46 | A04 translation | A translation is kept only when every number and every negation survives; others are rejected, audited and left for a person. IDs the model invents are ignored, and every call is recorded. English windows are not sent. Hindi negation markers respect Devanagari word edges ("कीमत" is not "मत") | 3 |

Backend total: 258 tests (236 from Steps 03–05 plus 22 new), run against the Compose MongoDB replica set without real credentials.

## Measured on the synthetic speech set (`evals/media/v1`)

Eight sentences written for this check, spoken by macOS voices: Lekha (Hindi) and Rishi (Indian English), including romanized Hinglish. The text is the ground truth. These are upper bounds: real videos have accents, music and noise. Real samples are measured at Step 12, once YouTube is reachable.

**Whisper:**

| Model | Where | Key facts kept | Hindi word error | English word error | Speed |
|---|---|---|---|---|---|
| small | native (M1) | 13/22 | 35% | 4% | — |
| large-v3-turbo | native (M1) | 19/22 | 27% | 7% | about 1–2× real time |
| large-v3-turbo | media worker (Docker, 2 GB) | 20/22 | 34% | 7% | about 3–11× real time |

**A04:** 5 of 5 translations kept by the backend, with all 12 English facts kept: prices in crore, dates, areas and both negations. The first live check found the "कीमत" false negation, since fixed.

Hindi number words are where Whisper errs ("पच्छाहेतर" for पचहत्तर). That is why machine-made numbers are always flagged.

## Recorded results

| Date (UTC) | Commit | Run by | Command | Result | Log |
|---|---|---|---|---|---|
| 2026-10-01 07:50–08:20 | worktree, before commit | Implementer | Whisper `small` and `large-v3-turbo` natively on the speech set | small 13/22 facts; turbo 19/22 at about 1–2× real time; turbo chosen | (console; numbers in the table above) |
| 2026-10-01 08:23 | worktree | Implementer | turbo inside a 3 GB test container | **Incident.** The 4 GB Docker VM ran out of memory and MongoDB was killed (exit 137, OOMKilled). Restarted with no data lost; the API and worker reconnected. Led to the D48 safeguards | (PROGRESS session entry) |
| 2026-10-01 08:30 | worktree | Implementer | turbo inside the media worker image, 2 GB cap | 20/22 facts at about 3–11× real time; MongoDB untouched | (console) |
| 2026-10-01 08:55 | worktree | Implementer | live A04 on the five non-English sentences | 4/5 kept: the backend wrongly read "कीमत" as a negation (fixed); after the fix 5/5 kept, 12/12 facts | (console) |
| 2026-10-01 09:12 | worktree | Implementer | `bash scripts/run_step06_mutations.sh` | 14/16. One weak test (window overlap at a boundary, strengthened) and one mutant whose text didn't match the file (fixed) | [log](mutation-check-20261001T091209Z.log) |
| 2026-10-01 09:31 | `fb5ce62` (before commit) | Implementer | `bash scripts/run_step06_mutations.sh` | ALL MUTANTS CAUGHT, 16/16; 258 backend tests | [log](mutation-check-20261001T093120Z.log) |
| 2026-10-01 09:53 | `fb5ce62` | Implementer | `bash scripts/run_step06_checks.sh` | 22/23. The seeding check wrongly required "unchanged" on the first pass after the upgrade, which correctly created spoken_video_content v2 and youtube v3 (script fixed). Speech set 20/22; A04 5/5 and 12/12; live attempt: 137 eligible videos, 5 tried, all `network_refused` (I17); verify-collection 16/16 | [log](checks-20261001T095344Z.log) |

## Step 06 acceptance checks

- [x] A video without an authorised transcript remains visible but yields no spoken-content finding. UC-43: the refusal path records no speech evidence. Live: refused videos stay metadata-only and are listed in the media library.
- [x] Duration alone does not determine Shorts format (UC-45; `format` stays `unknown` with basis `unknown`).
- [x] Timestamp jumps resolve the correct original segment within documented precision (UC-41). Precision: approximate, within the roughly 30-second window.
- [x] Hindi/English/Hinglish numerical and negation errors are measured and flagged. Measured above: Whisper's Hindi number words are the weak point, and A04 kept every number and negation. Flagged by UC-42 and UC-46.
- [x] Comments, descriptions, spoken content and frame observations remain distinguishable. Comments are separate sources (Step 05). Descriptions are metadata, never evidence. Speech evidence has modality `speech`. No frames are extracted (D49).
- [x] Relevant repository checks were actually run and their results recorded (above).
- [x] PROGRESS.md records changed paths, decisions, evidence, unresolved dependencies and the next action.
- [ ] Live media analysis on a permitted real sample. **Blocked by I17:** youtube.com is unreachable from the demo network.
- [ ] The product owner approves items Z1–Z3.

## Approvals (Z1–Z3), for the product owner

| Item | Decision | Where |
|---|---|---|
| Z1 | Transcripts: <ul><li>only videos with an accepted project match;</li><li>captions first, else local transcription for videos up to 10 minutes;</li><li>refusals recorded and never worked around;</li><li>audio deleted after each job;</li><li>windows of about 30 seconds as segments and evidence;</li><li>windows that name no project inherit the video's match;</li><li>machine-made numbers always flagged;</li><li>A04 translations kept only when numbers and negations survive;</li><li>spoken_video_content v2 and youtube v3 apply D33</li></ul> | D47 |
| Z2 | Whisper `large-v3-turbo` by default. It is better at Hindi than `small`, but slow in Docker (a 60-second short takes about 2–11 minutes). It runs in a separate media worker capped at 2 GB, which the kernel kills before MongoDB. Docker's VM here has 4 GB, shared with your other stacks. **Your choice:** keep turbo (quality), switch to `small` (speed), or give Docker more memory | D48 |
| Z3 | No frames or on-screen text in Release 1.0 | D49 |

**Also needed from you (I17):** can the media worker run on a network where youtube.com is reachable? If your office network blocks YouTube, that's your organisation's decision; nothing here will try to get around it.

## Known limits

- **Live gate:** captions and audio can't be fetched while I17 is open. Discovery (the Data API) and everything after acquisition are built and tested.
- **Speed:** transcription in Docker runs at several times real time on this machine. Captions, when available, take seconds.
- **Precision:** a claim's time is known to within its window (about 30 seconds), not to the exact word.
- **Speakers** are not identified; speech is attributed to the video (A03 is not used in Step 06).
- **Frames and on-screen text** are not extracted (D49).
