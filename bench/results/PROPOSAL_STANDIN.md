# Private context, measured with a stand-in (S13 task 8)

Run on 2026-10-29 by `bench/proposal.py`. CSV: `backtest_proposal_standin.csv`.

**This is an upper bound, not an estimate.** For each targeted back-test award, the funded project's own NIH RePORTER abstract (`abstract_text`, verified live) is added as a private "proposal" thread. It gets 0.6 of the weight, as private mode gives it. A real draft would be further from the award than the abstract that was funded.

| Setup | Targeted in top 10 | hit@5 | hit@10 | MRR | Retrieved in the top 200 |
|---|---|---|---|---|---|
| keyword-only (baseline) | 1 of 48 | 0.021 | 0.021 | 0.027 | 0.188 |
| keyword-only + abstract | 4 of 48 | 0.042 | 0.083 | 0.060 | 0.375 |
| hybrid + rerank (default) | 7 of 48 | 0.104 | 0.146 | 0.067 | 0.417 |
| hybrid + rerank + abstract | 16 of 48 | 0.250 | 0.333 | 0.191 | 0.625 |

- **Paired comparison, default setup:** with the abstract, 24 awards ranked higher, 6 lower and 18 the same. The MRR difference is 0.124. Its 95% paired bootstrap interval is [0.042, 0.218] (2,000 resamples, seed 7), so it does not contain 0.
- **What it supports:** the mechanism can move the right announcement up when the added text is close to the work being funded.
- **What it does not support:** a gain from a real, unfinished draft. That was not measured, and no such data is available.
- **A small difference from the S8 table:** this run gives the default MRR 0.067 (S8 0.066) and keyword-only 0.027 (S8 0.017), with the same 48 awards and the same top-10 counts. The cause was not checked; the stand-in comparison uses this run's own baseline rows.
- **Coverage:** all 48 targeted awards had an abstract. Parent announcements were not run.
