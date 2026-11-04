# Sparse search options for v1

Written 2026-11-04. Research only: nothing was run, installed or benchmarked. Every capability below was read from a
primary source on 2026-11-04 (URLs inline). Anything not confirmed is marked UNVERIFIED.

## 1. What the code does today
- **Index:** `record_vectors.tsv` is `to_tsvector('english', text)`, stored, with a GIN index (`0002_tables.sql`).
- **Query build:** `PgVectorIndex.bm25` (`perch/store/postgres.py`) runs `to_tsvector('english', <query>)` on the whole
  query text, joins every lexeme with `|`, and casts to a `simple` `to_tsquery`.
- **Ranking:** `ts_rank_cd(tsv, t)` with no normalisation flag, ties broken by id.
- **Why this fails for a profile:** the query is a long researcher profile, so it has hundreds of lexemes. The `@@` filter
  matches almost every record. The Postgres docs say "the ranking functions do not use any global information"
  (https://www.postgresql.org/docs/16/textsearch-controls.html, checked 2026-11-04), so a common word counts as much as a
  rare one. The top 100 is then the longest, most repetitive records, not the most specific ones. This fits the S38 result:
  keyword-only hit@10 0 and recall@200 0.042, against 0.042 hit@10 for Lance BM25 in S27 (`bench/results/s38_backtest/README.md`).
- **Not yet verified:** that missing IDF is the whole cause. The migrate-corpus self-search miss (17 of 20) is not explained
  by IDF and may point to a second issue, such as record text that differs between the old and new index. Check this first.

## 2. D-2 re-evaluated
D-2 said `pg_search` "needs a non-stock image". The current facts, all from primary sources:
- **Packaging:** ParadeDB publishes `.deb` packages for Debian 12 and 13 and Ubuntu 24.04 and 26.04, and `.rpm` for RHEL 9 and 10.
  Setup is `shared_preload_libraries = 'pg_search'` and `CREATE EXTENSION pg_search CASCADE`
  (https://www.paradedb.com/docs/deploy/self-hosted/extension, 2026-11-04). So a non-stock image is no longer the barrier.
  We still need either a custom Postgres image or an install step, which is a real but small cost.
- **Postgres 16:** the docs page says "Postgres 15+". `pg_search/Cargo.toml` defines features pg15, pg16, pg17, pg18
  (https://raw.githubusercontent.com/paradedb/paradedb/main/pg_search/Cargo.toml). The v0.26.4 release (29 Oct 2026) lists
  builds for 15, 16 and 18 (https://github.com/paradedb/paradedb/releases). Whether the Debian 12 `.deb` for PG16 exists is
  UNVERIFIED: the asset list was truncated (118 assets) and not fully read.
- **pgvector:** since 0.25.0 pg_search requires pgvector installed and `CASCADE` enables it. So they coexist in one database.
  We use pgvector 0.8, but the minimum pgvector version pg_search needs is UNVERIFIED.
- **License:** AGPL-3.0 (workspace `Cargo.toml` says `license = "AGPL-3.0"`; the repo LICENSE is the GNU AGPL v3;
  the README says "ParadeDB Community is licensed under the GNU Affero General Public License v3.0" and Enterprise is
  commercial; https://github.com/paradedb/paradedb). Implications:
  - A public repo is fine because we would not copy ParadeDB code into it. We would only install the binary and send SQL.
  - Running an unmodified AGPL server-side component behind our app generally does not make our app AGPL, because our
    code is a separate program talking over SQL. UNVERIFIED legally: this is a reading, not advice. Temple's counsel or
    open-source office should confirm before it ships.
  - Modifying pg_search and offering it over a network would trigger source-offer duties. We would not modify it.
  - Some universities restrict AGPL components. UNVERIFIED for Temple.
- **BM25 quality:** it is real BM25 with a Tantivy-based inverted index (Tantivy is also what Lance FTS used, so S27's
  0.042 keyword hit@10 is the closest proxy). The introduction page makes no benchmark claims
  (https://www.paradedb.com/docs/welcome/introduction). The exact long-query syntax (a match-disjunction operator and
  score function) was not confirmed from the docs: UNVERIFIED.
- **Maturity:** 9.5k GitHub stars, v0.26.x, so pre-1.0 and fast moving. Customer claims on the site are vendor-published.
- **Verdict on D-2:** its stated reason is out of date, but the new reasons to hesitate are AGPL, a pre-1.0 version, and
  a custom Postgres build. D-2 is still defensible; it is not a strong reason against.

## 3. Options compared
Effort is engineering hours to a working back-test number, including tests. Quality is stated as expectation, not
measurement, unless noted. Our query is a long profile for every option, which matters most for the first two.

### A. Plain Postgres fixes (tsvector stays)
**A1. Salient-term query plus `ts_rank`.**
- **Change:** build the query in code from the top K profile lexemes by `tf * idf`, with `idf` from `ts_stat` (or a
  `term_df` table made once), drop terms present in over about 5 percent of records, OR them, rank with `ts_rank` and
  normalisation flag 1 or 2. Selecting rare terms puts IDF into the choice of terms, because the ranker itself cannot.
- **Quality:** should recover a large share of the gap, but ranking is still coordination count, not BM25. UNVERIFIED until run.
- **Effort:** 3 to 4 h. **Deps:** none. **License:** PostgreSQL. **Risk:** low; `ts_rank_cd` plus flag 4 behaves differently,
  so test both.
- **Config:** try `english` vs `simple`. Stemming helps recall on grant text; `simple` keeps exact tokens. Phrases:
  `phraseto_tsquery` for the top bigrams is possible but long profiles rarely repeat phrases; skip at first.

**A2. Real BM25 in SQL from a term table.**
- **Change:** materialise `record_terms(index_name, term, record_id, tf)` from `unnest(tsv)` (tf = position count) and
  `term_df`, plus `doc_len`. Score = sum over the top-K query terms of `idf * tf*(k1+1) / (tf + k1*(1-b+b*dl/avgdl))`, grouped
  by record, with a b-tree on `(index_name, term)`.
- **Quality:** equals BM25, so close to the Lance baseline (S27: keyword hit@10 0.042, hybrid 0.208). Same ceiling as pg_search.
- **Effort:** 6 to 8 h (migration, refresh on upsert, query, tests). **Deps:** none. **License:** PostgreSQL.
- **Risk:** medium; the refresh must be kept in step with writes and with the 0003 functions and RLS grants. About 11k
  records, so latency is not a concern.
- **Variant A3:** compute the same BM25 in Python in memory (scipy sparse) at start-up. 3 h, no schema change, but a second
  copy of the corpus and a start-up cost. Not recommended for a multi-process deployment.

### B. pg_search (ParadeDB)
- **Quality:** proper BM25, expected near the Lance baseline. **Effort:** 6 to 10 h (image or install step, migration,
  index on `text`, query, tests, backup and restore check). **Deps:** pg_search `.deb`, pgvector at the matching version.
- **License:** AGPL-3.0 (section 2). **Risk:** medium to high: pre-1.0, the AGPL review, and the image change, which
  touches the deploy, backup and RLS work already built. **Back-test:** swap the `bm25` SQL behind the same interface.

### C. Other Postgres BM25 extensions
**pg_textsearch (Timescale).**
- PostgreSQL License. Supports Postgres 17 and 18 (19 beta); v1.0.0 is "first generally available" and v1.5.1 is latest
  (https://github.com/timescale/pg_textsearch, 2026-11-04). Postgres 16 is not listed, so it is out for our Postgres 16 unless
  we move to 17. The upgrade cost is UNVERIFIED (pgvector 0.8 and our image would need to be rechecked).
- Features: BM25 with tunable k1 and b, Block-Max WAND, `ORDER BY content <@> 'terms'`, tsquery boolean filters.
  Behaviour on a several-hundred-term query is UNVERIFIED. Segment IDF is computed per partition, and the README says
  corpus statistics include rows hidden by RLS. That is a concern for us because we use RLS: the statistics are global,
  the rows are not, so scores can leak counts. Records are public, so the leak is minor, but it needs a decision.
- Effort: 8 to 12 h including a Postgres 17 move. Best license of the extension group.

**VectorChord-bm25 (TensorChord).**
- Dual AGPLv3 or ELv2 (https://github.com/tensorchord/VectorChord-bm25). Image tags shown are pg17 and pg18; Postgres 16
  support UNVERIFIED. Needs two extensions (`pg_tokenizer`, `vchord_bm25`). Returns at most `bm25_limit` rows, default 100,
  which is too low for our recall@200 unless raised. 381 stars, 92 commits, so the least mature. Not recommended.

**Others.** UNVERIFIED: no other Postgres BM25 extension was surveyed beyond these three and the Postgres-native route.
(Search of the field was limited to what was reachable in this session.)

### D. Learned sparse in pgvector `sparsevec`
- **pgvector limits** (https://github.com/pgvector/pgvector, 2026-11-04): up to 16,000 non-zero elements per vector,
  8 bytes per non-zero plus 16 bytes of overhead, HNSW supported but "up to 1,000 non-zero elements" for indexed vectors,
  operators `<->`, `<#>`, `<=>`, `<+>`. IVFFlat does not list sparsevec. The README gave no maximum dimension, so a
  30,522-dimension SPLADE vocabulary is UNVERIFIED against the limit. Which release added the type is not stated on the
  page (sparsevec operators are listed under 0.7.0); we run 0.8, so it is available.
- **Models:**
  - **SPLADE-v3** (`naver/splade-v3`): licence cc-by-nc-sa-4.0 and a gated repo, BEIR-13 average nDCG@10 51.7
    (https://huggingface.co/naver/splade-v3). Non-commercial: unsuitable if Temple's deployment counts as commercial or
    the code is later reused; flag it. Max length 512 tokens.
  - **BGE-M3** (`BAAI/bge-m3`): MIT; produces dense, sparse (per-token lexical weights) and multi-vector outputs in one
    pass; max length 8192 (https://huggingface.co/BAAI/bge-m3). Published sparse-only numbers could not be read from the
    page (tables are images): quality UNVERIFIED. It would also tempt a re-embed of the corpus with a different dense model.
  - **OpenSearch neural-sparse doc-v3-gte:** Apache-2.0, 133M parameters, BEIR average nDCG@10 0.546, and the query side needs
    only a tokenizer and weight table (https://huggingface.co/opensearch-project/opensearch-neural-sparse-encoding-doc-v3-gte).
    Best licence and an inference-free query side, which suits a long profile. Whether it loads outside OpenSearch with
    plain transformers code is UNVERIFIED.
- **Fit:** learned sparse expands terms, which helps short queries. Our query is a long profile, so gains over BM25 are
  uncertain. The 1,000 non-zero HNSW limit may force truncating document vectors. Encode cost: none measured here; published
  numbers were not collected, UNVERIFIED. On one RTX 5000 Ada the corpus is only about 17k texts, so the cost is likely minutes,
  but that is a guess and must be measured.
- **Effort:** 12 to 20 h (model licence choice, encoder in `perch/llm` or a new module, migration, truncation policy, tests).
  **Risk:** high; new model dependency on the single GPU shared with embed and rerank.

### E. Drop sparse from ranking
- **Change:** `retrieve` mode `dense` then rerank the top 100; keep `tsv` for exact lookups (ids, names, award numbers).
- **Quality:** measured, not guessed. Dense-only recall@200 is 0.500 against hybrid 0.417 (S38). Dense with rerank_in 100 has not
  been run on Postgres; the hybrid+rerank number at rerank_in 100 is 0.229 hit@10 (S38), and S27 shows hybrid 0.208 vs
  keyword-only 0.042. Expect dense+rerank to be at or above hybrid+rerank, because the sparse list adds noise today.
- **Effort:** 1 to 2 h. **Deps:** none. **Risk:** low for quality here; the loss is exact-term queries such as a grant number,
  which tsvector can still serve.

## 4. Back-testing each option with `bench/backtest.py`
`--store postgres`, `--configs`, `--rerank-in` already exist. Configs are a fixed list in `main()` (lines near 309), so a new
label means one added tuple.
- **A1, A2, B, C:** change only the body of `PgVectorIndex.bm25` (or add `bm25_v2` behind a flag). Run
  `--configs keyword-only hybrid` first (no GPU rerank, cheap), then `hybrid+rerank --rerank-in 100 --strata targeted`.
  Report keyword-only hit@10 and recall@200 against the 0 and 0.042 baseline, and top-100 overlap with the old Lance BM25.
- **D:** add a `record_sparse sparsevec` column, fill it, and add a `sparse_search` method; a new config label, e.g.
  `("splade","sparse",None)`.
- **E:** add `("dense+rerank", "dense", "qwen3-reranker-0.6b")` to `configs` and run `--configs dense+rerank --rerank-in 100`.
  The rerank cache already holds many pairs from the rerank_in 100 run, so most scores are free.
Standing rule 9: report the keyword-only baseline on every row, and one award is 0.021, so differences under about 0.04 are noise.

## 5. Ranked recommendation
1. **E, dense + rerank, then A1.** Do E first as the production default. It needs one added config and few hours, and the
   measured data already show sparse hurting recall. Keep tsvector for exact lookups.
2. **A2, BM25 in SQL from a term table (or B pg_search if AGPL is cleared).** If hybrid is still wanted after E and A1, A2 gives
   real BM25 with no new dependency or license risk. pg_search gives the same quality for less code but adds AGPL, a
   pre-1.0 extension and an image change.
3. **A1 alone** as the cheap fix if E shows rerank needs a sparse candidate list.
4. **C, pg_textsearch,** only if Postgres 17 becomes acceptable; best license, no PG16 support.
5. **D, learned sparse:** highest effort, licence trouble for SPLADE-v3, unproven on long profile queries.
6. **VectorChord-bm25:** immature, 100-row default cap, PG16 UNVERIFIED.

## 6. The two cheapest experiments
**Experiment 1 (about 1 h): dense + rerank, no sparse.**
- Edit `bench/backtest.py`: in `main()` add `("dense+rerank", "dense", "qwen3-reranker-0.6b")` to the base `configs` list
  (the extra `("dense","dense",None)` is appended only in the `a.configs` branch).
- Run `--store postgres --dsn $DSN --configs dense+rerank --rerank-in 100 --strata targeted --rerank-cache bench/results/s38_backtest/rerank_cache.db`
  on the test server. Compare with hybrid+rerank 0.229 hit@10 and MRR 0.127. (Needs the reranker, so it runs on the GPU, not here.)

**Experiment 2 (about 3 to 4 h): salient-term tsvector query (A1).**
- In `PgVectorIndex.bm25` replace the `string_agg(... ' | ')` over all lexemes with:
  1. run `to_tsvector('english', %s)` and count lexeme positions to get the query tf;
  2. join to a `term_df` made once with `CREATE TABLE term_df AS SELECT word, ndoc FROM ts_stat('SELECT tsv FROM record_vectors')`;
  3. keep the top 25 lexemes by `tf * ln(N / ndoc)` and drop any with `ndoc > 0.05 * N`;
  4. rank by `ts_rank(tsv, t, 1)`.
- Run `--configs keyword-only hybrid` on targeted and parent. Success: keyword-only recall@200 well above 0.042 and hybrid
  recall@200 at or above dense-only 0.500. If keyword-only stays near 0, the cause is not IDF and the 17-of-20 self-search
  miss in `migrate-corpus` is the next thing to chase before any extension is tried.
