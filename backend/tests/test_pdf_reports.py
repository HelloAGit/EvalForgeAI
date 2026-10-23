import io

import pytest
from pypdf import PdfReader

from app.database import SessionLocal
from app.models.entities import ReportSnapshot, StatisticalResult
from app.services.pdf_report import render_pdf, TEMPLATES, safe
from app.services.snapshot import canonical_hash
from tests.conftest import make_results


def _body(seeded, **kw):
    return {"title": "Q3 Quality Report", "template": "executive", "project_id": seeded["project"], **kw}


def _text(pdf_bytes):
    r = PdfReader(io.BytesIO(pdf_bytes))
    return r, "\n".join(p.extract_text() for p in r.pages)


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_each_template_produces_valid_pdf_matching_snapshot(client, user_h, seeded, template):
    r = client.post("/api/v1/reports", headers=user_h, json=_body(seeded, template=template))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    rep = client.get(f"/api/v1/reports/{rid}", headers=user_h).json()
    assert rep["status"] == "COMPLETED" and rep["artifact"]["size_bytes"] > 2000
    dl = client.get(f"/api/v1/reports/{rid}/download", headers=user_h)
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
    assert "attachment" in dl.headers["content-disposition"] and dl.headers["x-content-type-options"] == "nosniff"
    assert dl.content.startswith(b"%PDF-") and dl.content.rstrip().endswith(b"%%EOF")
    reader, text = _text(dl.content)
    assert len(reader.pages) >= 3  # cover + toc + content
    assert reader.metadata.title == "Q3 Quality Report"
    assert TEMPLATES[template] in text and "Table of contents" in text and "Page 3" in text
    snap = client.get(f"/api/v1/reports/{rid}/snapshot", headers=user_h).json()
    # figures in the PDF equal the snapshot values (which equal the persisted data)
    llm = next(m for m in snap["payload"]["metrics"] if m["key"] == "llm_correctness")
    assert f"{llm['value'] * 100:.1f}%" in text
    assert "N/A" in text  # unsupported metrics are labelled, never scored


def test_snapshot_is_canonical_immutable_and_complete(client, user_h, seeded, db):
    rid = client.post("/api/v1/reports", headers=user_h, json=_body(seeded)).json()["id"]
    snap = client.get(f"/api/v1/reports/{rid}/snapshot", headers=user_h).json()
    p = snap["payload"]
    for key in ("schema_version", "snapshot_id", "project", "runs", "models", "dataset_versions", "evaluation_time_range",
                "metric_definitions", "metrics", "statistical_results", "chart_datasets", "failures", "limitations",
                "evidence_index", "created_at", "quality_index", "recommendations"):
        assert key in p, key
    assert p["schema_version"] == "1.0" and p["models"] == ["model-a", "model-b"] and p["dataset_versions"] == ["v1"]
    assert len(p["runs"]) == 3
    llm = next(m for m in p["metrics"] if m["key"] == "llm_correctness")
    assert llm["n_observations"] == 15 and llm["ci_low"] < llm["value"] < llm["ci_high"]
    assert snap["payload_sha256"] == canonical_hash(p)
    assert db.query(StatisticalResult).filter_by(snapshot_id=p["snapshot_id"]).count() >= 1
    row = db.get(ReportSnapshot, p["snapshot_id"])
    row.payload = {"tampered": True}
    with pytest.raises(ValueError):
        db.commit()
    db.rollback()
    with pytest.raises(ValueError):
        db.delete(db.get(ReportSnapshot, p["snapshot_id"]))
        db.commit()
    db.rollback()


def test_snapshot_ignores_later_data_and_regeneration_uses_original(client, user_h, seeded, db):
    from app.services import ingest
    rid = client.post("/api/v1/reports", headers=user_h, json=_body(seeded)).json()["id"]
    before = client.get(f"/api/v1/reports/{rid}/snapshot", headers=user_h).json()
    run = ingest.create_run(db, project_id=seeded["project"], model_id="model-a", provider="prov-1", suite="core")
    ingest.add_results(db, run, make_results("late", {"llm_correctness": [0.0] * 5}))
    db.commit()
    assert client.post(f"/api/v1/reports/{rid}/regenerate", headers=user_h).status_code == 202
    rep = client.get(f"/api/v1/reports/{rid}", headers=user_h).json()
    assert rep["status"] == "COMPLETED" and len(rep["artifacts"]) == 2
    assert client.get(f"/api/v1/reports/{rid}/snapshot", headers=user_h).json()["payload_sha256"] == before["payload_sha256"]


def test_permissions_on_report_endpoints(client, user_h, other_h, admin_h, seeded):
    assert client.get("/api/v1/reports").status_code == 401
    assert client.post("/api/v1/reports", json=_body(seeded)).status_code == 401
    rid = client.post("/api/v1/reports", headers=user_h, json=_body(seeded)).json()["id"]
    for path in ("", "/snapshot", "/download"):
        assert client.get(f"/api/v1/reports/{rid}{path}", headers=other_h).status_code == 404, path
        assert client.get(f"/api/v1/reports/{rid}{path}").status_code == 401, path
    assert client.post(f"/api/v1/reports/{rid}/regenerate", headers=other_h).status_code == 404
    assert client.get(f"/api/v1/reports/{rid}/download", headers=admin_h).status_code == 200
    assert client.get("/api/v1/reports", headers=other_h).json() == []
    assert len(client.get("/api/v1/reports", headers=user_h).json()) == 1


