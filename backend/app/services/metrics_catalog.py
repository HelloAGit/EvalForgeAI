"""Configurable metrics catalogue and Overall Quality Index (OQI) definition.

Every KPI shown by the dashboard is declared here. A KPI is *never* given a
value unless persisted observations (or operational data) back it; otherwise
the dashboard shows ``N/A`` together with a specific reason.

Overall Quality Index
---------------------
``OQI = 100 * sum(w_i * s_i) / sum(w_i)`` over the *available* quality metrics i,
where ``s_i`` is the mean observed score in [0, 1] (``1 - mean`` for
lower-is-better metrics such as hallucination rate) and ``w_i`` the metric
weight. A metric is available when it has at least ``MIN_OBSERVATIONS``
observations. Missing metrics are excluded and the remaining weights are
re-normalised (no imputation). The index is reported as N/A when the share of
total weight covered by available metrics (``coverage``) is below
``QI_MIN_COVERAGE``. Weights can be overridden with ``QUALITY_INDEX_WEIGHTS_JSON``.
"""
import json
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

CATALOG_VERSION = "1.0"


@dataclass(frozen=True)
class MetricDef:
    key: str
    name: str
    category: str  # llm | rag | agent | operations
    unit: str  # ratio | ms | tokens | usd | count
    definition: str
    calculation: str
    direction: str = "higher_better"  # higher_better | lower_better | neutral
    kind: str = "observation"  # observation | derived
    qi_weight: float = 0.0
    aliases: Tuple[str, ...] = ()
    alias_prefixes: Tuple[str, ...] = ()
    producer: str = "external"  # built-in | external
    method: str = ""
    method_version: str = "1.0"
    failure_threshold: Optional[float] = None  # observation below (above for lower_better) = failed case
    version: str = CATALOG_VERSION

    def public(self) -> dict:
        d = asdict(self)
        d["aliases"] = list(self.aliases)
        d["alias_prefixes"] = list(self.alias_prefixes)
        return d


_EXT = "Requires scores ingested by an LLM-judge or external evaluator (not computed by the built-in engines)."

