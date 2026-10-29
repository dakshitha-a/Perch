# Temple STTR partners, S12 task 7 (2026-10-29)

Judged by Perch-dev (Claude Opus 5.5), not by Dakshitha. Source: SBIR.gov's bulk award file, rows whose research institution names Temple University (`data/sbir/temple_sttr_partners.csv`, made by `scripts/sbir_temple.py`).

## The table

- 41 STTR awards to 25 companies.
- Agencies: HHS 13, DoD 11, NASA 8, DOE 8, NSF 1.
- 8 rows have no award date in the file.

## Matches to each researcher's three main topics (title words, `perch/sttr.py`)

| PI | Company | Award title (start) | Judgment | Why |
|---|---|---|---|---|
| PI-1 (A5063022331) | Recombination Therapeutics LLC | Nucleotide inhibitors as precision medicine in breast cancer | yes | DNA repair precision medicine, PI-1's main area. A second award to the same company, on recombination-deficient cancers, was missed because its title shares no topic word. |
| PI-2 (A5057472361) | Onconova Therapeutics | Identification of Small Pharmacologic Inhibitors of HIV-1 Replication (FY 2007) | thin | HIV is PI-2's main topic, but the award is from 2007 and is about drug screening. |
| PI-3 (A5023080104) | — | — | — | No match. |
| PI-4 (A5026494099) | Intelligent Fusion Technology | High-performance computing for multiple-target tracking | thin | Shares only high-performance computing with PI-4's work. |

## Does it add leads?

- A Route B lead needs two kinds of signal.
- None of the three matched companies appears among the companies in the live signals: 360 for PI-1, 510 for PI-2 and 571 for PI-4.
- So, as a signal, the table adds 0 leads.
- Following the task's gate, it is not wired into Route B. The table and the matcher stay in the repo. Q20 asks whether a past Temple STTR partner in the researcher's topics should count as a lead on its own.
