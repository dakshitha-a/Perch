# Route B hand check, S11 (2026-10-29)

Judged by Perch-dev (Claude Opus 5.5) against the records each lead cites, not by Dakshitha. Dakshitha should spot-check before this number is used in the deck. Outputs: `A5063022331.txt` (PI-1), `A5057472361.txt` (PI-2), `A5023080104.txt` (PI-3), all with `as_of` 2026-10-29.

## Criteria, fixed before looking

- **yes:** the organisation is a company, its signals are real records, and the cited papers are the researcher's own substantive work in an area the company works on.
- **thin:** a real company with real signals, but the link to the researcher's work is indirect or rests on one record.
- **wrong:** the lead rests on papers that say little about the researcher, such as 100-author consortium papers, or the organisation is not a company.

## Result

| Run | yes | thin | wrong | Leads |
|---|---|---|---|---|
| First run (no author cap) | 7 | 3 | 5 | 15 |
| After the author cap (papers with more than 30 authors do not seed Route B) | 8 | 6 | 0 | 14 |

The cap was chosen after seeing the first run, on the same three researchers. So the second row is not an independent measure.

## Per lead, after the cap

| PI | Company | Signals | Judgment | Why |
|---|---|---|---|---|
| PI-1 | Artios Pharma | citing, topic | yes | Polθ inhibitor company; cites seven of PI-1's Polθ and RAD52 papers. |
| PI-1 | AstraZeneca | citing, topic | yes | PARP and ATR inhibitor work; cites PI-1's Polθ and PARG papers. |
| PI-1 | Pharmaron | citing, topic | thin | Contract research company; cites two Polθ inhibitor papers in its own chemistry work. |
| PI-1 | Boehringer Ingelheim | citing, topic | yes | SOS1 with BCR-ABL inhibitors in leukemia; cites PI-1's BCR-ABL and RAD52 papers. |
| PI-1 | Novartis | citing, topic | yes | Chronic myeloid leukemia drugs; one citing review, many CML topic works. |
| PI-2 | Acuitas Therapeutics | citing, topic | yes | Lipid nanoparticles; cites PI-2's brain-targeted nanocarrier papers. |
| PI-2 | F. Hoffmann-La Roche | citing, topic | yes | A CB2 receptor agonist paper cites PI-2's CB2 and blood-brain barrier work. |
| PI-2 | BioNTech | citing, topic | yes | RNA lipid nanoparticles; cites PI-2's nanocarrier papers. |
| PI-2 | BGI Group | citing, topic | thin | Cites an old blood-brain barrier review; genomics services company. |
| PI-2 | Regeneron | citing, topic | thin | Cites older HIV brain papers through one THC and SIV study. |
| PI-3 | Innovation Research and Training | SBIR/STTR, topic | yes | NIH SBIR health-education company; topic work on teaching adolescents about clinical trials. |
| PI-3 | Leidos Biomedical Research | citing, topic | thin | A GTEx tissue-quality paper cites PI-3's consent paper; government contractor. |
| PI-3 | AbbVie | citing, topic | thin | One citing work; one topic work on consent forms. |
| PI-3 | Abbott | citing, topic | thin | Cites PI-3's nutrition-literacy review from 2021. |

## First run, PI-3 (before the cap)

deCODE Genetics, Regeneron, Genentech, Pfizer and Illumina: all **wrong**. Every cited paper was a GTEx consortium paper with 96 to 100 listed authors.

## Other observations

- Signal 2 (NIH SBIR/STTR) joined an OpenAlex company in 1 of 14 leads. Large companies do not take SBIR awards, and small SBIR firms rarely publish under an OpenAlex company record.
- Every lead had the citing or SBIR signal plus the topic signal. No lead had all three, so every confidence label is "moderate".
