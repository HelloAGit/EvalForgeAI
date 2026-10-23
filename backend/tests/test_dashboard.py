import asyncio
import json

from app.config import settings
from app.database import SessionLocal
from app.services import dashboard as svc, ingest
from app.services.events import latest_event_id, sse_stream
from app.services.metrics_catalog import resolve_catalog_key, CATALOG
from app.models.entities import EvaluationRun, Project, MetricAggregate
from tests.conftest import bearer, make_results


def test_requires_auth(client):
    assert client.get("/api/v1/dashboard/overview").status_code == 401
    assert client.get("/api/v1/dashboard/overview", headers=bearer("wrong")).status_code == 401


def test_empty_database_shows_na_with_reasons_not_fake_values(client, user_h):
    body = client.get("/api/v1/dashboard/overview", headers=user_h).json()
    kpis = {k["key"]: k for k in body["kpis"]}
    assert len(kpis) == len(CATALOG) >= 24
    assert kpis["quality_index"]["value"] is None and kpis["quality_index"]["na_reason"]
    assert kpis["hallucination_rate"]["status"] == "na" and "No observations" in kpis["hallucination_rate"]["na_reason"]
    assert kpis["total_runs"]["value"] == 0
    assert kpis["latency_p95"]["value"] is None
    assert body["has_data"] is False


def test_kpis_are_computed_from_persisted_data(client, user_h, seeded):
    body = client.get("/api/v1/dashboard/overview", headers=user_h).json()
    kpis = {k["key"]: k for k in body["kpis"]}
    # llm_correctness: 15 observations across 3 runs
    expected = sum([0.9, 0.8, 1.0, 0.9, 0.85, 0.7, 0.6, 0.65, 0.7, 0.62, 0.5, 0.55, 0.6, 0.5, 0.45]) / 15
    assert abs(kpis["llm_correctness"]["value"] - expected) < 1e-9
    assert kpis["llm_correctness"]["n_observations"] == 15
    assert kpis["llm_correctness"]["ci"][0] < expected < kpis["llm_correctness"]["ci"][1]
    assert kpis["total_runs"]["value"] == 3
    assert kpis["active_jobs"]["value"] == 0
    assert kpis["token_consumption"]["value"] == 15 * 50
    assert abs(kpis["total_cost"]["value"] - 0.15) < 1e-9
    assert kpis["failure_rate"]["value"] == 1 / 15 * 1 or kpis["failure_rate"]["value"] > 0
    assert kpis["context_recall"]["status"] == "na"
    assert kpis["latency_p95"]["value"] >= kpis["latency_median"]["value"]


def test_quality_index_weights_and_missing_treatment(seeded, db):
    qi = svc.quality_index(svc.metric_stats(db, svc.Filters(model_id="model-a", run_id=seeded["runs"][("model-a", 0)])))
    # llm_correctness (0.15) + rag_faithfulness (0.15) available of total weight -> coverage below default 50%?
    total = sum(c["weight"] for c in qi["components"]) + sum(m["weight"] for m in qi["missing"])
    assert abs(qi["coverage"] - sum(c["weight"] for c in qi["components"]) / total) < 1e-12
    assert qi["value"] is None and "coverage" in qi["na_reason"].lower()
    old = settings.QI_MIN_COVERAGE
    settings.QI_MIN_COVERAGE = 0.1
    try:
        qi = svc.quality_index(svc.metric_stats(db, svc.Filters(run_id=seeded["runs"][("model-a", 0)])))
        scores = {"llm_correctness": sum([0.9, 0.8, 1.0, 0.9, 0.85]) / 5, "rag_faithfulness": sum([0.8, 0.9, 0.85, 0.9, 0.88]) / 5}
        assert abs(qi["value"] - 100 * (scores["llm_correctness"] + scores["rag_faithfulness"]) / 2) < 1e-9
        assert {m["key"] for m in qi["missing"]} >= {"hallucination_rate", "agent_task_completion"}
    finally:
        settings.QI_MIN_COVERAGE = old


