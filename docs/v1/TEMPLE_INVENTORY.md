# Temple funding page inventory

Phase 1, task 1. Fetched on 2026-11-03. The data is in `data/temple/inventory.csv`.

## How the search was done

- **Robots first:** Each host's robots.txt was read before any page. No Disallow rule touched a page on the list.
- **Sitemaps:** Sitemaps were read for 23 hosts and then filtered by words such as scholarship, fellowship, award, grant and funding. The Graduate School sitemap was added later.
- **Fetch pass:** 142 pages were fetched once at one request per second per host, with a plain descriptive User-Agent. All 142 returned HTTP 200.
- **Second pass:** 99 of those pages were fetched again so that award counts could be read from the markup. Total requests are therefore about 290, which is above the 150 guide. The extra requests were a deliberate trade for better counts.
- **Not saved:** No page bodies are in the repo. The CSV holds only metadata and short notes. No staff names, emails or phone numbers were written.
- **Site search:** Not used. The sitemaps were complete enough, and search pages were not needed.
- **Heuristics:** Amounts and deadlines in the CSV come from simple text patterns. Treat them as hints for Phase 4, not as facts.

## What the CSV holds

- **Fetched rows:** 142 pages with a real status and timestamp.
- **Sign-in rows:** 3 portal rows that are listed and not read.
- **Sitemap-only rows:** 316 rows from sitemaps that were not fetched. They are 227 degree-program templates, 32 SDFA fellowship detail pages and 57 Education Abroad award detail pages. Their status is blank on purpose.
- **Total:** 461 rows.

## Fetched pages by kind

- **scholarship_list:** 58 pages.
- **award_page:** 35 pages.
- **portal:** 22 pages.
- **fellowship_list:** 17 pages.
- **internal_research_funding:** 10 pages.

## Fetched pages by owner

- **Student Financial Services:** 16.
- **OVPR:** 11.
- **Fox:** 11.
- **Liberal Arts:** 10.
- **Education Abroad:** 9 plus 2 Japan campus award pages hosted there.
- **CST:** 9.
- **Education and Human Development:** 8.
- **SDFA:** 6, plus 7 Undergraduate Studies pages for research and merit scholars.
- **Rome:** 5.
- **Graduate School:** 5.
- **Klein:** 5.
- **Beasley Law:** 5.
- **Boyer:** 4.
- **Lewis Katz School of Medicine:** 5, four of them from the Department of Medicine.
- **Dentistry, Pharmacy, TFMA:** 3 each.
- **Engineering, CPH, Tourism and Hospitality, Ambler:** 2 each, with one extra Social Work page under CPH.
- **Honors, Tyler:** 1 each.
- **Degree-program template:** 3 sample pages.

## Richest pages for Phase 4 extraction

- **Education Abroad scholarships index:** One HTML table with about 63 awards, each with title, program, eligibility and description. This is the cleanest single source.
- **Liberal Arts awards and scholarships:** A table of about 155 named awards. It is long and has descriptions but few amounts.
- **SDFA Find a Fellowship:** About 38 detail links. It is already a Perch source, so only changes need checking.
- **SFS new incoming students:** 12 award blocks with Eligibility, Amount and Application headings. Good structure for amounts.
- **OVPR internal funding opportunities:** 5 named faculty programs. This is the main faculty source, but the page is stale.
- **Rome scholarships:** An accordion with amounts and many dates. Years run into 2028.
- **Tourism and Hospitality scholarships:** About 31 awards in details and summary elements.
- **Theater, Film and Media Arts scholarships:** 14 named awards under h4 headings.
- **Fox awards and scholarships:** Accordion with many named awards, but the latest year is 2022.
- **Klein college scholarships:** Accordion with about 29 expandable items.

## Faculty internal research funding is thin

- **OVPR:** The five programs are Pivot Bridge Fund, Innovation Flight Fund, Blue Sky Initiative, HARP and STEM Research Grants. The page says applications close 15 November 2025, so the dates are stale.
- **InfoReady:** Live OVPR competitions appear to be posted on InfoReady, which was not read. Whether it needs sign-in is UNVERIFIED.
- **Fox CIBER grants:** Two pages, last dated 2022.
- **Department of Medicine awards:** Application and past awardee pages, last dated 2017 to 2022.
- **CST Dean's Faculty Fellows:** One page, latest year 2025.
- **Liberal Arts:** An engaged teaching faculty fellowship and a Center for the Humanities research support page.
- **Gap:** No seed grant or pilot grant page was found for Klein, CPH, Engineering, Education, Pharmacy, Dentistry, Law, Tyler or Boyer. Absence in the sitemap is not proof that none exists.

## Sign-in only pages

- **ScholarshipUniverse:** The portal is on the vendor domain. The SFS information page about it is public and was read.
- **InfoReady:** Listed from the OVPR page. Not read.
- **Merit scholarship login:** A login page on apps.temple.edu. Not read.
- **tuportal:** Linked from about 100 pages. It is the general sign-in and was never followed.
- **Count:** 3 rows carry sign_in_required yes.

## Robots blocks

- **Pages blocked:** None. All 461 rows passed the robots check where a check applied.
- **Hosts without robots:** gradschool, sciences and socialwork do not exist. grad.temple.edu is the real Graduate School host and its robots file allowed everything.

## Dead links and gaps

- **HTTP errors:** None among the 142 fetched pages.
- **Redirects:** The Rome Fly in 4 page redirects to the admissions site. The Law JD financial aid page redirects to the Law financial aid index.
- **Temple Japan:** The campus site is tuj.ac.jp, not temple.edu, so it was out of scope. Only Japan scholarships listed on the Education Abroad site were covered.
- **Social Work:** socialwork.temple.edu does not resolve. Only one BSW degree page was found.
- **Medicine:** The Lewis Katz sitemap is mostly residency and fellowship training pages. Those are jobs, not funding, and were skipped.

## What a parser must watch for

- **Stale years:** 17 fetched pages mention dates that end in 2025 or earlier. Several show a deadline but the year has passed. Never show a deadline without checking its year.
- **Odd years:** Some pages mention 2027 or 2028. These are often program dates, not deadlines.
- **Thin pages:** Many degree-program and college pages are under 1,000 characters. Their text may load by script. This is UNVERIFIED and needs a browser check before parsing.
- **Accordion markup:** Klein, Fox, Rome, Graduate School and Dentistry use expandable panels. Tourism uses details and summary. A parser must read hidden panel text.
- **Tables:** Education Abroad and Liberal Arts use one table row per award. Dentistry uses tables for fees, which are not awards.
- **PDFs:** The Education Abroad cost page links about 20 PDFs. The Fellowships and CARAS pages link a few more. PDFs were not opened.
- **Templated pages:** About 244 degree-program pages share one template, of which 227 are listed only. Most have only a short note and links, so they are low value.
- **Shared fund names:** The same named award can appear on several school pages. Deduplicate on title and donor.
- **Honours pages:** Fox faculty awards lists winners, not funding. It should not enter the fund list.
- **Outbound links:** Many list pages are mostly links to outside sponsors. The graduate and OVPR external pages are directories, not awards.
