# Arı Kaynak — Production Audit Report

Branch: `feature/production-upgrade`
Date: August 16, 2026

## 1. Files inspected

Full repository: `index.html`, `tr/index.html`, `about.html`, `tr/hakkimizda.html`, `privacy.html`, `tr/gizlilik.html`, `robots.txt`, `sitemap.xml`, `assets/style.css`, all 8 articles under `/articles/`, all 8 articles under `/tr/makaleler/`. 22 HTML files total prior to this pass.

## 2. Files changed (this session)

36 files changed, 1009 insertions, 40 deletions:
- 16 article pages (EN + TR): added `og:image`/social meta, `BreadcrumbList` JSON-LD
- 2 homepages (EN + TR): added category filter pills + `data-category` attributes, `idx-cat` labels on archive cards, social meta, removed a redundant trust-strip block (per prior request), search box redesign (prior session)
- `about.html`, `privacy.html`, `tr/hakkimizda.html`, `tr/gizlilik.html`: added full OG/Twitter card blocks (previously had none)
- `assets/style.css`: added category-pill styles

## 3. New files

- `404.html` — on-brand error page ("FILE No. 0000 / Not Found" stamp), absolute-path navigation so it resolves correctly regardless of where it's triggered from
- `assets/og/*.png` (9 files) — 1200×630 social share cards generated from the site's own design tokens (paper texture, punch-hole edge, AK mark, verdict stamp), one per case file plus a generic homepage card
- `EDITORIAL_STANDARD.md` — claim eligibility, source-selection priority, evidence hierarchy, verdict-assignment logic, uncertainty communication, corrections/AI fact-checking policy
- `CORRECTIONS.md` — how errors are reported and fixed, what counts as a logged correction vs a routine edit
- `ARTICLE_TEMPLATE.md` — reusable section-by-section template plus a pre-publish checklist for future files
- `PRODUCTION_AUDIT.md` — this document

## 4. SEO improvements

- Added `og:image`, `og:image:width/height/alt`, `og:site_name`, `og:locale`, `twitter:image` to all 22 pages (18 had none of these; 4 — about/privacy EN+TR — had no Open Graph tags at all)
- Upgraded `twitter:card` from `summary` to `summary_large_image` sitewide to match the new 1200×630 images
- Added `BreadcrumbList` JSON-LD to all 16 article pages (visible breadcrumbs already existed from a prior pass; structured-data version was missing)
- Confirmed (did not need to change): canonical URLs, hreflang reciprocity, unique titles/descriptions on every page, single `<h1>` per page — all already correct from prior audit passes

## 5. Technical fixes

- `robots.txt` / `sitemap.xml`: verified — 22 indexable URLs in the sitemap, `404.html` correctly excluded, no query-param or duplicate URLs
- Verified every `og:image`/`twitter:image` URL referenced actually resolves to a file on disk (0 missing)
- Verified all 34 JSON-LD blocks sitewide are syntactically valid JSON
- Verified 240 internal links across 23 files all resolve
- Verified HTML tag balance across all 23 files (0 mismatched/unclosed tags)

## 6. Structured-data improvements

- `Article` + `WebSite` JSON-LD: already present from a prior pass
- `BreadcrumbList` JSON-LD: added this pass, on every article page, matching the visible breadcrumb exactly

## 7. Navigation / discovery improvements

- Added a clickable category-pill filter (Exercise, Health, Longevity, Nutrition, Supplements, Women's Health / Turkish equivalents) to both homepages, combinable with the existing text search (AND logic)
- Added a visible category label to every archive card
- Existing "Related case files" cross-linking (from a prior pass) means no article is orphaned — every file is reachable from the homepage archive and linked from at least one other relevant file

## 8. Content-quality guardrails (Phase 5/18/24 instructions)

- Did not silently rewrite any existing scientific claim, citation, DOI, or PMID
- Did not invent any author, statistic, citation, or "most read" metric — no analytics data exists, so no such section was added
- Verdict language, evidence-strength ratings, and all citations from the prior session's content audit were left as-is in this pass; this session's changes were structural/technical, not content rewrites

## 9. Intentionally NOT changed

- **Article body copy** — Phase 24 explicitly says not to blindly rewrite content; nothing needed correction beyond the verdict-precision pass already completed in a prior session
- **Per-language OG images** — homepage/about/privacy share one generic card across EN/TR rather than two near-identical variants; this keeps the asset count small (9 images instead of 18) with no meaningful loss, since the card carries no language-specific text
- **A dedicated image sitemap extension** — skipped as unnecessary weight for 9 static images
- **Full WCAG contrast audit with a contrast-ratio tool** — not run in this pass; the palette is dark ink on light paper throughout, which is visually high-contrast, but no automated contrast-ratio check has been performed

## 10. Remaining recommendations (not done, for a future pass)

- A formal color-contrast audit (e.g. axe or Lighthouse) rather than visual judgment
- If the archive grows past ~30–40 files, the client-side search/filter approach (no index, DOM-only) should be revisited for performance

## 10b. Follow-up work completed (August 16, 2026, later same day)

- **Font loading**: moved Google Fonts from a render-blocking CSS `@import` to `<link rel="preconnect">` + `<link rel="preload" as="style">` + `<link rel="stylesheet">` in every page's `<head>`, so the font request starts in parallel with `style.css` instead of after it. Applied to all 23 pages.
- **Full breakpoint testing**: verified 375, 430, 768, 1024, and 1440px (320px and desktop were verified in an earlier pass) on both the homepage and an article page. Checked programmatically for horizontal overflow (`scrollWidth` vs `clientWidth`) at every breakpoint — zero overflow anywhere — plus visual review of the archive grid's column-count transitions, category pill wrapping, table rendering, and the evidence panel's single-column collapse below 640px. No layout fixes were needed; the existing responsive rules already handled every tested width correctly.

## 11. Validation performed this session

- [x] Every internal link (240/240 resolve)
- [x] Every canonical URL
- [x] Every hreflang pair (reciprocal, no dangling targets)
- [x] Every sitemap URL (22, matches indexable pages, 404 excluded)
- [x] Every JSON-LD block (34/34 valid JSON)
- [x] Every referenced OG/Twitter image exists on disk
- [x] No duplicate `<title>` or meta description across the site
- [x] Exactly one `<h1>` per page
- [x] HTML tag balance across all 23 pages

## 12. Branch / commit info

- Branch: `feature/production-upgrade`
- Not merged to `main` — awaiting explicit instruction, per this task's own workflow rules