def test_lower_is_better_metric_is_inverted_in_index():
    stats = {"hallucination_rate": {"n": 10, "mean": 0.2}}
    old = settings.QI_MIN_COVERAGE
    settings.QI_MIN_COVERAGE = 0.0
    try:
        assert abs(svc.quality_index(stats)["value"] - 80.0) < 1e-9
    finally:
        settings.QI_MIN_COVERAGE = old


def test_insufficient_observations_are_na(db, client, user_h):
    p = Project(name="p")
    db.add(p)
    db.flush()
    run = ingest.create_run(db, project_id=p.id, model_id="m")
    ingest.add_results(db, run, make_results("s", {"hallucination_rate": [0.1, 0.2]}))
    db.commit()
    k = {x["key"]: x for x in client.get("/api/v1/dashboard/overview", headers=user_h).json()["kpis"]}["hallucination_rate"]
    assert k["value"] is None and "Insufficient observations (n=2" in k["na_reason"]


def test_alias_resolution_and_no_double_counting(db):
    assert resolve_catalog_key("precision_at_3") == "context_precision"
    assert resolve_catalog_key("task_completion") == "agent_task_completion"
    assert resolve_catalog_key("unknown_metric") is None
    p = Project(name="p")
    db.add(p)
    db.flush()
    run = ingest.create_run(db, project_id=p.id, model_id="m")
    ingest.add_results(db, run, [{"sample_id": "1", "metrics": {"exact_match": 1.0, "numerical_accuracy": 0.0}}])
    db.commit()
    st = svc.metric_stats(db, svc.Filters())
    assert st["llm_correctness"]["n"] == 1 and st["llm_correctness"]["mean"] == 0.0  # numerical_accuracy wins by priority


def test_filters(client, user_h, seeded):
    def kpi(params, key="total_runs"):
        body = client.get("/api/v1/dashboard/overview", headers=user_h, params=params).json()
        return {k["key"]: k for k in body["kpis"]}[key]
    assert kpi({"model_id": "model-a"})["value"] == 2
    assert kpi({"provider": "prov-2"})["value"] == 1
    assert kpi({"suite": "nope"})["value"] == 0
    assert kpi({"category": "rag"})["value"] == 0
    assert kpi({"project_id": seeded["project"], "dataset_version": "v1"})["value"] == 3
    assert kpi({"run_id": seeded["runs"][("model-b", 0)]}, "llm_correctness")["n_observations"] == 5
    assert kpi({"status": "FAILED"}, "llm_correctness")["n_observations"] <= 15
    assert kpi({"date_from": "2999-01-01"}, "llm_correctness")["status"] == "na"
    assert kpi({"date_from": "2000-01-01", "date_to": "2999-12-31"}, "llm_correctness")["status"] == "ok"
    assert client.get("/api/v1/dashboard/overview", headers=user_h, params={"category": "bogus"}).status_code == 422
    assert client.get("/api/v1/dashboard/overview", headers=user_h, params={"date_from": "garbage"}).status_code == 422


def test_trends_and_charts(client, user_h, seeded):
    t = client.get("/api/v1/dashboard/trends", headers=user_h, params={"metric": "llm_correctness"}).json()
    assert {s["model_id"] for s in t["series"]} == {"model-a", "model-b"}
    assert all(p["n"] > 0 for s in t["series"] for p in s["points"])
    t = client.get("/api/v1/dashboard/trends", headers=user_h, params={"metric": "latency_p95", "bucket": "hour"}).json()
    assert t["unit"] == "ms" and t["series"]
    assert client.get("/api/v1/dashboard/trends", headers=user_h, params={"metric": "zzz"}).status_code == 422
    ov = client.get("/api/v1/dashboard/overview", headers=user_h).json()
    ranking = ov["charts"]["model_ranking"]
    assert {r["model_id"] for r in ranking} == {"model-a", "model-b"}
    assert any(d["metric_key"] == "llm_correctness" and sum(d["counts"]) == 15 for d in ov["charts"]["distributions"])
    assert ov["charts"]["latency_percentiles"] and ov["charts"]["usage"]
    assert ov["options"]["model_ids"] == ["model-a", "model-b"]


