# S46 student brief on the real model (SYNTHETIC personas, counts only)

Cloud-gpu profile, real Anthropic provider, e2e Postgres, GPU 3. counts.csv is the second run.
Two runs were made (the second added the MiniCheck split by sentence kind).

| persona | eligible leads explained | shown | withheld (failed twice) | MiniCheck-unsupported (shown) | calls | usd |
|---|---|---|---|---|---|---|
| persona-ug | 20 | 20 | 0 | 16 (opp 11, finding 16) | 20 | 0.114 |
| persona-masters | 20 | 20 | 0 | 20 (opp 7, finding 20) | 20 | 0.106 |
| persona-phd | 20 | 19 | 1 (opp_sentence_not_one) | 9 (opp 7, finding 4) | 22 | 0.120 |

Total spend: run 1 $0.3424, run 2 $0.3405 (about $0.68, cap was $1.00 per run).
Finding: on the real model the citation checks almost never withhold (1 of 60). The walk's
"withheld twice" is a fake-model artefact. What is common is Layer 2 (MiniCheck) marking
statements unsupported while the card is still shown.
