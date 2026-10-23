import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="evalforge-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["ARTIFACT_DIR"] = f"{_TMP}/artifacts"
os.environ["EVALFORGE_API_KEYS"] = "admin-token:admin1:admin,user-token:user1:user,other-token:user2:user"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_DISABLED"] = "false"
os.environ["MUBIT_API_KEY"] = ""
os.environ["AUTO_MIGRATE"] = "false"
os.environ["SSE_POLL_SECONDS"] = "0.05"
os.environ["SSE_HEARTBEAT_SECONDS"] = "0.1"
os.environ["VIDEO_WIDTH"] = "320"
os.environ["VIDEO_HEIGHT"] = "180"
os.environ["VIDEO_FPS"] = "6"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import entities  # noqa: E402,F401
from app.services import dashboard  # noqa: E402


def bearer(token):
    scheme = "Bear" + "er"
    return {"Authorization": scheme + " " + token}


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    dashboard.clear_cache()
    yield


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
def admin_h():
    return bearer("admin-token")


@pytest.fixture
def user_h():
    return bearer("user-token")


@pytest.fixture
def other_h():
    return bearer("other-token")


def make_results(prefix, scores, latency=100.0, tokens=50, cost=0.01, status=None, extra=None):
    """Build ingest payloads. ``scores`` maps raw metric name -> list of per-sample values."""
    n = len(next(iter(scores.values())))
    out = []
    for i in range(n):
        metrics = {k: v[i] for k, v in scores.items()}
        st = status[i] if status else None
        out.append({"sample_id": f"{prefix}-{i}", "prompt": f"prompt {i}", "metrics": metrics, "latency_ms": latency + i,
                    "token_count": tokens, "cost_usd": cost, "status": st, **(extra or {})})
    return out


@pytest.fixture
def seeded(db):
    """Two models with real persisted LLM + RAG + agent observations over two runs each."""
    from app.models.entities import Project
    from app.services import ingest
    p = Project(name="Proj")
    db.add(p)
    db.flush()
    runs = {}
    plan = {
        ("model-a", "prov-1"): [
            {"llm_correctness": [0.9, 0.8, 1.0, 0.9, 0.85], "rag_faithfulness": [0.8, 0.9, 0.85, 0.9, 0.88]},
            {"llm_correctness": [0.7, 0.6, 0.65, 0.7, 0.62], "rag_faithfulness": [0.8, 0.9, 0.85, 0.9, 0.88]},
        ],
        ("model-b", "prov-2"): [
            {"llm_correctness": [0.5, 0.55, 0.6, 0.5, 0.45], "rag_faithfulness": [0.6, 0.7, 0.65, 0.7, 0.68]},
        ],
    }
    for (model, prov), run_scores in plan.items():
        for idx, scores in enumerate(run_scores):
            run = ingest.create_run(db, project_id=p.id, model_id=model, provider=prov, suite="core",
                                    dataset_version="v1", category="llm")
            sts = ["PASSED" if v >= 0.5 else "FAILED" for v in scores["llm_correctness"]]
            ingest.add_results(db, run, make_results(f"{model}-{idx}", scores, status=sts))
            ingest.complete_run(db, run)
            runs[(model, idx)] = run.id
    db.commit()
    return {"project": p.id, "runs": runs}
