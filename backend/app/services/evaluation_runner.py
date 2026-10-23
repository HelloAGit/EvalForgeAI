"""Executes queued (scheduled) evaluation runs and persists real results.

* rag   - scores the recorded retrievals in the dataset with the built-in retrieval metrics
* agent - scores recorded agent traces with the built-in agent metrics
* llm   - sends each prompt to the configured model through the Mubit gateway and scores the answer
          (requires MUBIT_API_KEY; the run fails with a clear message otherwise)

Pass/fail rules (documented in docs/dashboard.md): llm numerical_accuracy == 1; rag recall@k > 0;
agent task_completion == 1. Cost is only recorded when the provider supplies it (it never is invented).
"""
import time
from typing import Callable, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.entities import Dataset, EvaluationRun, utcnow
from app.services import ingest
from app.services.agent_metrics import AgentMetricsEngine
from app.services.llm_metrics import LLMMetricsEngine
from app.services.mubit_gateway import MubitGateway
from app.services.rag_metrics import RAGMetricsEngine


def claim_pending_run(db: Session) -> Optional[EvaluationRun]:
    for run_id in db.scalars(select(EvaluationRun.id).where(
            EvaluationRun.status == "PENDING", EvaluationRun.trigger.in_(("scheduled", "dataset", "release")))
            .order_by(EvaluationRun.created_at).limit(5)).all():
        won = db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id, EvaluationRun.status == "PENDING")
                         .values(status="RUNNING", started_at=utcnow())).rowcount
        db.commit()
        if won == 1:
            return db.get(EvaluationRun, run_id)
    return None


def execute_run(db: Session, run: EvaluationRun, gateway: Optional[MubitGateway] = None) -> None:
    try:
        ds = db.get(Dataset, run.dataset_id) if run.dataset_id else None
        if ds is None:
            raise ValueError("Dataset not found for run")
        items = (ds.content or [])[: int((run.config or {}).get("max_samples", 100))]
        batch = []
        if ds.type == "rag":
            eng = RAGMetricsEngine()
            for it in items:
                m = eng.evaluate_retrieval(it.get("retrieved_doc_ids", []), it.get("relevant_doc_ids", []), k=3)
                batch.append({"sample_id": it["id"], "prompt": it.get("query", ""), "expected_output": it.get("expected_answer"),
                              "metrics": m, "status": "PASSED" if m["recall_at_3"] > 0 else "FAILED",
                              "evidence": {"retrieved": it.get("retrieved_doc_ids"), "relevant": it.get("relevant_doc_ids")}})
        elif ds.type == "agent":
            eng = AgentMetricsEngine()
            for it in items:
                trace = {"steps": it.get("steps", []), "expected_outcome": it.get("expected_outcome"),
                         "verified_outcome": it.get("verified_outcome", it.get("expected_outcome", ""))}
                if "verified_outcome" not in it:
                    # recorded traces without a verified outcome cannot be judged for completion
                    m = {"tool_accuracy": eng.calculate_tool_accuracy(trace["steps"])}
                    status = "COMPLETED"
                else:
                    m = eng.evaluate_agent_trace(trace)
                    status = "PASSED" if m["task_completion"] == 1.0 else "FAILED"
                batch.append({"sample_id": it["id"], "prompt": it.get("task", ""), "metrics": m, "status": status})
        elif ds.type == "llm":
            gateway = gateway or MubitGateway(model=run.model_id)
            if not gateway.is_configured():
                raise RuntimeError("MUBIT_API_KEY is not configured; LLM evaluation runs need a model gateway.")
            eng = LLMMetricsEngine()
            for it in items:
                started = time.monotonic()
                try:
                    resp = gateway.complete("Answer concisely with the final value.", it.get("question", ""), max_tokens=256)
                except Exception as exc:
                    batch.append({"sample_id": it["id"], "prompt": it.get("question", ""), "metrics": {},
                                  "error_type": "provider_error", "evidence": {"error": type(exc).__name__}})
                    continue
                expected = it.get("expected_answer", "")
                m = eng.evaluate_sample(expected, resp.text)
                batch.append({"sample_id": it["id"], "prompt": it.get("question", ""), "expected_output": expected,
                              "actual_output": resp.text, "latency_ms": (time.monotonic() - started) * 1000,
                              "token_count": (resp.input_tokens or 0) + (resp.output_tokens or 0) if resp.output_tokens is not None else None,
                              "metrics": {"numerical_accuracy": m["numerical_accuracy"]},
                              "status": "PASSED" if m["numerical_accuracy"] == 1.0 else "FAILED",
                              "mubit_request_id": resp.request_id})
        else:
            raise ValueError(f"Unsupported dataset type {ds.type!r}")
        ingest.add_results(db, run, batch)
        ingest.complete_run(db, run)
    except Exception as exc:
        db.rollback()
        run = db.get(EvaluationRun, run.id)
        ingest.complete_run(db, run, "FAILED", f"{type(exc).__name__}: {exc}"[:500])
    db.commit()