def test_regression_alert_detected_and_graded(client, user_h, seeded):
    alerts = client.get("/api/v1/dashboard/alerts", headers=user_h).json()["alerts"]
    llm = [a for a in alerts if a["metric_key"] == "llm_correctness"]
    assert len(llm) == 1 and llm[0]["model_id"] == "model-a"
    assert llm[0]["severity"] == "critical" and llm[0]["testable"] and llm[0]["p_value"] < 0.05
    assert llm[0]["latest_run_id"] == seeded["runs"][("model-a", 1)]
    assert not [a for a in alerts if a["metric_key"] == "rag_faithfulness"]  # unchanged
    assert not [a for a in alerts if a["model_id"] == "model-b"]  # only one run: nothing to compare


def test_comparison_of_models_and_runs(client, user_h, seeded):
    r = client.get("/api/v1/dashboard/compare", headers=user_h, params={"a_model_id": "model-a", "b_model_id": "model-b"}).json()
    row = next(m for m in r["metrics"] if m["key"] == "llm_correctness")
    assert row["delta"] < 0 and row["test"]["testable"] and row["a"]["n"] == 10 and row["b"]["n"] == 5
    na = next(m for m in r["metrics"] if m["key"] == "agent_task_completion")
    assert na["delta"] is None and "Insufficient" in na["na_reason"]
    r = client.get("/api/v1/dashboard/compare", headers=user_h, params={
        "a_run_id": seeded["runs"][("model-a", 0)], "b_run_id": seeded["runs"][("model-a", 1)]}).json()
    assert next(m for m in r["metrics"] if m["key"] == "llm_correctness")["delta"] < 0
    assert client.get("/api/v1/dashboard/compare", headers=user_h).status_code == 422


def test_metric_drill_down(client, user_h, seeded):
    d = client.get("/api/v1/dashboard/metrics/llm_correctness", headers=user_h).json()
    assert d["metric"]["definition"] and d["metric"]["calculation"] and d["metric"]["unit"] == "ratio"
    assert d["kpi"]["n_observations"] == 15 and d["kpi"]["ci"]
    assert d["evaluation_method"]["version"] and d["trend"]["series"]
    assert d["failed_cases"] and all(c["value"] < 0.5 for c in d["failed_cases"])
    assert d["failed_cases"][0]["value"] <= d["failed_cases"][-1]["value"]
    assert d["failed_cases"][0]["evidence_ref"].startswith("result:")
    assert d["models"] == ["model-a", "model-b"] and d["dataset_versions"] == ["v1"]
    assert sum(d["distribution"]["counts"]) == 15
    ops = client.get("/api/v1/dashboard/metrics/failure_rate", headers=user_h).json()
    assert ops["failed_cases"]
    assert client.get("/api/v1/dashboard/metrics/nope", headers=user_h).status_code == 404
    cat = client.get("/api/v1/dashboard/metrics", headers=user_h).json()
    assert len(cat["metrics"]) == len(CATALOG) and "current" in cat["metrics"][0]


def test_legacy_summary_is_database_backed(client, user_h, seeded):
    s = client.get("/api/v1/dashboard/summary", headers=user_h).json()
    assert s["is_demo_data"] is False and s["total_evaluations"] == 3 and s["agent_completion"] is None


