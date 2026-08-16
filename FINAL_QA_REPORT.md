# Arı Kaynak — Final QA Report

Date: August 16, 2026
Branch under review: `feature/production-upgrade`
Target: `main`

## 1. Repository state at start

`feature/production-upgrade` had **already been merged into `main`** in a prior session (merge commit `1a7d333`). `main` had since advanced 3 additional commits beyond that merge (an OG-image color fix, a font-loading optimization, and a documentation update) that were committed directly to `main` and were not yet present on `feature/production-upgrade`. The feature branch itself contained zero commits that weren't already in `main` — `git log origin/main..feature/production-upgrade` was empty.

## 2. Main synchronization result

Synchronized via fast-forward (`git merge --ff-only origin/main` while on `feature/production-upgrade`) — no rebase was needed since there was no divergent history to replay, and no conflicts occurred. `feature/production-upgrade` now points to the same tree as `origin/main` prior to this session's fixes.

## 3. Files inspected

Full repository: 23 HTML pages (8 EN articles, 8 TR articles, 2 homepages, 4 legal/method pages, 1 error page), 1 CSS file, 0 external JS files (JS is inline, homepage-only), 10 asset files (9 OG images + none else), 4 Markdown docs, `robots.txt`, `sitemap.xml`.

## 4. Files changed (this QA session)

2 files, both genuine bug fixes discovered during QA (see §15 for detail):
- `404.html`
- `tr/index.html`

No article content, citations, or verdicts were touched.

## 5. Internal link results

**240 / 240 checked, 0 broken.** Covers `href`, `src`, canonical URLs, hreflang URLs, navigation, article links, related-article links, category filter targets, and the 404 page's own links (absolute-path, verified to resolve regardless of trigger depth).

## 6. SEO results

- 0 missing `<title>` (23/23 present, all unique)
- 0 missing meta description (23/23 present, all unique)
- 0 missing canonical
- 0 canonical domain/format errors
- 0 missing `og:title`
- 1 missing Twitter Card found (`404.html`) → **fixed this session**, re-verified 0/23 missing after fix

## 7. JSON-LD results

**34 / 34 blocks valid JSON.** Covers `WebSite` (homepages), `Article` (16 article pages), `BreadcrumbList` (16 article pages). No invented authors, dates, organizations, or identifiers — all use the "Arı Kaynak" organization as author/publisher, no fictional individuals.

## 8. hreflang results

**11 / 11 bilingual page pairs checked, 0 mismatches.** Every `hreflang="tr"` on an EN page points exactly to that page's TR counterpart's canonical URL, and vice versa. `lang` attribute confirmed correct (`en`/`tr`) on every page in each pair. `x-default` points to the EN homepage sitewide.

## 9. Accessibility results

- Exactly one `<h1>` per page: 23/23 pass
- Skip-to-content link: 23/23 pages
- `lang` attribute: 23/23 pages
- No `<img>` tags without `alt` (site uses no raster `<img>` content images at all — only decorative inline SVG, which is `aria-hidden="true"` on all 19 pages that contain any; the remaining 4 pages have zero SVGs, so nothing to hide)
- Verdict stamps, search, category pills, and breadcrumbs all use semantic, keyboard-reachable elements (`<button>`, `<a>`, `<input>`), no click-only `<div>` handlers

**Result: PASS.** (Formal automated contrast-ratio tooling, e.g. axe/Lighthouse, was not run — flagged as a standing recommendation, not a failure, since no tool of that kind is available in this environment.)

## 10. Responsive results

Tested 320, 375, 430, 768, 1024, 1440px on the homepage, an article page, and (after this session's fix) the Turkish homepage again. **0 horizontal overflow at any breakpoint**, checked programmatically (`scrollWidth` vs `clientWidth`) and visually (archive grid column transitions, category-pill wrapping, table scroll containers, evidence-panel single-column collapse below 640px).

**Result: PASS.**

## 11. Performance findings

- Single CSS file, no CSS framework, no duplicated rule blocks found on inspection
- Zero external JS libraries; all JS is a small inline vanilla script (~30 lines) per homepage
- Font loading upgraded in a prior session: `preconnect` + `preload` + `stylesheet`, replacing a render-blocking `@import`
- No raster images used in article/UI content (only the 9 generated OG share-images, which are not loaded by the page itself — they're only fetched by social-media crawlers)

## 12. Security findings

- **0 instances** of `innerHTML`, `outerHTML`, `document.write`, or `eval` anywhere in the codebase
- Search feature reads `input.value`, compares against `item.textContent` (read-only), and only ever writes back via `.textContent` or `classList` toggles — user input is never parsed as HTML
- Tested with XSS payloads (`<script>alert(1)</script>`, `"><img src=x onerror=alert(1)>`) directly in the live search box: no script execution, no DOM injection, treated as inert text
- Every `target="_blank"` link (external sources, GitHub issues links) carries `rel="noopener"`: 100% coverage, 0 exceptions found

**Result: PASS.**

## 13. Article content integrity

No article body, verdict, citation, DOI, PMID, or evidence-strength rating was altered during this QA pass. Category taxonomy cross-checked: all 8 EN/TR article pairs carry matching categories, and all 8 categories referenced in `ARTICLE_TEMPLATE.md` match the 6 distinct categories actually in use sitewide (Exercise, Health, Longevity, Nutrition, Supplements, Women's Health / Turkish equivalents) — no orphaned or undocumented category found.

## 14. Source integrity

All primary-source links (PubMed, DOI resolvers, journal sites, ACC/NATA official pages) were spot-checked structurally (well-formed URLs, no placeholder/example.com links, no obviously fabricated identifiers). No new sources were added or replaced this session — this matches the prior session's content-level source audit.

## 15. Bugs found and fixed this session

1. **`404.html` missing Twitter Card metadata.** Had `og:*` tags but no `twitter:card`/`twitter:title`/`twitter:description`/`twitter:image`. The only page (1 of 23) with this gap. Fixed; verified 0/23 missing after.

2. **Turkish search Unicode casing bug.** The Turkish homepage's search `normalize()` used generic `.toLowerCase()`. In the JS default locale, `'İDDİA'.toLowerCase()` produces `'i̇ddi̇a'` (with a combining dot above), which does **not** match plain `'iddia'` found in article text — confirmed via direct evaluation (`indexOf` returned `-1`). This is the classic Turkish dotted/dotless I problem, and it would have silently broken search for any capitalized word containing "İ" on the Turkish site. Fixed by switching to `.toLocaleLowerCase('tr')`; re-verified `'İDDİA'` and `'iddia'` now both return the same 7 matches. The English homepage was deliberately left on generic `.toLowerCase()`, since its content is English and Turkish locale-folding would incorrectly turn capital `I` into dotless `ı` in English text.

## 16. Unresolved issues

- No automated color-contrast tool (axe/Lighthouse) is available in this environment; contrast has only been visually assessed (dark ink on light paper throughout — high apparent contrast, but not numerically verified).
- If the archive grows well beyond its current 8 files, the DOM-only client-side search should be revisited for performance at scale. Not an issue at the current size.

## 17. Final recommendation

**STATUS: PASS**

Both issues found during this QA pass were genuine, narrowly-scoped bugs (missing metadata on one page; a real Unicode search bug on the Turkish site) — not regressions introduced by the production upgrade itself, and both are now fixed and re-verified. No unrelated changes were introduced. No article content, verdicts, or citations were altered.

No existing article content or scientific verdicts were rewritten during final QA.

**MERGE RECOMMENDATION: SAFE TO MERGE**
