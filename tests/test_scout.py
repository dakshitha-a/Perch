"""Scout's loop, offline: fake models, fixture-backed store, every rule the plan names."""

import json
from datetime import date

import pytest

from perch.llm import ToolCall
from perch.llm.fake import FakeProvider
from perch.llm.ollama import OllamaProvider
from perch.privacy import PrivateSettings
from perch.scout.log import ScoutLog, replay
from perch.scout.loop import Scout, ScoutBudget, cited, scrub, stated_numbers
from perch.scout.tools import TOOLS, ScoutContext, check_arguments

from .test_api import make

AUTHOR = "https://openalex.org/A5026494099"
OPP = "grants_gov:PAR-25-268"  # closes 2026-11-17, no award ceiling in the record
AS_OF = date(2026, 10, 28)


@pytest.fixture
def service(tmp_path):
    c, service = make(tmp_path)
    c.post("/briefs", json={"author_id": "A5026494099", "as_of": "2026-10-28",
                            "explain": False})  # fetches the researcher and works
    return service


def ctx(service):
    return ScoutContext(service, AS_OF, researcher_id=AUTHOR)


def call(name, **args):
    return [ToolCall(f"c-{name}", name, args)]


def test_run_mode_calls_tools_answers_with_citations_and_replays(service, tmp_path):
    log = ScoutLog(tmp_path / "scout.jsonl")
    fake = FakeProvider([call("search_opportunities", route="A", max_amount=500000),
                         f"PAR-25-268 closes 2026-11-17 [{OPP}]. Its record gives no award "
                         f"ceiling [{OPP}]."])
    s = Scout(fake, ctx(service), mode="run", log=log).start("R01s under $500k?")
    assert s.status == "done" and not s.flagged, s.errors
    assert s.cited_ids == [OPP] and s.cards[0].status == "done"
    assert s.cards[0].result["leads"][0]["id"] == OPP
    # the second model call saw the tool result
    assert fake.calls[1]["messages"][-1].tool_results[0].name == "search_opportunities"
    events = [json.loads(x) for x in (tmp_path / "scout.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in events] == ["session", "question", "tool", "answer"]
    tool = events[2]
    assert tool["arguments"] == {"route": "A", "max_amount": 500000}
    assert len(tool["args_hash"]) == 16 and len(tool["result_hash"]) == 16
    assert "R01s" not in (tmp_path / "scout.jsonl").read_text()  # questions as hashes only
    rows = replay(log, s.id, lambda r, a: ScoutContext(service, date.fromisoformat(a), r))
    assert rows == [{"turn": 1, "tool": "search_opportunities", "logged": "done",
                     "match": True}]


def test_ask_mode_waits_for_approval_and_skip_is_reported_to_the_model(service):
    fake = FakeProvider([call("list_awards"), call("get_record", id=OPP),
                         f"It closes 2026-11-17 [{OPP}]."])
    scout = Scout(fake, ctx(service), mode="ask")
    s = scout.start("When does it close?")
    assert s.status == "awaiting_approval" and [c.tool for c in s.pending()] == ["list_awards"]
    assert len(fake.calls) == 1  # nothing ran before approval
    s = scout.skip(s)
    assert s.cards[0].status == "skipped" and s.status == "awaiting_approval"
    assert "skipped" in fake.calls[1]["messages"][-1].tool_results[0].content
    s = scout.approve(s)
    assert s.cards[1].status == "done" and s.status == "done" and s.answer


def test_follow_up_reuses_the_session(service):
    fake = FakeProvider([call("get_record", id=OPP), f"It closes 2026-11-17 [{OPP}].",
                         "It is an R01 [grants_gov:PAR-25-268]."])
    scout = Scout(fake, ctx(service), mode="run")
    s = scout.start("When does PAR-25-268 close?")
    s = scout.ask(s, "What activity code?")
    assert s.status == "done" and s.answer.startswith("It is an R01")
    assert len(fake.calls[2]["messages"]) == 5  # q, call, result, answer, follow-up


def test_unknown_tool_and_bad_arguments_are_refused_not_run(service):
    fake = FakeProvider([call("send_email", to="x"), call("get_record"),
                         "I cannot send email; Perch only drafts."])
    s = Scout(fake, ctx(service), mode="run").start("Email the program officer")
    assert [c.status for c in s.cards] == ["refused", "refused"]
    assert "not an allowed tool" in s.cards[0].detail and "missing 'id'" in s.cards[1].detail
    assert s.status == "done" and s.answer


def test_invented_numbers_are_rewritten_once_then_withheld(service):
    bad = f"It closes 2031-01-01 and pays $2,000,000 [{OPP}]."
    s = Scout(FakeProvider([call("get_record", id=OPP), bad, bad]), ctx(service),
              mode="run").start("When?")
    assert s.flagged and s.answer is None and s.status == "done"
    assert any("2031-01-01" in e for e in s.errors)
    good = f"It closes 2026-11-17 [{OPP}]."
    s = Scout(FakeProvider([call("get_record", id=OPP), bad, good]), ctx(service),
              mode="run").start("When?")
    assert not s.flagged and s.answer == good
    # an id the tools never returned is not a citation
    s = Scout(FakeProvider(["See [grants_gov:PA-99-999].", "See [grants_gov:PA-99-999]."]),
              ctx(service), mode="run").start("Anything?")
    assert s.flagged and "was not in the input" in s.errors[0]


def test_numbers_the_user_typed_may_be_repeated():
    assert {"200", "200000"} <= stated_numbers("under $200k")
    assert scrub(f"Under $200,000, closes 2026-11-17 [{OPP}]", {"200000"}).split() == [
        "Under", "closes", "2026-11-17"]
    assert cited("a [W1, W2] b [grants_gov:PA-1]") == ["W1", "W2", "grants_gov:PA-1"]
    # the user's date does not cut up a record's date; list markers are formatting
    allowed = stated_numbers("R21s closing by 2027-03-01?")
    assert "2027-03-01" in allowed and "2027" not in allowed
    assert scrub("1. closes 2027-01-07\n2. by 2027-03-01", allowed).split() == [
        "closes", "2027-01-07", "by"]


def test_budget_stops_the_loop(service):
    fake = FakeProvider(responder=lambda m, s, sc: call("get_record", id=OPP))
    s = Scout(fake, ctx(service), mode="run", budget=ScoutBudget(max_turns=3)).start("loop")
    assert s.status == "stopped" and "3 model turns" in s.errors[0] and len(fake.calls) == 3


def test_structured_fallback_for_models_without_tool_calling(service):
    step = {"action": "call", "tool": "get_record", "arguments": {"id": OPP}, "answer": ""}
    done = {"action": "answer", "tool": "none", "arguments": {},
            "answer": f"It closes 2026-11-17 [{OPP}]."}
    fake = FakeProvider([json.dumps(step), json.dumps(done)])
    s = Scout(fake, ctx(service), mode="run", policy="structured").start("When?")
    assert s.policy == "structured" and s.status == "done" and not s.flagged, s.errors
    assert fake.calls[0]["schema"]["properties"]["tool"]["enum"][-1] == "none"
    assert "get_record" in fake.calls[0]["system"]  # the catalogue is in the prompt
    assert fake.calls[1]["messages"][-1].content.startswith("Result of get_record:")
    s = Scout(FakeProvider(["not json"]), ctx(service), policy="structured").start("x")
    assert s.status == "failed"


def test_compare_and_draft_handoff_use_records_and_send_nothing(service):
    from perch.scout.tools import ToolError

    c = ctx(service)
    with pytest.raises(ToolError, match="no kept leads"):
        TOOLS["compare"][1](c)
    out = TOOLS["compare"][1](c, ids=[OPP])
    row = out["rows"][0]
    assert row["record"] == OPP and row["Closes"].startswith("2026-11-17")
    assert row["Money"] == "Not in the record" and row["Office"] == "Research Development"
    d = TOOLS["draft_handoff"][1](c, ids=["PAR-25-268"])
    assert d["office"] == "Research Development" and d["to"] == ""
    assert "PAR-25-268" in d["body"] and "closes 2026-11-17" in d["body"]
    assert d["opening_withheld"] is True  # the fake model gives nothing usable
    with pytest.raises(ToolError, match="none of these leads"):
        TOOLS["draft_handoff"][1](c, office="technology_commercialization", ids=[OPP])


def _brief_with_route_b(service):
    """The fixture brief plus one SYNTHETIC Route B lead."""
    from datetime import UTC, datetime

    from perch.schemas import Brief, Lead, Organisation, Signal, Work

    t = datetime(2026, 10, 29, tzinfo=UTC)
    with service.repo() as r:
        # A brief of its own, with Route B finished, so test order cannot hand Scout a
        # brief whose Route B is still to run (that made this flaky under random order).
        base = max(r.list(Brief), key=lambda x: x.created_at)
        b = base.model_copy(update={
            "id": f"{base.id}-rb", "lead_ids": list(base.lead_ids),
            "stages": [s.model_copy(update={"status": "done"}) if s.name == "route_b" else s
                       for s in base.stages]})
        org = Organisation(id="https://openalex.org/I1", source="openalex",
                           source_url="https://api.openalex.org/institutions/I1", fetched_at=t,
                           name="SYNTHETIC Co", type="company", aliases=["SYNTHETIC Co"])
        w = Work(id="https://openalex.org/W77", source="openalex", source_url="u",
                 fetched_at=t, title="SYNTHETIC company paper", publication_date=date(2026, 1, 2))
        lead = Lead(id=f"{b.id}:B1", source="openalex", source_url=org.source_url, fetched_at=t,
                    brief_id=b.id, route="B", record_id=org.id, rank=1, inferred=True,
                    relationship="Sponsored research or collaboration", confidence="moderate",
                    explanation=("4 works with an author at SYNTHETIC Co cite 2 of your papers; "
                                 "the newest was published 2026-01-02."),
                    inference="Inferred from public signals; not verified.",
                    signals=[Signal(kind="citing_works", record_ids=[w.id], count=4,
                                    latest=date(2026, 1, 2))])
        r.upsert([org, w, lead, b.model_copy(update={"lead_ids": [*b.lead_ids, lead.id]})])
    c = ctx(service)
    c.brief_id = b.id
    return c, lead


def test_route_b_tools_return_the_briefs_industry_leads(service):
    c, lead = _brief_with_route_b(service)
    out = TOOLS["get_org_signals"][1](c)
    x = out["leads"][0]
    assert out["label"].startswith("Inferred") and x["lead"] == lead.id
    assert x["organisation"] == "SYNTHETIC Co" and x["organisation_id"] == "I1"
    assert x["signals"][0]["records"] == ["W77"] and x["signals"][0]["count"] == 4
    assert TOOLS["get_org_signals"][1](c, organisation="nobody")["leads"] == []
    b = TOOLS["search_opportunities"][1](c, route="B")
    assert b["leads"][0]["lead"] == lead.id and "do not apply to route B" in b["note"]


def test_route_b_answer_counts_and_dates_pass_the_validator(service):
    c, lead = _brief_with_route_b(service)
    fake = FakeProvider([call("get_org_signals"),
                         f"SYNTHETIC Co is an inferred lead: 4 of its works cite 2 of your "
                         f"papers, the newest published 2026-01-02 [{lead.id}]. This is not "
                         f"verified [{lead.id}]."])
    s = Scout(fake, c, mode="run").start("Which companies might fund this?")
    assert s.status == "done" and not s.flagged, s.errors
    bad = FakeProvider([call("get_org_signals"),
                        f"SYNTHETIC Co: 9 works cite your papers [{lead.id}].",
                        f"SYNTHETIC Co: 9 works cite your papers [{lead.id}]."])
    assert Scout(bad, c, mode="run").start("Which companies?").flagged


def test_argument_check():
    t = TOOLS["search_opportunities"][0]
    assert check_arguments(t, {"route": "A", "max_amount": 1e5, "agencies": ["NIH"]}) == []
    assert check_arguments(t, {"route": "C"}) == ["'route' must be one of ['A', 'B']"]
    assert check_arguments(t, {"route": "A", "top": "5", "x": 1}) == [
        "unknown argument 'x'", "'top' must be integer"]
    assert check_arguments(t, "route=A") == ["arguments must be an object"]


def test_private_sessions_are_local_only_and_keep_no_scout_log(service, tmp_path):
    private = PrivateSettings(enabled=True, endpoints=("127.0.0.1",), tls_at="server",
                              public_url=None)
    api = FakeProvider()
    api.name = "anthropic"
    with pytest.raises(PermissionError, match="hosted API"):
        Scout(api, ctx(service), private=private)
    remote = OllamaProvider("m", base_url="http://gpu.example.org:11434")
    with pytest.raises(PermissionError, match="not an allowed endpoint"):
        Scout(remote, ctx(service), private=private)
    log = ScoutLog(tmp_path / "private.jsonl")
    s = Scout(FakeProvider([call("get_record", id=OPP), f"Closes 2026-11-17 [{OPP}]."]),
              ctx(service), mode="run", log=log, private=private).start("When?")
    assert s.private and s.status == "done" and not (tmp_path / "private.jsonl").exists()


def test_bench_scoring_rules():
    from bench.scout import arg_match, score
    from perch.scout.loop import Card, Session

    assert arg_match(["clinical trial"], ["Clinical Trials"]) and not arg_match(["R01"], "R01")
    assert arg_match(500000, 500000.0) and arg_match("PAR-25-369", "grants_gov:PAR-25-369")
    s = Session("s", "run", "native", "fake:1", False, status="done", answer="ok")
    s.cards = [Card("1", 1, "search_opportunities", {"route": "A", "max_amount": 2e5},
                    status="done"), Card("2", 1, "send_email", {}, status="refused")]
    task = {"expect": ["search_opportunities"], "allowed": ["search_opportunities"],
            "args": {"search_opportunities": {"max_amount": 200000}}}
    assert score(task, s) == {"completed": False, "calls": 2, "wrong_calls": 1, "missing": ""}
    s.cards.pop()
    assert score(task, s)["completed"] is True
    s.flagged = True
    assert score(task, s)["completed"] is False
    s.flagged = False
    s.cards = [Card("3", 1, "search_opportunities", {"route": "B"}, status="done")]
    rb = {"expect": ["get_org_signals"], "allowed": ["get_org_signals"]}
    assert score(rb, s)["completed"] is True
    assert s.cards[0].tool == "search_opportunities"  # scoring does not rename the card


def test_a_repeated_call_is_answered_from_the_earlier_result(service, monkeypatch):
    runs = []
    real = TOOLS["get_record"]
    monkeypatch.setitem(TOOLS, "get_record",
                        (real[0], lambda c, **a: runs.append(a) or real[1](c, **a)))
    answer = f"It closes 2026-11-17 [{OPP}]."
    fake = FakeProvider([call("get_record", id=OPP), call("get_record", id=OPP), answer])
    scout = Scout(fake, ctx(service), mode="run")
    s = scout.start("When does it close?")
    assert [c.status for c in s.cards] == ["done", "repeated"] and s.status == "done"
    assert len(runs) == 1 and s.cards[1].result["repeat_of"] == s.cards[0].id
    # a new question may run the same call again
    fake.replies = [call("get_record", id=OPP), answer]
    s = scout.ask(s, "And again?")
    assert s.cards[-1].status == "done" and len(runs) == 2
    # ask mode: the user approves the first call; the repeat is never put to them
    fake.replies = [call("get_record", id=OPP), call("get_record", id=OPP), answer]
    ask = Scout(fake, ctx(service), mode="ask")
    s = ask.start("When does it close?")
    assert s.status == "awaiting_approval"
    s = ask.approve(s)
    assert s.status == "done" and [c.status for c in s.cards] == ["done", "repeated"]
