import json

import pytest

from app.services import narrative as nv
from app.services.mubit_gateway import BudgetExceeded, GatewayError, GatewayNotConfigured, GatewayResponse, MubitGateway
from app.services.snapshot import build_payload


class FakeGateway:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def is_configured(self):
        return True

    def complete(self, system, user, max_tokens=None, temperature=0.0):
        self.calls.append((system, user))
        if self.exc:
            raise self.exc
        return GatewayResponse(self.text, 100, 200, "req_1")


@pytest.fixture
def payload(db, seeded):
    return build_payload(db, "user1", {"project_id": seeded["project"]}, "snap-test")


def good_json(payload, **override):
    m = next(x for x in payload["metrics"] if x["key"] == "llm_correctness")
    data = {"schema_version": "1.0", "title": "Briefing", "executive_narrative": "Summary of the evaluation.",
            "key_findings": [{"text": f"LLM answer correctness is {m['value'] * 100:.1f}% across {m['n_observations']} observations.",
                              "evidence_refs": ["metric:llm_correctness"]}],
            "chart_explanations": [], "failure_analysis": "", "statistical_interpretation": "", "recommendations": [],
            "scenes": [{"id": "s1", "type": "title", "title": "Intro", "on_screen_text": ["Hello"], "narration": "Welcome.", "duration_seconds": 10},
                       {"id": "s2", "type": "llm", "title": "LLM quality", "on_screen_text": [f"{m['value'] * 100:.1f}%"],
                        "narration": f"Correctness was {m['value'] * 100:.1f} percent.", "duration_seconds": 20,
                        "metric_refs": ["metric:llm_correctness"]},
                       {"id": "s3", "type": "closing", "title": "End", "on_screen_text": [], "narration": "Thanks.", "duration_seconds": 5}]}
    data.update(override)
    return data


OPTS = {"duration_seconds": 60, "mode": "silent", "sections": None}


def test_valid_claude_storyboard_is_accepted_and_grounded(payload):
    gw = FakeGateway(json.dumps(good_json(payload)))
    sb, source, val = nv.generate_storyboard(payload, OPTS, gw)
    assert source == "claude" and val["ok"] and val["flags"] == []
    assert val["numbers_checked"] >= 3 and val["numbers_unsupported"] == 0
    assert abs(sb.total_duration_seconds - 60) < 1.5  # durations are fitted to the target
    assert val["usage"]["output_tokens"] == 200
    system, user = gw.calls[0]
    assert "ONLY" in system and "evidence_index" in user and "prompt_excerpt" not in user


def test_fenced_json_and_surrounding_prose_are_parsed(payload):
    raw = "Here you go:\n```json\n" + json.dumps(good_json(payload)) + "\n```"
    assert nv.parse_storyboard(raw).title == "Briefing"
    assert nv.parse_storyboard("noise " + json.dumps(good_json(payload)) + " trailing").title == "Briefing"


@pytest.mark.parametrize("raw", ["", "   ", "not json at all", "{broken", "[1,2]", '{"title": "x"}',
                                 '{"title":"x","scenes":[{"id":"a","type":"bogus","title":"t","duration_seconds":5}]}'])
def test_malformed_responses_raise_narrative_error(raw):
    with pytest.raises(nv.NarrativeError):
        nv.parse_storyboard(raw)


def test_schema_limits_are_enforced(payload):
    d = good_json(payload)
    d["scenes"][0]["duration_seconds"] = 500
    with pytest.raises(nv.NarrativeError):
        nv.parse_storyboard(json.dumps(d))
    d = good_json(payload)
    d["scenes"] = d["scenes"] * 6
    with pytest.raises(nv.NarrativeError):
        nv.parse_storyboard(json.dumps(d))
    d = good_json(payload)
    d["recommendations"] = [{"text": "x", "priority": "urgent"}]
    with pytest.raises(nv.NarrativeError):
        nv.parse_storyboard(json.dumps(d))


def test_unsupported_numeric_claims_are_flagged_not_silently_accepted(payload):
    d = good_json(payload)
    d["scenes"][1]["narration"] = "Correctness improved to 97.3 percent, up 12.5 points."
    sb, source, val = nv.generate_storyboard(payload, OPTS, FakeGateway(json.dumps(d)))
    assert source == "claude" and not val["ok"]
    toks = [f["message"] for f in val["flags"] if f["type"] == "unsupported_number"]
    assert any("97.3" in t for t in toks) and any("12.5" in t for t in toks)
    assert all(f["scene_id"] == "s2" for f in val["flags"] if f["type"] == "unsupported_number")
    assert nv.blocking_flags(val)


def test_mostly_fabricated_response_is_rejected_and_replaced_by_template(payload):
    d = good_json(payload)
    d["executive_narrative"] = "Scores were 11.1, 22.2, 33.3, 44.4 and 55.5."
    d["failure_analysis"] = "Also 66.6, 77.7 and 88.8 were seen."
    d["statistical_interpretation"] = "Values of 91.1 and 92.2 followed."
    sb, source, val = nv.generate_storyboard(payload, OPTS, FakeGateway(json.dumps(d)))
    assert source == "template"
    assert any(f["type"] == "claude_unavailable" and "Rejected" in f["message"] for f in val["flags"])
    assert val["numbers_unsupported"] == 0


