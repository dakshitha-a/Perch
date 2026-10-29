"""Monitoring (S16): the Grants.gov delta refresh, triggers, diff and the code-written
draft, on fake models and fixture-backed clients."""

import json
from datetime import date

import httpx

from perch import monitor
from perch.schemas import Brief, Digest, Opportunity
from perch.sources import grants_gov

from .test_api import FIX, make

AID = "A5026494099"  # the fixture researcher; their last award ends 2016-06-30


def detail(number: str = "PAR-25-268", oid: int = 357303, close: str | None = None) -> dict:
    d = json.loads((FIX / "grants_gov/fetch_opportunity.json").read_text())
    d["data"].update(id=oid, opportunityNumber=number)
    if close:
        d["data"]["synopsis"]["responseDate"] = close
    return d


def grants(hits: list[dict], details: dict[int, dict], calls: list[int]):
    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if req.url.path.endswith("/search2"):
            page = hits if body["startRecordNum"] == 0 else []
            return httpx.Response(200, json={"errorcode": 0, "data": {
                "hitCount": len(hits), "oppHits": page}})
        calls.append(body["opportunityId"])
        if body["opportunityId"] not in details:
            return httpx.Response(200, json={"errorcode": 1, "msg": "not found"})
        return httpx.Response(200, json=details[body["opportunityId"]])
    return lambda: grants_gov.GrantsGovClient(transport=httpx.MockTransport(handle),
                                              min_interval=0)


def hit(number: str, oid: int, close: str = "11/17/2026", status: str = "posted") -> dict:
    return {"id": str(oid), "number": number, "closeDate": close, "oppStatus": status}


def test_refresh_fetches_only_new_or_changed_listings(tmp_path):
    _, service = make(tmp_path)  # the store holds PAR-25-268, posted, closing 2026-11-17
    calls: list[int] = []
    g = grants([hit("PAR-25-268", 357303), hit("PAR-99-001", 999),
                hit("PAR-25-268", 357303, close="12/01/2026")],
               {999: detail("PAR-99-001", 999),
                357303: detail(close="Dec 01, 2026 12:00:00 AM EST")}, calls)
    with service.repo() as r, g() as gg:
        n = monitor.refresh_opportunities(r, gg)
        assert r.get(Opportunity, "grants_gov:PAR-25-268").close_date == date(2026, 12, 1)
    assert n == {"listed": 3, "new": 1, "changed": 1, "unchanged": 1, "failed": 0}
    assert calls == [999, 357303]  # the unchanged listing was not fetched


def test_a_failed_fetch_is_counted_and_the_refresh_goes_on(tmp_path):
    _, service = make(tmp_path)
    g = grants([hit("PAR-98-001", 998), hit("PAR-99-001", 999)],
               {999: detail("PAR-99-001", 999)}, [])  # 998 answers with an error
    with service.repo() as r, g() as gg:
        n = monitor.refresh_opportunities(r, gg)
    assert n["failed"] == 1 and n["new"] == 1


def test_first_run_is_a_baseline_with_no_draft(tmp_path):
    _, service = make(tmp_path)
    d = monitor.watch(service, AID, as_of=date(2026, 10, 28))
    assert d.baseline_brief_id is None and d.changes == [] and d.draft_subject is None
    assert d.source == "perch" and d.source_url == f"perch://digests/{d.id}"
    assert [s["record_id"] for s in d.snapshot] == ["grants_gov:PAR-25-268"]
    with service.repo() as r:
        assert r.get(Digest, d.id) == d
        assert r.get(Brief, d.brief_id).status == "done"


def test_a_new_top_10_opportunity_and_a_moved_close_date_draft_an_email(tmp_path):
    _, service = make(tmp_path)
    first = monitor.watch(service, AID, as_of=date(2026, 10, 28))
    g = grants([hit("PAR-25-268", 357303, close="12/01/2026"), hit("PAR-99-001", 999)],
               {999: detail("PAR-99-001", 999),
                357303: detail(close="Dec 01, 2026 12:00:00 AM EST")}, [])
    [d] = monitor.run(service, [AID], g, as_of=date(2026, 10, 29))
    assert d.baseline_brief_id == first.brief_id and d.brief_id != first.brief_id  # not reused
    kinds = {c.kind: c for c in d.changes}
    assert set(kinds) == {"new_lead", "close_date"}
    assert kinds["new_lead"].record_id == "grants_gov:PAR-99-001" and kinds["new_lead"].trigger
    assert (kinds["close_date"].before, kinds["close_date"].after) == ("2026-11-17",
                                                                       "2026-12-01")
    assert not kinds["close_date"].trigger
    assert d.draft_subject == "Perch weekly watch: 1 new funding opportunity in your top 10"
    body = d.draft_body
    assert "PAR-99-001" in body and "closes 2026-11-17" in body  # copied from its record
    assert "Was 2026-11-17, now 2026-12-01" in body
    assert "did not send it" in body and d.refresh["new"] == 1


def test_an_award_ending_within_12_months_fires_once(tmp_path):
    _, service = make(tmp_path)
    d1 = monitor.watch(service, AID, as_of=date(2015, 7, 1))  # the award ends 2016-06-30
    [c] = d1.changes
    assert c.kind == "award_ending" and c.after == "2016-06-30" and c.trigger
    assert d1.draft_subject == "Perch weekly watch: a public award ends within 12 months"
    assert "Ends 2016-06-30" in d1.draft_body and c.source_url in d1.draft_body
    d2 = monitor.watch(service, AID, as_of=date(2015, 7, 8))
    assert [x.trigger for x in d2.changes if x.kind == "award_ending"] == [False]
    assert d2.draft_subject is None  # already told; nothing new
    with service.repo() as r:
        assert [x.id for x in monitor.latest(r)] == [d2.id]


def test_year_after_handles_29_february():
    assert monitor.year_after(date(2028, 2, 29)) == date(2029, 2, 28)


def test_cli_needs_someone_to_watch(monkeypatch, capsys):
    from perch.cli import main

    monkeypatch.delenv("PERCH_WATCH", raising=False)
    monkeypatch.setattr("perch.cli.load_dotenv", lambda: None)
    assert main(["monitor", "--models", "fake"]) == 2
    assert "needs --author" in capsys.readouterr().err