CATALOG: List[MetricDef] = [
    MetricDef("quality_index", "Overall AI Quality Index", "operations", "index",
              "Weighted composite of available quality metrics on a 0-100 scale.",
              "100 * sum(w_i*s_i)/sum(w_i) over metrics with enough observations; missing metrics excluded, weights re-normalised.",
              kind="derived"),
    MetricDef("total_runs", "Total evaluation runs", "operations", "count",
              "Number of evaluation runs matching the filters.", "COUNT(evaluation_runs)", "neutral", "derived"),
    MetricDef("active_jobs", "Active evaluation jobs", "operations", "count",
              "Runs currently PENDING or RUNNING.", "COUNT(runs WHERE status IN (PENDING, RUNNING))", "neutral", "derived"),
    MetricDef("llm_correctness", "LLM answer correctness", "llm", "ratio",
              "Share of answers judged correct against the reference.", "Mean of per-sample correctness scores in [0,1].",
              qi_weight=0.15, aliases=("answer_correctness", "numerical_accuracy", "exact_match"),
              producer="built-in", method="exact_match / numerical_accuracy", failure_threshold=0.5),
    MetricDef("factual_precision", "Factual precision", "llm", "ratio",
              "Share of stated facts that are supported by the reference.", "Mean per-sample factual precision.",
              qi_weight=0.10, failure_threshold=0.5, method="external judge"),
    MetricDef("hallucination_rate", "Hallucination rate", "llm", "ratio",
              "Share of responses containing unsupported content.", "Mean per-sample hallucination indicator.",
              "lower_better", qi_weight=0.15, failure_threshold=0.5, method="external judge"),
    MetricDef("instruction_adherence", "Instruction adherence", "llm", "ratio",
              "How well responses follow the instructions given.", "Mean per-sample adherence score.",
              qi_weight=0.05, failure_threshold=0.5, method="external judge"),
    MetricDef("response_consistency", "Response consistency", "llm", "ratio",
              "Agreement between repeated responses to the same prompt.", "Mean pairwise agreement score.",
              qi_weight=0.05, failure_threshold=0.5, method="external judge"),
    MetricDef("rag_faithfulness", "RAG faithfulness", "rag", "ratio",
              "Share of answer claims grounded in retrieved context.", "Mean per-sample faithfulness.",
              qi_weight=0.15, failure_threshold=0.5, method="external judge"),
    MetricDef("context_precision", "Context precision", "rag", "ratio",
              "Share of retrieved documents that are relevant (precision@k).", "relevant_in_top_k / k",
              qi_weight=0.05, alias_prefixes=("precision_at_",), producer="built-in", method="precision@k",
              failure_threshold=0.5),
    MetricDef("context_recall", "Context recall", "rag", "ratio",
              "Share of relevant documents that were retrieved (recall@k).", "relevant_in_top_k / relevant_total",
              qi_weight=0.05, alias_prefixes=("recall_at_",), producer="built-in", method="recall@k",
              failure_threshold=0.5),
    MetricDef("answer_relevancy", "Answer relevancy", "rag", "ratio",
              "How relevant the generated answer is to the question.", "Mean per-sample relevancy score.",
              qi_weight=0.05, failure_threshold=0.5, method="external judge"),
    MetricDef("citation_accuracy", "Citation accuracy", "rag", "ratio",
              "Share of citations that point to supporting documents.", "Mean per-sample citation accuracy.",
              qi_weight=0.05, failure_threshold=0.5, method="external judge"),
    MetricDef("retrieval_ndcg", "Retrieval NDCG@K", "rag", "ratio",
              "Normalised discounted cumulative gain of the retrieved ranking.", "DCG@k / IDCG@k with binary relevance.",
              qi_weight=0.05, alias_prefixes=("ndcg_at_",), producer="built-in", method="ndcg@k",
              failure_threshold=0.5),
    MetricDef("agent_task_completion", "Agent task completion", "agent", "ratio",
              "Share of tasks whose verified outcome matches the expected outcome.", "Mean of per-trace completion (0/1).",
              qi_weight=0.10, aliases=("task_completion",), producer="built-in", method="outcome match",
              failure_threshold=0.5),
    MetricDef("tool_use_accuracy", "Tool-use accuracy", "agent", "ratio",
              "Share of tool calls that succeeded.", "SUCCESS steps / total steps per trace.",
              qi_weight=0.05, aliases=("tool_accuracy",), producer="built-in", method="step success rate",
              failure_threshold=0.5),
    MetricDef("agent_recovery_success", "Agent recovery success", "agent", "ratio",
              "Share of tool failures from which the agent recovered.", "Recovered failures / failures.",
              qi_weight=0.05, failure_threshold=0.5, method="external evaluator"),
    MetricDef("failure_rate", "Evaluation failure rate", "operations", "ratio",
              "Share of results with status FAILED or ERROR.", "(FAILED+ERROR)/results", "lower_better", "derived"),
    MetricDef("latency_median", "Median latency", "operations", "ms",
              "Median response latency.", "Median of result latency_ms.", "lower_better", "derived"),
    MetricDef("latency_p95", "P95 latency", "operations", "ms",
              "95th percentile response latency.", "Linear-interpolated 95th percentile of latency_ms.",
              "lower_better", "derived"),
    MetricDef("token_consumption", "Token consumption", "operations", "tokens",
              "Total tokens consumed by evaluated responses.", "SUM(token_count)", "neutral", "derived"),
    MetricDef("total_cost", "Total evaluation cost", "operations", "usd",
              "Total recorded evaluation cost.", "SUM(cost_usd)", "lower_better", "derived"),
    MetricDef("cost_per_success", "Cost per successful evaluation", "operations", "usd",
              "Recorded cost divided by results that did not fail.", "SUM(cost_usd)/COUNT(results WHERE status NOT IN (FAILED, ERROR))",
              "lower_better", "derived"),
    MetricDef("regression_alerts", "Regression alerts", "operations", "count",
              "Metrics whose latest run is worse than the previous comparable run.",
              "Latest vs previous run per (project, model, suite, metric); see /dashboard/alerts.",
              "lower_better", "derived"),
    MetricDef("confidence_intervals", "Metrics with 95% CI", "operations", "count",
              "Number of quality metrics with enough observations for a 95% t-interval.",
              "Metrics with n >= 2 and non-zero variance computation.", "neutral", "derived"),
]

CATALOG_BY_KEY: Dict[str, MetricDef] = {m.key: m for m in CATALOG}


def external_reason(m: MetricDef) -> str:
    if m.producer == "external":
        return f"No observations recorded for this metric. {_EXT}"
    return "No observations recorded for this metric in the selected scope (run the built-in evaluator or ingest scores)."


def resolve_catalog_key(raw_name: str) -> Optional[str]:
    """Map a metric name reported by an evaluator to a catalogue key."""
    name = (raw_name or "").strip().lower()
    if name in CATALOG_BY_KEY and CATALOG_BY_KEY[name].kind == "observation":
        return name
    for m in CATALOG:
        if m.kind != "observation":
            continue
        if name in m.aliases or any(name.startswith(p) for p in m.alias_prefixes):
            return m.key
    return None


def observation_metrics() -> List[MetricDef]:
    return [m for m in CATALOG if m.kind == "observation"]


def quality_weights() -> Dict[str, float]:
    from app.config import settings
    weights = {m.key: m.qi_weight for m in observation_metrics() if m.qi_weight > 0}
    if settings.QUALITY_INDEX_WEIGHTS_JSON:
        try:
            override = json.loads(settings.QUALITY_INDEX_WEIGHTS_JSON)
            for k, v in override.items():
                if k in CATALOG_BY_KEY and CATALOG_BY_KEY[k].kind == "observation" and float(v) >= 0:
                    weights[k] = float(v)
        except (ValueError, TypeError, AttributeError):
            pass
    return {k: v for k, v in weights.items() if v > 0}