def test_unknown_references_and_significance_and_causality(payload):
    d = good_json(payload)
    d["key_findings"][0]["evidence_refs"] = ["metric:does_not_exist"]
    d["statistical_interpretation"] = "Failures were caused by retrieval."
    val = nv.validate_grounding(nv.Storyboard.model_validate(d), payload)
    types = {f["type"] for f in val["flags"]}
    assert {"unknown_reference", "causal_language"} <= types
    nosig = {**payload, "statistical_results": []}
    d2 = good_json(payload, executive_narrative="Model B is significantly worse.")
    val2 = nv.validate_grounding(nv.Storyboard.model_validate(d2), nosig)
    assert any(f["type"] == "unsupported_significance" for f in val2["flags"])
    d3 = good_json(payload, executive_narrative="The difference is not statistically significant.")
    assert not any(f["type"] == "unsupported_significance" for f in nv.validate_grounding(nv.Storyboard.model_validate(d3), nosig)["flags"])


def test_number_matching_accepts_raw_rounded_percent_forms(payload):
    allowed = nv.allowed_numbers(payload)
    assert nv._is_supported("68.8", allowed) and nv._is_supported("0.688", allowed) and nv._is_supported("69", allowed)
    assert not nv._is_supported("68.9", allowed)
    assert nv.extract_numbers("run:abc-123 on 2026-10-23T20:41:19Z used model-3 at p95 of 104 ms (+3.5%)") == ["104", "3.5"]


def test_provider_failures_fall_back_to_grounded_template(payload):
    for exc in (GatewayError("down"), BudgetExceeded("too big"), GatewayNotConfigured("x")):
        sb, source, val = nv.generate_storyboard(payload, OPTS, FakeGateway(exc=exc))
        assert source == "template" and val["flags"][0]["type"] == "claude_unavailable"
        assert val["ok"], val["flags"]
    sb, source, val = nv.generate_storyboard(payload, OPTS, FakeGateway("garbage"))
    assert source == "template"


def test_unconfigured_gateway_uses_template_without_calls(payload):
    gw = MubitGateway(api_key="")
    sb, source, val = nv.generate_storyboard(payload, OPTS, gw)
    assert source == "template" and val["flags"][0]["type"] == "claude_not_configured" and val["ok"]


def test_template_storyboard_is_grounded_and_respects_sections(payload):
    sb = nv.template_storyboard(payload, {"duration_seconds": 120, "sections": ["kpis", "llm", "stats"]})
    assert [s.type for s in sb.scenes] == ["title", "kpis", "llm", "stats", "closing"]
    assert nv.validate_grounding(sb, payload)["flags"] == []
    llm = next(s for s in sb.scenes if s.type == "llm")
    assert any("68.8%" in line for line in llm.on_screen_text)
    assert abs(nv.fit_duration(sb, 120).total_duration_seconds - 120) < 3


def test_input_budget_enforced_by_gateway(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "MUBIT_MAX_INPUT_CHARS", 100)
    gw = MubitGateway(api_key="k", client=object())
    with pytest.raises(BudgetExceeded):
        gw.complete("s" * 80, "u" * 80)


def test_oversized_snapshot_is_trimmed_or_rejected(payload, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "MUBIT_MAX_INPUT_CHARS", 2400)
    with pytest.raises(nv.NarrativeError):
        nv._compact_payload(payload, 500)
    sb, source, val = nv.generate_storyboard(payload, OPTS, FakeGateway(json.dumps(good_json(payload))))
    assert source == "template"  # budget too small -> graceful fallback


class _Msg:
    def __init__(self, text):
        self.content = [type("B", (), {"text": text})()]
        self.usage = type("U", (), {"input_tokens": 5, "output_tokens": 7})()
        self.id = "msg_1"


class _SDK:
    def __init__(self, fail_times=0, status=500):
        self.fail, self.status, self.calls, self.kwargs = fail_times, status, 0, None
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        self.kwargs = kw
        if self.calls <= self.fail:
            e = RuntimeError("boom")
            e.status_code = self.status
            raise e
        return _Msg("{}")


def test_gateway_retries_transient_errors_and_caps_tokens(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "MUBIT_MAX_RETRIES", 2)
    monkeypatch.setattr(settings, "MUBIT_MIN_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(settings, "MUBIT_MAX_TOKENS", 1000)
    sdk = _SDK(fail_times=2)
    r = MubitGateway(api_key="k", client=sdk, sleep=lambda s: None).complete("s", "u", max_tokens=99999)
    assert r.text == "{}" and sdk.calls == 3 and sdk.kwargs["max_tokens"] == 1000 and r.output_tokens == 7
    sdk = _SDK(fail_times=5, status=400)  # non-transient errors are not retried
    with pytest.raises(GatewayError):
        MubitGateway(api_key="k", client=sdk, sleep=lambda s: None).complete("s", "u")
    assert sdk.calls == 1
