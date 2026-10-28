# SOURCES

One entry per data source. Nothing goes here from memory; every line comes from a live request made in this repo.

| Source | Endpoint(s) used | Key fields | Rate limit / terms observed | Fixture | Verified on | Notes / limitations |
|---|---|---|---|---|---|---|
| OpenAlex | `GET /authors?search=<name>&filter=last_known_institutions.id:I84392919&per-page=3` (resolve by name at Temple); `GET /authors/orcid:<orcid>` (resolve by ORCID); `GET /authors/<A-id>`; `GET /works?filter=author.id:<A-id>&sort=publication_date:desc&per-page=100&cursor=*` (works, cursor paging via `meta.next_cursor`). Temple = `https://openalex.org/I84392919`, from `GET /institutions?search=Temple University`. | Author: `id`, `display_name`, `orcid`, `last_known_institutions[].display_name`, `works_count`, `cited_by_count`, `topics[]`. Work: `id`, `title`, `publication_year`, `publication_date`, `doi`, `type`, `primary_location.source.display_name` (venue), `abstract_inverted_index` (rebuilt to text), `authorships[].author.id`, `authorships[].institutions[].id`, `topics[]` (id, display_name, score), `referenced_works`, `cited_by_count`. | Budget in USD per day, reported in `X-RateLimit-*` headers and `meta.cost_usd`. Observed: list + filter 1 credit ($0.0001), search 10 credits ($0.001), single-record lookups free. No key: one shared $0.10/day per IP (`X-RateLimit-Limit: 1000` credits). Free key: $1/day, sent as `Authorization: Bearer` (`OPENALEX_API_KEY`). Data licence CC0 (help.openalex.org/access/pricing). The old mailto polite pool is not mentioned in the current docs; not used. | `tests/fixtures/openalex/authors_search.json`, `author_orcid.json`, `works_page.json` (public Temple researcher, OpenAlex A5026494099) | 2026-10-28 | `works_count` on the author (45) differs from the `author.id` works filter count (35); Perch uses the filter. Works also carry `awards` and `funders` fields, not yet used (candidate for S2). Name search returns only authors whose *last known* institution is Temple, so researchers who moved away are missed. Client retries 429 and 5xx with `Retry-After`, and spaces requests by 0.1 s (self-imposed). |
| NIH RePORTER v2 | | | | | | |
| NSF Award Search | | | | | | |
| Grants.gov | | | | | | |
| NIH Guide archive | | | | | | |
| SBIR.gov | | | | | | |