def test_validation_and_error_handling(client, user_h, seeded):
    assert client.post("/api/v1/reports", headers=user_h, json=_body(seeded, template="nope")).status_code == 422
    assert client.post("/api/v1/reports", headers=user_h, json=_body(seeded, metrics=["bogus"])).status_code == 422
    assert client.post("/api/v1/reports", headers=user_h, json=_body(seeded, charts=["bogus"])).status_code == 422
    assert client.post("/api/v1/reports", headers=user_h, json=_body(seeded, project_id="missing")).status_code == 422
    assert client.post("/api/v1/reports", headers=user_h, json=_body(seeded, model_ids=["ghost"])).status_code == 422
    assert client.get("/api/v1/reports/unknown", headers=user_h).status_code == 404


def test_report_scope_and_chart_selection(client, user_h, seeded):
    r = client.post("/api/v1/reports/preview", headers=user_h, json=_body(
        seeded, model_ids=["model-b"], metrics=["llm_correctness"], charts=["model_ranking"])).json()["payload"]
    assert r["models"] == ["model-b"] and [m["key"] for m in r["metrics"]] == ["llm_correctness"]
    assert list(r["chart_datasets"]) == ["model_ranking"] and r["metrics"][0]["n_observations"] == 5
    assert r["scope"]["run_ids"] == [seeded["runs"][("model-b", 0)]]


def test_include_cases_toggle(client, user_h, seeded, db):
    from app.models.entities import EvaluationResult
    without = client.post("/api/v1/reports/preview", headers=user_h, json=_body(seeded)).json()["payload"]
    with_cases = client.post("/api/v1/reports/preview", headers=user_h, json=_body(seeded, include_cases=True)).json()["payload"]
    assert all("prompt_excerpt" not in c for c in without["failures"]["failed_cases"])
    assert all("prompt_excerpt" in c for c in with_cases["failures"]["failed_cases"])


def test_long_content_wraps_and_tables_paginate(client, user_h, db):
    from app.models.entities import Project
    from app.services import ingest
    p = Project(name="Big " + "very-long-name-" * 8)
    db.add(p)
    db.flush()
    for i in range(30):
        run = ingest.create_run(db, project_id=p.id, model_id=f"model-{i}-" + "x" * 40, suite="s")
        ingest.add_results(db, run, make_results(f"r{i}", {"llm_correctness": [0.1 * (j % 10) for j in range(6)]},
                                                 status=["FAILED"] * 6, extra={"error_type": "timeout " * 12}))
        ingest.complete_run(db, run)
    db.commit()
    body = {"title": "Long " * 30, "template": "technical", "project_id": p.id}
    rid = client.post("/api/v1/reports", headers=user_h, json=body).json()["id"]
    dl = client.get(f"/api/v1/reports/{rid}/download", headers=user_h).content
    reader, text = _text(dl)
    assert len(reader.pages) >= 8
    box = reader.pages[0].mediabox
    assert abs(float(box.width) - 595.27) < 1 and abs(float(box.height) - 841.89) < 1  # A4
    # no text runs off the right edge of any page
    for page in reader.pages:
        xs = []
        page.extract_text(visitor_text=lambda t, cm, tm, fd, fs: xs.append(tm[4]) if t.strip() else None)
        assert all(x < float(box.width) for x in xs)
    assert "model-29-" in text  # later rows are on later pages, not dropped


def test_charts_are_embedded_as_vector_graphics(client, user_h, seeded):
    rid = client.post("/api/v1/reports", headers=user_h, json=_body(seeded, template="technical")).json()["id"]
    pdf = client.get(f"/api/v1/reports/{rid}/download", headers=user_h).content
    reader, text = _text(pdf)
    assert "Latency percentiles" in text and "confidence interval" in text.lower()
    assert "Chart not available" in text  # charts without data are labelled, not faked
    ops = [op for pg in reader.pages for _, op in pg.get_contents().operations]
    assert ops.count(b"re") > 20 and ops.count(b"l") > 10  # rectangle/line operators from the chart drawings


def test_unicode_sanitising_and_unknown_template():
    assert safe("a \u2265 b \u2192 c \u0394") == "a >= b -> c Delta "
    with pytest.raises(ValueError):
        render_pdf({}, "nope", "t", "r", "now")


def test_render_failure_marks_report_failed(client, user_h, seeded, monkeypatch):
    import app.services.reports as rs
    monkeypatch.setattr(rs, "render_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    rid = client.post("/api/v1/reports", headers=user_h, json=_body(seeded)).json()["id"]
    rep = client.get(f"/api/v1/reports/{rid}", headers=user_h).json()
    assert rep["status"] == "FAILED" and "boom" in rep["error_message"]
    assert client.get(f"/api/v1/reports/{rid}/download", headers=user_h).status_code == 409


def test_storage_rejects_traversal(tmp_path):
    from app.services.storage import LocalArtifactStorage, StorageError
    s = LocalArtifactStorage(str(tmp_path))
    for bad in ("../../etc/passwd", "pdf/../../x.pdf", "/etc/passwd", "pdf/abc.pdf"):
        with pytest.raises(StorageError):
            s.path(bad)
    key = s.new_key("pdf", "pdf")
    size, sha = s.put_bytes(key, b"%PDF-x")
    assert s.exists(key) and size == 6 and len(sha) == 64
