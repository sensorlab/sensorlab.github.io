# SensorLab website

## Project overview

This is the Hugo static site source for **SensorLab** (Jožef Stefan Institute), published to `sensorlab.github.io` / `sensorlab.ijs.si`. There is no custom Hugo theme submodule — layouts, styles, and scripts live directly in this repo (`layouts/`, `assets/`).

## General Guidelines

- Commit messages: lowercase, imperative subject line, prefixed with the area when it fits (`update:`, `chore:`, `todo:`, `fix:`, `refactor:`, `feat:`, `content:`, `docs:`).
- NEVER add AI attribution: no agent co-author trailers and no "Generated with ..." lines, in commit messages or PR descriptions.
- When making technical decisions, do not give much weight to development cost. Prefer quality, simplicity, robustness, and long-term maintainability.

## Commands

### Native development
- `npm install` — install NodeJS dependencies (Bootstrap, PostCSS/Babel toolchain)
- `npm start` — run Hugo dev server (`hugo server -v --gc --disableFastRender --buildDrafts --buildFuture`)
- `npm run prod` — production build (`hugo -v --gc --minify`), output to `public/`
- `npm run cobiss` — refresh `data/publications.json` from COBISS/arXiv (see below)
- `npm run highlight` — regenerate `assets/styles/_highlight.scss` from Hugo's Chroma syntax highlighter

Requires Hugo **extended** edition (see `Dockerfile`/CI for pinned version, currently 0.154.5) and Node 22+.

### Container-based development (recommended, per README)
- `make up` / `make dev` — run Hugo dev server inside a Docker container (build via `make container` first if needed)
- `make shell` — drop into a shell inside the container
- `make build` — full production build (`clean` → `cobiss` → `public` → `clean`) inside container, output in `public/`
- `make deploy` — build into `public.tmp/` then `rsync` into `public/` (used for local staged deploys)
- `make clean` — remove `node_modules`, `resources`, `hugo_stats.json`, `.hugo_build.lock`, `public.tmp`

### Python data pipeline (COBISS/arXiv parser)
- `pip install -r requirements.txt` then `python3 scripts/cobiss_parser.py`
- Useful flags: `--skip-cobiss` / `--skip-arxiv` (reload from `data/cobiss.debug.json` / `data/arxiv.debug.json` instead of hitting the network), `-e/--exclude <cobiss_ids>`, `-o/--output <dir>`, `-v`/`-vv` for verbosity
- Lint with `ruff` (config in `ruff.toml`, line length 119, target py312)

### CI/CD
`.github/workflows/*.yml` runs on push to `main`, on PRs, and on a daily cron. It installs Python + Node + Hugo, runs `scripts/cobiss_parser.py` to refresh publication data, builds with `hugo --gc --minify --environment production`, and deploys `public/` to GitHub Pages. There are no automated tests — the closest thing to CI validation is a successful Hugo build.

## Architecture

### Content model (Hugo content types under `content/`)
- `content/people/<username>/index.md` — one directory per lab member (past & present). See **People profiles** below for the full schema and how to add someone.
- `content/projects/<PROJECT-NAME>/index.md` — one directory per funded project. See **Project pages** below for the full schema and how to add one.
- `content/publications/` — publication list page; actual publication *data* comes from `data/publications.json`, not markdown files (see pipeline below), and is rendered via the `{{< publicationlist ids="..." >}}` shortcode (`layouts/shortcodes/publicationlist.html`) which matches on COBISS ID, arXiv ID, or DOI.
- `content/opportunities/`, `content/about/`, `content/results/`, numbered files like `content/00-anomaly-detection.md` … `content/11-agentic-ai.md` — research-area/results pages surfaced on the homepage.
- New content should be scaffolded from `archetypes/*.md` (`default.md`, `post.md`, `people.md`, `projects.md`) via `hugo new`, per the workflow documented in README.md. **Archetype filenames must match the section name exactly** (plural `projects.md` for the plural `content/projects/` section) — Hugo's archetype lookup is section-name-based, and a mismatch fails silently (falls back to `default.md`) rather than erroring. This bit `archetypes/project.md` for a long time before being caught and fixed.

