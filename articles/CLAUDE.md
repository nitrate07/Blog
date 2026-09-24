# site — static bilingual fact-checking pages

Static HTML/CSS, no build step, no JS framework. This spoke covers the whole site component: root pages (`index.html`,
`about.html`, `privacy.html`, `ask.html`, `404.html`), `articles/` (41 EN case files), `tr/` (TR homepage, pages and
`tr/makaleler/`, 41 TR case files) and `assets/` (`style.css`, images). Hosted on GitHub Pages.

## Key Files
- `articles/*.html` / `tr/makaleler/*.html` — EN/TR case-file pairs; structure per `ARTICLE_TEMPLATE.md`.
- `index.html`, `tr/index.html` — homepages with the article index.
- `ask.html`, `tr/ask.html` — "Soruşturucu" chat UI; calls the Render API (`window.ARI_API_BASE`).
- `sitemap.xml`, `robots.txt`, `llms.txt`, `llms-full.txt`, `claims.json` — discovery / machine-readable indexes.

## Architecture Notes
- Verdict and body text of a published case file are editorial content: never edit unless explicitly asked
  (`EDITORIAL_STANDARD.md`, `CORRECTIONS.md`).
- EN and TR versions are pairs: hreflang, sitemap and index entries change together.
- Pages under `tr/` use `../assets/...` paths (root-relative mistakes left a page unstyled before).

## Build
- None — edit HTML directly. No version constant; changes ship via merged PRs.

For domain logic: see `.salvor/DOMAIN_REF.md`. For infra/ops: see `.salvor/INFRA.md`.
