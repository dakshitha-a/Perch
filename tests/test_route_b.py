"""Route B scoring rules. All records here are SYNTHETIC."""

from datetime import UTC, date, datetime

from perch import route_b as rb
from perch.schemas import Award, Organisation, Topic, Work
from perch.service import _temple

T = datetime(2026, 10, 29, tzinfo=UTC)
AS_OF = date(2026, 10, 29)
ME = "https://openalex.org/A1"
TOPIC = Topic(id="https://openalex.org/T1", display_name="SYNTHETIC topic")
MINE = [Work(id=f"https://openalex.org/W{i}", source="openalex", source_url="u", fetched_at=T,
             title=f"SYNTHETIC paper {i}", author_ids=[ME], topics=[TOPIC]) for i in (1, 2)]
TOPICS = rb.main_topics(MINE)


def org(n: str, name: str) -> Organisation:
    return Organisation(id=f"https://openalex.org/I{n}", source="openalex",
                        source_url=f"https://api.openalex.org/institutions/I{n}", fetched_at=T,
                        name=name, type="company", aliases=[name],
                        institution_ids=[f"https://openalex.org/I{n}"])


def work(n: int, cites=(), authors=("https://openalex.org/A9",), d=date(2026, 1, 5), year=2026):
    return Work(id=f"https://openalex.org/W{n}", source="openalex", source_url="u",
                fetched_at=T, title=f"SYNTHETIC company work {n}", publication_date=d,
                publication_year=year, author_ids=list(authors), topics=[TOPIC],
                referenced_works=list(cites))


def award(n: int, firm: str, start=date(2025, 4, 1), fy=2025):
    return Award(id=f"nih:{n}", source="nih_reporter",
                 source_url=f"https://reporter.nih.gov/project-details/{n}", fetched_at=T,
                 agency="NCI", award_number=f"R43CA{n}", title="SYNTHETIC SBIR project",
                 institution=firm, start_date=start, fiscal_year=fy, activity_code="R43")


ACME = org("10", "Acme Therapeutics (United States)")
ACME_UK = org("11", "Acme Therapeutics (United Kingdom)")


def score(citing=(), topical=(), sbir=()):
    return rb.score_leads(ME, MINE, list(citing), list(topical), list(sbir), TOPICS, AS_OF)


def test_norm_name_strips_country_punctuation_and_legal_form_only():
    assert rb.norm_name("BLACKSMITH MEDICINES, INC.") == "blacksmith medicines"
    assert rb.norm_name("AstraZeneca (United Kingdom)") == "astrazeneca"
    assert rb.norm_name("Acme Bio") != rb.norm_name("Acme Biosciences")


def test_one_signal_is_not_a_lead():
    assert score(citing=[(work(5, cites=[MINE[0].id]), [ACME])]) == []


def test_a_citing_work_never_counts_as_a_topic_work_too():
    w = work(5, cites=[MINE[0].id])
    assert score(citing=[(w, [ACME])], topical=[(w, [ACME])]) == []


def test_two_kinds_of_record_make_a_lead_with_label_and_relationship():
    leads = score(citing=[(work(5, cites=[MINE[0].id, MINE[1].id]), [ACME])],
                  topical=[(work(6, d=date(2025, 3, 2)), [ACME_UK])])
    assert len(leads) == 1
    x = leads[0]
    assert x.org.aliases == ["Acme Therapeutics (United States)",
                             "Acme Therapeutics (United Kingdom)"]
    assert [s.kind for s in x.signals] == ["citing_works", "topic_works"]
    assert x.relationship == "Sponsored research or collaboration"
    assert x.confidence == "moderate"
    assert x.cited_works == [MINE[0].id, MINE[1].id]
    assert x.org.name == "Acme Therapeutics"  # two national entities merged
    assert x.sentences[0] == ("1 work with an author at Acme Therapeutics cites 2 of your "
                              "papers; the newest was published 5 Jan 2026.")


def test_the_researchers_own_papers_are_not_citing_signals():
    own = work(5, cites=[MINE[0].id], authors=[ME, "https://openalex.org/A9"])
    assert score(citing=[(own, [ACME])], topical=[(work(6), [ACME])]) == []


def test_sbir_firm_joins_by_exact_normalised_name_only():
    citing = [(work(5, cites=[MINE[0].id]), [ACME])]
    leads = score(citing=citing, sbir=[award(1, "ACME THERAPEUTICS, INC.")])
    assert len(leads) == 1 and leads[0].relationship == "STTR or SBIR partner"
    assert leads[0].org.id == ACME.id
    assert score(citing=citing, sbir=[award(1, "ACME THERAPEUTICS GROUP")]) == []


def test_sbir_projects_count_once_and_three_signals_read_stronger():
    leads = score(citing=[(work(5, cites=[MINE[0].id]), [ACME])],
                  topical=[(work(6), [ACME])],
                  sbir=[award(1, "Acme Therapeutics Inc", fy=2024),
                        award(2, "Acme Therapeutics Inc", fy=2025).model_copy(
                            update={"award_number": "R43CA1"})])
    s = {x.kind: x for x in leads[0].signals}
    assert s["sbir_sttr"].count == 1 and s["sbir_sttr"].record_ids == ["nih:2"]
    assert leads[0].confidence == "stronger"