def test_events_ids_polling_resync_and_overview_cache(client, user_h, db):
    r = client.post("/api/v1/projects", json={"name": "P"}, headers=user_h).json()
    pid = r["id"]
    first = client.get("/api/v1/dashboard/events", headers=user_h).json()
    assert first["events"] == [] and first["last_event_id"] >= 1
    run = client.post("/api/v1/evaluations/runs", headers=user_h, json={
        "project_id": pid, "model_id": "m1", "category": "llm",
        "results": [{"sample_id": "a", "metrics": {"llm_correctness": 1.0}, "latency_ms": 5}]}).json()
    ev = client.get("/api/v1/dashboard/events", headers=user_h, params={"after": first["last_event_id"]}).json()
    assert [e["type"] for e in ev["events"]] == ["run.created", "results.added"]
    ids = [e["id"] for e in ev["events"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    again = client.get("/api/v1/dashboard/events", headers=user_h, params={"after": ev["last_event_id"]}).json()
    assert again["events"] == []  # no duplicates after the cursor
    # cursor ahead of the log (e.g. database reset) or too far behind -> resync
    assert client.get("/api/v1/dashboard/events", headers=user_h, params={"after": 10_000}).json()["resync"] is True
    old = settings.SSE_MAX_CATCHUP_EVENTS
    settings.SSE_MAX_CATCHUP_EVENTS = 1
    try:
        assert client.get("/api/v1/dashboard/events", headers=user_h, params={"after": 0}).json()["resync"] is True
    finally:
        settings.SSE_MAX_CATCHUP_EVENTS = old
    ov1 = client.get("/api/v1/dashboard/overview", headers=user_h).json()
    assert ov1["last_event_id"] == ev["last_event_id"]
    assert client.get("/api/v1/dashboard/overview", headers=user_h).json()["generated_at"] == ov1["generated_at"]  # cached
    client.post(f"/api/v1/evaluations/runs/{run['id']}/results", headers=user_h,
                json={"results": [{"sample_id": "b", "metrics": {"llm_correctness": 0.0}}], "complete": True})
    ov2 = client.get("/api/v1/dashboard/overview", headers=user_h).json()
    assert ov2["last_event_id"] > ov1["last_event_id"]
    assert {k["key"]: k for k in ov2["kpis"]}["llm_correctness"]["n_observations"] == 2


def test_sse_stream_delivers_new_events_with_ids_and_reconnect_hint(db):
    async def scenario():
        with SessionLocal() as s:
            p = Project(name="p")
            s.add(p)
            s.flush()
            run = ingest.create_run(s, project_id=p.id, model_id="m")
            run_id = run.id
            s.commit()
            after = latest_event_id(s) - 1
        frames = []

        async def writer():
            await asyncio.sleep(0.3)
            with SessionLocal() as s:
                r = s.get(EvaluationRun, run_id)
                ingest.add_results(s, r, make_results("x", {"llm_correctness": [1.0]}))
                s.commit()

        task = asyncio.create_task(writer())
        async for frame in sse_stream(SessionLocal, after, 1.5):
            frames.append(frame)
        await task
        return frames
    frames = asyncio.run(scenario())
    text = "".join(frames)
    assert "event: evaluation" in text and "id: " in text
    assert '"type":"run.created"' in text and '"type":"results.added"' in text
    assert ": heartbeat" in text
    assert frames[-1].startswith("event: reconnect")
    ids = [int(f.split("\n")[0][4:]) for f in frames if f.startswith("id: ")]
    assert ids == sorted(set(ids))


def test_sse_endpoint_content_type_and_resync_frame(client, user_h, seeded):
    with client.stream("GET", "/api/v1/dashboard/events", headers=user_h,
                       params={"stream": "true", "after": 9999, "max_seconds": 1}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: resync" in body and "event: reconnect" in body


def test_preferences_roundtrip_and_validation(client, user_h):
    assert client.put("/api/v1/dashboard/preferences", headers=user_h, json={"visible_kpis": ["nope"]}).status_code == 422
    ok = client.put("/api/v1/dashboard/preferences", headers=user_h, json={"visible_kpis": ["quality_index"]})
    assert ok.status_code == 200
    assert client.get("/api/v1/dashboard/preferences", headers=user_h).json()["visible_kpis"] == ["quality_index"]
    assert client.get("/api/v1/dashboard/preferences", headers=bearer("other-token")).json()["visible_kpis"] == []


def test_aggregates_table_refreshed(db, seeded):
    aggs = db.query(MetricAggregate).filter_by(run_id=seeded["runs"][("model-b", 0)], catalog_key="llm_correctness").one()
    assert aggs.n == 5 and abs(aggs.mean - 0.52) < 1e-9 and aggs.ci_low < aggs.mean < aggs.ci_high