### People profiles (`content/people/<username>/index.md`)
Each person is a Hugo leaf bundle: a directory (username convention: first-name initial + surname, lowercase, no diacritics, e.g. `gcerar`, `mmohorcic`) containing `index.md` plus that person's photo file side by side — the photo must live in the same directory (not `static/`), referenced by filename via the `avatar` front-matter key as a Hugo page resource. If `avatar` doesn't resolve to a real file, templates fall back to `assets/images/unk.png`.

**To add a new person:** `hugo new content/people/<username>/index.md`, which scaffolds from `archetypes/people.md`. That archetype uses descriptive placeholders (`title: "Firstname Lastname"`, `role: "e.g. PhD Student, Postdoc, Research Fellow"`) rather than blanks, so it's obvious what to fill in. Then drop their photo into the new directory and point `avatar` at its filename.

Fields actually read by the templates (`layouts/people/{list,member,single,alumni}.html`):
- `title` — the *only* display-name field (there's no separate `name` or `prefix` — both were removed as dead/unused). For a nickname or preferred form, embed it in quotes within `title` itself, e.g. `Mihael "Miha" Mohorčič`.
- `avatar`, `position` (manual sort order for the Members grid — higher sorts first, `sort ... "desc"`), `role`, `organizations`, `interests` — rendered as-is.
- `cobiss` — SICRIS researcher ID. Empty/absent excludes the person from `scripts/cobiss_parser.py`'s roster entirely. Leave it genuinely empty rather than a placeholder — it's fed directly into live COBISS/arXiv API calls, unlike the cosmetic fields above.
- `date_start`/`date_end` — informational "Joined"/"Departed" dates on the profile page. Section placement (Members vs. Alumni) is controlled by `user_groups`, not `date_end`.
- `user_groups` — a list; including `alumni` moves someone from the "Members" grid to the "Alumni" list on `/people/` (see `layouts/people/list.html`). `researchers` is the default active-member group.
- `social` — a list of `{text, link}` pairs rendered as a comma-separated links line (e.g. `text: Scholar`, `link: https://...`) — plain text labels, not icon classes, despite what older revisions of this archetype used to show. Only a handful of profiles currently have this filled in.

### Project pages (`content/projects/<PROJECT-NAME>/index.md`)
Each funded project is a Hugo leaf bundle, one directory per project (naming convention: the project's acronym/short name as it appears publicly, e.g. `NANCY`, `6G-OPTICON`).

**To add a new project:** `hugo new content/projects/<PROJECT-NAME>/index.md`, which scaffolds from `archetypes/projects.md`.

Fields read by `layouts/projects/{list,single}.html`:
- `title`, `summary`, `tags`, `date_start`/`date_end` (shown as "Duration:") — rendered as-is.
- `featured_image` — thumbnail/banner image, resolved as a page resource next to `index.md` first, then as a global asset by that filename; the list page additionally falls back to `assets/images/project-default.png` if neither exists (the single page does not).
- `project_url` — rendered as a "Website:" link when set (22 of 26 current projects have this; wasn't actually rendered anywhere until this was noticed and fixed).
- `grant_code`, `budget` — optional, each shown as its own line only when set.
- Body content is free-form Markdown. Use the `{{< figure2 src="..." >}}` shortcode to embed an image from the project's own directory, and `{{< publicationlist ids="...">}}` to link related publications by COBISS/arXiv/DOI id — see `archetypes/projects.md` for working examples of both. There's no equivalent mechanism yet to back-reference `content/results/*.md` entries from a project page.

### Publication data pipeline (`scripts/cobiss_parser.py`)
This is the one piece of "real" logic in the repo, distinct from the templating. The whole script is asyncio-based:
1. Scans `content/people/**/index.md` for `cobiss` IDs to build the researcher roster (`get_members`).
2. Fetches each researcher's bibliography from COBISS/SICRIS as XML (`get_bib_in_xml`, `get_cobiss_data`) and separately queries arXiv by author name (`get_arxiv_data`) — the two branches run concurrently via `asyncio.gather(..., return_exceptions=True)` in `_fetch_sources()`, so one branch failing can't cancel or discard the other's already-completed work.
3. Merges the two sources **by DOI only** (`merge_sources`) — there is no title-matching. A COBISS entry and an arXiv preprint merge only if their DOIs match exactly (case/whitespace-normalized); otherwise the arXiv entry is kept as its own standalone `"preprint"`-coded publication. COBISS fields win on merge; only `arxiv_url`/`arxiv_id` get attached.
4. Applies `valid_sensorlab_paper()` — an authorship-based heuristic — to flag which merged entries count as official SensorLab publications (`is_sensorlab`), handling a special-cased "target member" edge case (`_TARGET_COBISS_IDS`) and a `DEFAULT_EXCLUDE_LIST` of COBISS IDs to always skip.
5. Writes `data/publications.json` (production, consumed by Hugo via `.Site.Data.publications`) plus `data/cobiss.debug.json` / `data/arxiv.debug.json` (raw per-source snapshots, reusable via `--skip-cobiss`/`--skip-arxiv` to avoid re-hitting rate-limited network APIs during iteration).

**Concurrency model — don't "optimize" this without reading it first.** COBISS researcher fetches run concurrently over `httpx.AsyncClient`, bounded by `asyncio.Semaphore(COBISS_CONCURRENCY)` — a self-imposed politeness limit, since this is still an unofficial scraping endpoint, not a documented/rate-limited API. arXiv's per-researcher loop is **intentionally sequential**: arXiv's terms of use ask for no more than one request every 3 seconds, enforced by `arxiv.Client`'s own internal pacing, which isn't safe under concurrent calls into the same client — parallelizing it would trigger more HTTP 429s, not fewer. Both branches share one retry helper, `with_backoff()` (exponential, capped); COBISS's HTML meta-refresh "please wait" polling is a separate, expected-wait code path and is deliberately *not* routed through it.

When modifying this script, note that COBISS ID matching across sources is the crux of correctness (`author_cobiss_id`/`is_employee` flags, `_TARGET_COBISS_IDS` special case) — most bugs will look like a paper appearing/missing from the public list or being mis-attributed as a SensorLab paper.

### Frontend build (assets → resources → public)
- `layouts/_default/baseof.html` is the single base template all pages extend; it pipes `assets/styles/app.scss` through Hugo Pipes (`toCSS` → `postCSS` → `minify` → `fingerprint`) and `assets/scripts/app.js` through `babel` → `js.Build` → `minify` → `fingerprint`. Toggle `params.inlineCSS` in `hugo.toml` to inline vs. link the compiled CSS.
- `postcss.config.js` only runs `postcss-import` + `postcss-preset-env` in dev; PurgeCSS (driven by `hugo_stats.json`, Hugo's structured record of classes/tags/ids actually used) and `cssnano` are added only when `HUGO_ENVIRONMENT=production`, so purging behavior can't be observed from a plain dev server run.
- `layouts/partials/` holds shared fragments (navbar, footer, SEO/meta tags, pagination, publication list item, i18n language list); `layouts/shortcodes/` holds content-callable shortcodes (`publicationlist`, `figure2`, `rawhtml`).
- Section-specific list/single templates live under `layouts/<section>/` (`people/`, `projects/`, `publications/`, `opportunities/`, `results/`), overriding `layouts/_default/list.html` / `single.html` per Hugo's template lookup order.
- i18n strings are in `i18n/en.toml` and `i18n/sl.toml`; the site is bilingual (English default, Slovenian second) per `hugo.toml`'s `[languages]` block.
- `[security]` in `hugo.toml` explicitly allowlists external-exec binaries (`dart-sass-embedded`, `go`, `babel`, `npx`, `postcss`) and `HUGO_`-prefixed env vars — required for Hugo Pipes' Babel/PostCSS integration to run at all.

### Generated/output directories — do not hand-edit
- `public/` — final built site (Hugo output, mirrors `content/` + rendered assets); regenerate via `hugo`/`npm run prod`, never edit directly.
- `resources/`, `hugo_stats.json`, `.hugo_build.lock` — Hugo's build cache/state; safe to delete (`make clean` does this).
- `data/cobiss.debug.json`, `data/arxiv.debug.json`, `data/publications.json` — generated by `scripts/cobiss_parser.py`; treat as build artifacts, not hand-maintained data.