def test_dates_without_a_day_are_never_shown():
    leads = score(citing=[(work(5, cites=[MINE[0].id], d=None, year=2025), [ACME])],
                  sbir=[award(1, "Acme Therapeutics", start=None)])
    assert all(s.latest is None for s in leads[0].signals)
    assert leads[0].sentences[0] == ("1 work with an author at Acme Therapeutics (United States) "
                                     "cites 1 of your papers.")


def test_older_evidence_scores_lower():
    new = score(citing=[(work(5, cites=[MINE[0].id]), [ACME])], topical=[(work(6), [ACME])])
    old = score(citing=[(work(5, cites=[MINE[0].id], d=date(2016, 1, 5)), [ACME])],
                topical=[(work(6, d=date(2016, 1, 5)), [ACME])])
    assert old[0].score < new[0].score


def test_award_linking_ignores_non_temple_records():
    assert _temple(award(1, "TEMPLE UNIV OF THE COMMONWEALTH"))
    assert not _temple(award(1, "ACME THERAPEUTICS, INC."))


class _FakeOA:
    def __init__(self):
        self.cited = None

    def company_works_citing(self, ids):
        self.cited = ids
        return []

    def company_works_in_topics(self, topics, since, until):
        return []


class _FakeNIH:
    def sbir_sttr(self, text, years):
        return []


def test_consortium_papers_do_not_seed_route_b():
    big = MINE[0].model_copy(update={"id": "https://openalex.org/W99",
                                     "author_ids": [f"https://openalex.org/A{i}" for i in
                                                    range(rb.MAX_AUTHORS + 1)]})
    oa = _FakeOA()
    g = rb.gather(oa, _FakeNIH(), [*MINE, big], AS_OF)
    assert set(oa.cited) == {MINE[0].id, MINE[1].id}
    assert big not in g.seeds


def test_a_copy_of_the_researchers_own_paper_is_never_evidence():
    # a list response cut the researcher from the author list of their own paper
    cut = work(1, cites=[MINE[1].id])
    assert score(citing=[(cut, [ACME])], topical=[(work(6), [ACME])]) == []
    big = work(50)  # their consortium paper: not a seed, still theirs
    leads = rb.score_leads(ME, MINE, [(work(5, cites=[MINE[0].id]), [ACME])],
                           [(big, [ACME])], [], TOPICS, AS_OF, own={big.id})
    assert leads == []


def test_a_company_joins_its_openalex_parent_only_when_the_parent_is_there():
    """U13: OpenAlex lists Samsung (South Korea) in the lineage of Samsung Electronics
    (South Korea) (checked live, 31 Oct 2026). Records of the child count under the parent,
    by that link, not by name; a parent missing from the records merges nothing."""
    parent = org("20", "Parentco (Testland)")
    child = org("21", "Parentco Devices (Testland)").model_copy(
        update={"lineage": [parent.id, "https://openalex.org/I21"]})
    leads = score(citing=[(work(5, cites=[MINE[0].id]), [child])],
                  topical=[(work(6), [parent])])
    assert len(leads) == 1
    x = leads[0]
    assert x.org.name == "Parentco" and x.org.id == parent.id
    assert set(x.org.aliases) == {"Parentco (Testland)", "Parentco Devices (Testland)"}
    assert score(citing=[(work(5, cites=[MINE[0].id]), [child])]) == []  # one signal, no merge
    other = org("22", "Parentco Devices (Testland)")  # no lineage: stays its own company
    assert len(score(citing=[(work(5, cites=[MINE[0].id]), [other])],
                     topical=[(work(6), [parent])])) == 0


def test_the_hand_off_lists_industry_signals_in_the_researchers_own_voice():
    """R12: the email, in the researcher's voice, said "18 works ... cite 2 of your papers";
    to the office "your" means the office's papers. The screen and export keep "your"."""
    from datetime import UTC, date, datetime

    from perch.route_b import sentence
    from perch.schemas import Lead, Organisation, Signal
    from perch.skills.handoff import lead_lines

    t = datetime(2026, 10, 29, tzinfo=UTC)
    sigs = [Signal(kind="citing_works", record_ids=["W1"], count=18, latest=date(2026, 1, 2)),
            Signal(kind="topic_works", record_ids=["W2"], count=3, latest=date(2025, 5, 6))]
    org = Organisation(id="https://openalex.org/I1", source="openalex", source_url="u",
                       fetched_at=t, name="SYNTHETIC Co", type="company")
    lead = Lead(id="b:B1", source="openalex", source_url="u", fetched_at=t, brief_id="b",
                route="B", record_id=org.id, rank=1, cited_ids=["W7", "W8"], signals=sigs,
                explanation=" ".join(sentence(s, org.name, 2) for s in sigs))
    line = lead_lines([(lead, org)])[0]
    assert "cite 2 of my papers" in line and "one of my main topics" in line
    assert "your" not in line
    assert "cite 2 of your papers" in lead.explanation  # the screen and export say "your"
