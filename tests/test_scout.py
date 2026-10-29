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


def test_tools_from_later_sessions_say_so(service):
    c = ctx(service)
    for name in ("get_org_signals", "compare", "draft_handoff"):
        args = {"opportunity_ids": [OPP]} if name == "compare" else (
            {"opportunity_id": OPP} if name == "draft_handoff" else {})
        assert TOOLS[name][1](c, **args)["status"] == "not_built"
    assert TOOLS["search_opportunities"][1](c, route="B")["status"] == "not_built"


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
