"""Dashboard aggregation: KPIs, Overall Quality Index, trends, alerts, comparison, drill-down.

Everything is computed from persisted rows (observations, results, runs). No value is
ever synthesised: when data is missing the KPI is reported as ``N/A`` with a reason.
"""
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import Integer, case, cast, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.entities import (
    EvaluationResult, EvaluationRun, MetricAggregate, MetricObservation, Project,
)
from app.services.events import latest_event_id
from app.services.metrics_catalog import (
    CATALOG, CATALOG_BY_KEY, CATALOG_VERSION, MetricDef, external_reason,
    observation_metrics, quality_weights,
)
from app.services.stats_utils import compare_samples, describe, describe_from_sums, percentile

FAILING = ("FAILED", "ERROR")
MAX_ROWS = 200_000


@dataclass(frozen=True)
class Filters:
    project_id: Optional[str] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    suite: Optional[str] = None
    dataset_version: Optional[str] = None
    run_id: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    run_ids: Optional[tuple] = None  # report scopes: several runs / models at once
    model_ids: Optional[tuple] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None

    def key(self) -> tuple:
        return tuple(sorted((k, str(v)) for k, v in self.__dict__.items() if v is not None))

    def public(self) -> Dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, datetime) else list(v) if isinstance(v, tuple) else v)
                for k, v in self.__dict__.items() if v is not None}


def parse_date(value: Optional[str], end_of_day: bool = False) -> Optional[datetime]:
    """Parse YYYY-MM-DD or ISO-8601 into naive UTC."""
    if not value:
        return None
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            start = datetime(d.year, d.month, d.day)
            return start + timedelta(days=1) - timedelta(microseconds=1) if end_of_day else start
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        raise ValueError(f"Invalid date: {value!r}")


# ----------------------------------------------------------------------------- query helpers
def _run_conditions(f: Filters) -> list:
    c = []
    for col, val in ((EvaluationRun.project_id, f.project_id), (EvaluationRun.provider, f.provider),
                     (EvaluationRun.model_id, f.model_id), (EvaluationRun.suite, f.suite),
                     (EvaluationRun.dataset_version, f.dataset_version), (EvaluationRun.id, f.run_id),
                     (EvaluationRun.category, f.category)):
        if val:
            c.append(col == val)
    if f.run_ids:
        c.append(EvaluationRun.id.in_(list(f.run_ids)))
    if f.model_ids:
        c.append(EvaluationRun.model_id.in_(list(f.model_ids)))
    return c


def _obs_select(f: Filters, *cols):
    q = select(*cols).select_from(MetricObservation).join(EvaluationRun, EvaluationRun.id == MetricObservation.run_id)
    if f.status:
        q = q.join(EvaluationResult, EvaluationResult.id == MetricObservation.result_id)
        q = q.where(EvaluationResult.status == f.status)
    for cond in _run_conditions(f):
        q = q.where(cond)
    if f.date_from:
        q = q.where(MetricObservation.created_at >= f.date_from)
    if f.date_to:
        q = q.where(MetricObservation.created_at <= f.date_to)
    return q


def _result_select(f: Filters, *cols):
    q = select(*cols).select_from(EvaluationResult).join(EvaluationRun, EvaluationRun.id == EvaluationResult.evaluation_run_id)
    for cond in _run_conditions(f):
        q = q.where(cond)
    if f.status:
        q = q.where(EvaluationResult.status == f.status)
    if f.date_from:
        q = q.where(EvaluationResult.created_at >= f.date_from)
    if f.date_to:
        q = q.where(EvaluationResult.created_at <= f.date_to)
    return q


def _run_select(f: Filters, *cols):
    q = select(*cols).select_from(EvaluationRun)
    for cond in _run_conditions(f):
        q = q.where(cond)
    if f.date_from:
        q = q.where(EvaluationRun.created_at >= f.date_from)
    if f.date_to:
        q = q.where(EvaluationRun.created_at <= f.date_to)
    return q


# ----------------------------------------------------------------------------- core aggregation
def metric_stats(db: Session, f: Filters) -> Dict[str, Dict[str, Any]]:
    q = _obs_select(f, MetricObservation.catalog_key, func.count(), func.sum(MetricObservation.value),
                    func.sum(MetricObservation.value * MetricObservation.value)
                    ).where(MetricObservation.catalog_key.is_not(None)).group_by(MetricObservation.catalog_key)
    return {k: describe_from_sums(int(n), float(s), float(sq)) for k, n, s, sq in db.execute(q).all()}


def _score(m: MetricDef, mean: float) -> float:
    s = min(max(mean, 0.0), 1.0)
    return 1.0 - s if m.direction == "lower_better" else s


def quality_index(stats: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    weights = quality_weights()
    total_w = sum(weights.values())
    components, missing = [], []
    for key, w in weights.items():
        m = CATALOG_BY_KEY[key]
        st = stats.get(key)
        n = st["n"] if st else 0
        if n == 0:
            missing.append({"key": key, "name": m.name, "weight": w, "reason": external_reason(m)})
        elif n < settings.MIN_OBSERVATIONS:
            missing.append({"key": key, "name": m.name, "weight": w,
                            "reason": f"Insufficient observations (n={n}, minimum {settings.MIN_OBSERVATIONS})."})
        else:
            components.append({"key": key, "name": m.name, "weight": w, "n": n,
                               "mean": st["mean"], "score": _score(m, st["mean"])})
    avail_w = sum(c["weight"] for c in components)
    coverage = avail_w / total_w if total_w else 0.0
    value, reason = None, None
    if not components:
        reason = "No quality metric has enough observations."
    elif coverage < settings.QI_MIN_COVERAGE:
        reason = (f"Metric coverage {coverage:.0%} is below the required {settings.QI_MIN_COVERAGE:.0%}; "
                  f"{len(missing)} metric(s) lack sufficient observations.")
    else:
        value = 100.0 * sum(c["weight"] * c["score"] for c in components) / avail_w
    return {"value": value, "na_reason": reason, "coverage": coverage, "components": components,
            "missing": missing, "method": "weighted mean of available metric scores; missing metrics excluded, "
            "weights re-normalised; N/A below minimum coverage", "min_coverage": settings.QI_MIN_COVERAGE,
            "min_observations": settings.MIN_OBSERVATIONS}


def quality_index_for_run(db: Session, run_id: str) -> Optional[float]:
    return quality_index(metric_stats(db, Filters(run_id=run_id)))["value"]


def _kpi(m: MetricDef, value=None, n=0, ci=None, reason=None, extra=None) -> Dict[str, Any]:
    d = {"key": m.key, "name": m.name, "category": m.category, "unit": m.unit, "direction": m.direction,
         "definition": m.definition, "value": value, "n_observations": n,
         "ci": list(ci) if ci else None, "status": "ok" if value is not None else "na",
         "na_reason": None if value is not None else reason}
    if extra:
        d.update(extra)
    return d


def operational(db: Session, f: Filters) -> Dict[str, Any]:
    ops: Dict[str, Any] = {}
    ops["total_runs"] = db.scalar(_run_select(f, func.count())) or 0
    active = replace(f, date_from=None, date_to=None)
    ops["active_jobs"] = db.scalar(_run_select(active, func.count()).where(EvaluationRun.status.in_(("PENDING", "RUNNING")))) or 0
    n_res, n_fail = db.execute(_result_select(f, func.count(), func.sum(
        case((EvaluationResult.status.in_(FAILING), 1), else_=0)))).one()
    ops["results"], ops["failed"] = int(n_res or 0), int(n_fail or 0)
    lat = [float(x) for x in db.scalars(_result_select(f, EvaluationResult.latency_ms)
                                        .where(EvaluationResult.latency_ms.is_not(None)).limit(MAX_ROWS))]
    ops["latencies"] = lat
    tok_n, tok_sum = db.execute(_result_select(f, func.count(EvaluationResult.token_count),
                                               func.sum(EvaluationResult.token_count))).one()
    ops["tokens_n"], ops["tokens"] = int(tok_n or 0), int(tok_sum or 0)
    c_n, c_sum = db.execute(_result_select(f, func.count(EvaluationResult.cost_usd), func.sum(EvaluationResult.cost_usd))).one()
    ops["cost_n"], ops["cost"] = int(c_n or 0), float(c_sum or 0.0)
    succ = db.scalar(_result_select(f, func.count()).where(EvaluationResult.cost_usd.is_not(None),
                                                           func.coalesce(EvaluationResult.status, "COMPLETED").not_in(FAILING))) or 0
    ops["cost_successes"] = int(succ)
    return ops


def build_kpis(db: Session, f: Filters, stats=None, alerts=None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    stats = stats if stats is not None else metric_stats(db, f)
    ops = operational(db, f)
    qi = quality_index(stats)
    alerts = alerts if alerts is not None else regression_alerts(db, f)
    minobs = settings.MIN_OBSERVATIONS
    out = []
    for m in CATALOG:
        k = m.key
        if k == "quality_index":
            out.append(_kpi(m, qi["value"], sum(c["n"] for c in qi["components"]), None, qi["na_reason"],
                            {"coverage": qi["coverage"]}))
        elif k == "total_runs":
            out.append(_kpi(m, ops["total_runs"], ops["total_runs"]))
        elif k == "active_jobs":
            out.append(_kpi(m, ops["active_jobs"], ops["active_jobs"]))
        elif m.kind == "observation":
            st = stats.get(k)
            n = st["n"] if st else 0
            if n == 0:
                out.append(_kpi(m, None, 0, None, external_reason(m)))
            elif n < minobs:
                out.append(_kpi(m, None, n, None, f"Insufficient observations (n={n}, minimum {minobs})."))
            else:
                ci = (st["ci_low"], st["ci_high"]) if st["ci_low"] is not None else None
                out.append(_kpi(m, st["mean"], n, ci, None))
        elif k == "failure_rate":
            r = ops["results"]
            out.append(_kpi(m, ops["failed"] / r if r else None, r, None, "No evaluation results recorded in this scope."))
        elif k in ("latency_median", "latency_p95"):
            lat = ops["latencies"]
            if len(lat) < minobs:
                out.append(_kpi(m, None, len(lat), None, "No latency recorded." if not lat else
                                f"Insufficient latency samples (n={len(lat)}, minimum {minobs})."))
            else:
                out.append(_kpi(m, percentile(lat, 50 if k == "latency_median" else 95), len(lat)))
        elif k == "token_consumption":
            out.append(_kpi(m, ops["tokens"] if ops["tokens_n"] else None, ops["tokens_n"], None, "No token counts recorded."))
        elif k == "total_cost":
            out.append(_kpi(m, ops["cost"] if ops["cost_n"] else None, ops["cost_n"], None, "No cost data recorded."))
        elif k == "cost_per_success":
            ok = ops["cost_n"] and ops["cost_successes"]
            out.append(_kpi(m, ops["cost"] / ops["cost_successes"] if ok else None, ops["cost_successes"], None,
                            "No cost data recorded." if not ops["cost_n"] else "No successful evaluations with recorded cost."))
        elif k == "regression_alerts":
            out.append(_kpi(m, len(alerts), len(alerts)))
        elif k == "confidence_intervals":
            cnt = sum(1 for s in stats.values() if s["ci_low"] is not None)
            out.append(_kpi(m, cnt if cnt else None, cnt, None, "No metric has at least 2 observations."))
    return out, {"ops": ops, "qi": qi, "stats": stats}


# ----------------------------------------------------------------------------- charts
def _per_model_stats(db: Session, f: Filters) -> Dict[str, Dict[str, Dict[str, Any]]]:
    q = _obs_select(f, EvaluationRun.model_id, MetricObservation.catalog_key, func.count(),
                    func.sum(MetricObservation.value), func.sum(MetricObservation.value * MetricObservation.value)
                    ).where(MetricObservation.catalog_key.is_not(None)).group_by(EvaluationRun.model_id, MetricObservation.catalog_key)
    out: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for model, key, n, s, sq in db.execute(q).all():
        out[model or "unknown"][key] = describe_from_sums(int(n), float(s), float(sq))
    return out


def build_charts(db: Session, f: Filters, ctx: Dict[str, Any], alerts: List[dict]) -> Dict[str, Any]:
    per_model = _per_model_stats(db, f)
    ranking = []
    for model, st in per_model.items():
        qi = quality_index(st)
        ranking.append({"model_id": model, "quality_index": qi["value"], "coverage": qi["coverage"],
                        "na_reason": qi["na_reason"], "n_metrics": len(qi["components"])})
    ranking.sort(key=lambda r: (r["quality_index"] is None, -(r["quality_index"] or 0)))
    for i, r in enumerate([r for r in ranking if r["quality_index"] is not None], 1):
        r["rank"] = i

    def mean_of(st, key):
        s = st.get(key)
        return s["mean"] if s and s["n"] >= settings.MIN_OBSERVATIONS else None

    rag = [{"model_id": m, "retrieval": {k: mean_of(st, k) for k in ("context_precision", "context_recall", "retrieval_ndcg")},
            "generation": {k: mean_of(st, k) for k in ("rag_faithfulness", "answer_relevancy", "citation_accuracy")}}
           for m, st in per_model.items()
           if any(k in st for k in ("context_precision", "context_recall", "retrieval_ndcg", "rag_faithfulness",
                                    "answer_relevancy", "citation_accuracy"))]
    llm = [{"model_id": m, **{k: mean_of(st, k) for k in ("llm_correctness", "factual_precision", "hallucination_rate",
                                                         "instruction_adherence", "response_consistency")}}
           for m, st in per_model.items() if any(CATALOG_BY_KEY[k].category == "llm" for k in st)]

    res_rows = db.execute(_result_select(f, EvaluationRun.model_id, EvaluationRun.category, EvaluationResult.status,
                                         EvaluationResult.error_type, func.count())
                          .group_by(EvaluationRun.model_id, EvaluationRun.category, EvaluationResult.status,
                                    EvaluationResult.error_type)).all()
    agent_outcomes: Dict[str, Dict[str, int]] = defaultdict(lambda: {"success": 0, "failure": 0, "unjudged": 0})
    failure_cls: Dict[str, int] = defaultdict(int)
    for model, cat, status, err, n in res_rows:
        if status in FAILING:
            failure_cls[err or f"{status} (unclassified)"] += n
        if cat == "agent":
            bucket = "failure" if status in FAILING else ("success" if status in ("PASSED", "COMPLETED") else "unjudged")
            agent_outcomes[model or "unknown"][bucket] += n

    lat_rows = db.execute(_result_select(f, EvaluationRun.model_id, EvaluationResult.latency_ms)
                          .where(EvaluationResult.latency_ms.is_not(None)).limit(MAX_ROWS)).all()
    lat_by_model: Dict[str, List[float]] = defaultdict(list)
    for model, v in lat_rows:
        lat_by_model[model or "unknown"].append(float(v))
    latency = [{"model_id": m, "n": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95), "p99": percentile(v, 99)}
               for m, v in lat_by_model.items()]

    usage_rows = db.execute(_result_select(f, EvaluationRun.model_id, func.count(), func.sum(EvaluationResult.token_count),
                                           func.sum(EvaluationResult.cost_usd), func.count(EvaluationResult.cost_usd))
                            .group_by(EvaluationRun.model_id)).all()
    usage = [{"model_id": m or "unknown", "results": n, "tokens": int(t) if t is not None else None,
              "cost_usd": float(c) if cn else None} for m, n, t, c, cn in usage_rows]

    bins = db.execute(_obs_select(f, MetricObservation.catalog_key, cast(MetricObservation.value * 10, Integer), func.count())
                      .where(MetricObservation.catalog_key.is_not(None))
                      .group_by(MetricObservation.catalog_key, cast(MetricObservation.value * 10, Integer))).all()
    dist: Dict[str, List[int]] = {}
    for key, b, n in bins:
        arr = dist.setdefault(key, [0] * 10)
        arr[min(max(int(b), 0), 9)] += int(n)
    distributions = [{"metric_key": k, "name": CATALOG_BY_KEY[k].name, "bins": [i / 10 for i in range(10)], "counts": c}
                     for k, c in dist.items()]

    cis = [{"metric_key": k, "name": CATALOG_BY_KEY[k].name, "mean": s["mean"], "ci_low": s["ci_low"],
            "ci_high": s["ci_high"], "n": s["n"]}
           for k, s in ctx["stats"].items() if s["n"] >= settings.MIN_OBSERVATIONS and s["ci_low"] is not None]
    return {"model_ranking": ranking, "rag_quality": rag, "llm_performance": llm,
            "agent_outcomes": [{"model_id": m, **v} for m, v in agent_outcomes.items()],
            "failure_classification": [{"classification": k, "count": v} for k, v in
                                       sorted(failure_cls.items(), key=lambda kv: -kv[1])],
            "latency_percentiles": latency, "usage": usage, "distributions": distributions,
            "confidence_intervals": cis,
            "regression": [{"metric_key": a["metric_key"], "name": a["name"], "model_id": a["model_id"],
                            "previous": a["previous_mean"], "latest": a["latest_mean"], "severity": a["severity"]}
                           for a in alerts]}


def filter_options(db: Session) -> Dict[str, Any]:
    def distinct(col):
        return [v for v in db.scalars(select(col).where(col.is_not(None)).distinct().order_by(col).limit(200))]
    runs = db.execute(select(EvaluationRun.id, EvaluationRun.model_id, EvaluationRun.suite, EvaluationRun.status,
                             EvaluationRun.created_at).order_by(EvaluationRun.created_at.desc()).limit(100)).all()
    return {"projects": [{"id": i, "name": n} for i, n in db.execute(select(Project.id, Project.name).order_by(Project.name).limit(200))],
            "providers": distinct(EvaluationRun.provider), "model_ids": distinct(EvaluationRun.model_id),
            "suites": distinct(EvaluationRun.suite), "dataset_versions": distinct(EvaluationRun.dataset_version),
            "categories": ["llm", "rag", "agent"], "statuses": ["PASSED", "FAILED", "ERROR", "COMPLETED"],
            "runs": [{"id": i, "model_id": m, "suite": s, "status": st, "created_at": c.isoformat() + "Z"} for i, m, s, st, c in runs]}


# ----------------------------------------------------------------------------- cache for expensive payloads
class _Cache:
    def __init__(self, size=64, ttl=30.0):
        self.size, self.ttl, self._d, self._lock = size, ttl, OrderedDict(), threading.Lock()

    def get(self, key):
        with self._lock:
            hit = self._d.get(key)
            if hit and (datetime.utcnow() - hit[0]).total_seconds() < self.ttl:
                self._d.move_to_end(key)
                return hit[1]
            return None

    def put(self, key, value):
        with self._lock:
            self._d[key] = (datetime.utcnow(), value)
            while len(self._d) > self.size:
                self._d.popitem(last=False)

    def clear(self):
        with self._lock:
            self._d.clear()


_overview_cache = _Cache()


def clear_cache():
    _overview_cache.clear()


def overview(db: Session, f: Filters) -> Dict[str, Any]:
    """Full dashboard state. Cached per (latest event id, filters): repeated polls/refetches
    between events cost one cheap MAX(id) query."""
    last_id = latest_event_id(db)
    ck = (settings.DATABASE_URL, last_id, f.key())
    cached = _overview_cache.get(ck)
    if cached is not None:
        return cached
    alerts = regression_alerts(db, f)
    kpis, ctx = build_kpis(db, f, alerts=alerts)
    payload = {"generated_at": datetime.utcnow().isoformat() + "Z", "last_event_id": last_id,
               "catalog_version": CATALOG_VERSION, "filters": f.public(), "kpis": kpis,
               "quality_index": ctx["qi"], "charts": build_charts(db, f, ctx, alerts),
               "options": filter_options(db), "has_data": ctx["ops"]["results"] > 0 or ctx["ops"]["total_runs"] > 0}
    _overview_cache.put(ck, payload)
    return payload


# ----------------------------------------------------------------------------- trends
def _bucket(dt: datetime, bucket: str) -> str:
    return dt.strftime("%Y-%m-%dT%H:00:00Z") if bucket == "hour" else dt.strftime("%Y-%m-%dT00:00:00Z")


TREND_OPERATIONAL = {"latency_p95", "latency_median", "tokens", "cost", "runs", "failure_rate", "results"}


def trends(db: Session, f: Filters, metric: str = "quality_index", bucket: str = "day") -> Dict[str, Any]:
    if bucket not in ("day", "hour"):
        raise ValueError("bucket must be 'day' or 'hour'")
    series: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    unit, na = "ratio", None
    if metric == "quality_index":
        unit = "index"
        rows = db.execute(_obs_select(f, EvaluationRun.model_id, MetricObservation.created_at, MetricObservation.catalog_key,
                                      MetricObservation.value).where(MetricObservation.catalog_key.is_not(None)).limit(MAX_ROWS)).all()
        grouped: Dict[Tuple[str, str], Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        for model, ts, key, val in rows:
            grouped[(model or "unknown", _bucket(ts, bucket))][key].append(val)
        for (model, t), by_key in grouped.items():
            st = {k: describe(v) for k, v in by_key.items()}
            qi = quality_index(st)
            if qi["value"] is not None:
                series[model][t] = [qi["value"], sum(c["n"] for c in qi["components"])]
    elif metric in CATALOG_BY_KEY and CATALOG_BY_KEY[metric].kind == "observation":
        rows = db.execute(_obs_select(f, EvaluationRun.model_id, MetricObservation.created_at, MetricObservation.value)
                          .where(MetricObservation.catalog_key == metric).limit(MAX_ROWS)).all()
        tmp: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        for model, ts, val in rows:
            tmp[(model or "unknown", _bucket(ts, bucket))].append(val)
        for (model, t), vals in tmp.items():
            if len(vals) >= 1:
                series[model][t] = [sum(vals) / len(vals), len(vals)]
    elif metric in TREND_OPERATIONAL:
        unit = {"latency_p95": "ms", "latency_median": "ms", "tokens": "tokens", "cost": "usd",
                "runs": "count", "failure_rate": "ratio", "results": "count"}[metric]
        if metric == "runs":
            rows = db.execute(_run_select(f, EvaluationRun.model_id, EvaluationRun.created_at)).all()
            for model, ts in rows:
                cell = series[model or "unknown"].setdefault(_bucket(ts, bucket), [0, 0])
                cell[0] += 1
                cell[1] += 1
        else:
            rows = db.execute(_result_select(f, EvaluationRun.model_id, EvaluationResult.created_at, EvaluationResult.latency_ms,
                                             EvaluationResult.token_count, EvaluationResult.cost_usd, EvaluationResult.status)
                              .limit(MAX_ROWS)).all()
            tmp2: Dict[Tuple[str, str], list] = defaultdict(list)
            for model, ts, lat, tok, cost, status in rows:
                tmp2[(model or "unknown", _bucket(ts, bucket))].append((lat, tok, cost, status))
            for (model, t), items in tmp2.items():
                if metric.startswith("latency"):
                    vals = [i[0] for i in items if i[0] is not None]
                    v = percentile(vals, 95 if metric == "latency_p95" else 50) if vals else None
                    n = len(vals)
                elif metric == "tokens":
                    vals = [i[1] for i in items if i[1] is not None]
                    v, n = (sum(vals) if vals else None), len(vals)
                elif metric == "cost":
                    vals = [i[2] for i in items if i[2] is not None]
                    v, n = (sum(vals) if vals else None), len(vals)
                elif metric == "failure_rate":
                    v, n = sum(1 for i in items if i[3] in FAILING) / len(items), len(items)
                else:
                    v, n = len(items), len(items)
                if v is not None:
                    series[model][t] = [v, n]
    else:
        raise ValueError(f"Unknown trend metric: {metric}")
    out = [{"model_id": model, "points": [{"t": t, "value": v[0], "n": v[1]} for t, v in sorted(pts.items())]}
           for model, pts in sorted(series.items())]
    if not out:
        na = "No persisted data for this metric in the selected scope."
    return {"metric": metric, "unit": unit, "bucket": bucket, "series": out, "na_reason": na,
            "last_event_id": latest_event_id(db), "filters": f.public()}


# ----------------------------------------------------------------------------- regression alerts
def regression_alerts(db: Session, f: Filters) -> List[Dict[str, Any]]:
    q = select(EvaluationRun.id, EvaluationRun.project_id, EvaluationRun.model_id, EvaluationRun.suite,
               EvaluationRun.category, EvaluationRun.created_at).where(EvaluationRun.status == "COMPLETED")
    for cond in _run_conditions(replace(f, run_id=None)):
        q = q.where(cond)
    rows = db.execute(q.order_by(EvaluationRun.created_at.desc()).limit(2000)).all()
    groups: Dict[tuple, List[tuple]] = defaultdict(list)
    for r in rows:
        groups[(r.project_id, r.model_id, r.suite, r.category)].append(r)
    alerts: List[Dict[str, Any]] = []
    for gk, runs in groups.items():
        latest_idx = 0
        if f.run_id:
            idx = [i for i, r in enumerate(runs) if r.id == f.run_id]
            if not idx:
                continue
            latest_idx = idx[0]
        if latest_idx + 1 >= len(runs):
            continue
        latest, prev = runs[latest_idx], runs[latest_idx + 1]
        aggs = {}
        for rid in (latest.id, prev.id):
            aggs[rid] = {a.catalog_key: a for a in db.scalars(select(MetricAggregate).where(MetricAggregate.run_id == rid))}
        for key, a_l in aggs[latest.id].items():
            a_p = aggs[prev.id].get(key)
            m = CATALOG_BY_KEY.get(key)
            if a_p is None or m is None or min(a_l.n, a_p.n) < settings.MIN_OBSERVATIONS:
                continue
            sign = -1.0 if m.direction == "lower_better" else 1.0
            drop = sign * (a_p.mean - a_l.mean)
            if drop < settings.REGRESSION_DROP_THRESHOLD:
                continue
            vals = {rid: [float(x) for x in db.scalars(select(MetricObservation.value).where(
                MetricObservation.run_id == rid, MetricObservation.catalog_key == key))] for rid in (latest.id, prev.id)}
            test = compare_samples(vals[prev.id], vals[latest.id])
            significant = bool(test.get("testable") and test.get("significant"))
            alerts.append({
                "id": f"{latest.id}:{key}", "severity": "critical" if significant else "warning",
                "metric_key": key, "name": m.name, "project_id": latest.project_id, "model_id": latest.model_id,
                "suite": latest.suite, "latest_run_id": latest.id, "previous_run_id": prev.id,
                "latest_mean": a_l.mean, "previous_mean": a_p.mean, "delta": a_l.mean - a_p.mean,
                "n_latest": a_l.n, "n_previous": a_p.n, "testable": bool(test.get("testable")),
                "p_value": test.get("p_value"), "ci": [test["ci_low"], test["ci_high"]] if test.get("testable") else None,
                "message": (f"{m.name} {'worsened' if sign > 0 else 'increased'} by {abs(a_l.mean - a_p.mean):.3f} "
                            f"versus the previous run" + (" (statistically significant, Welch t-test)." if significant
                                                         else " (not statistically confirmed).")),
            })
    alerts.sort(key=lambda a: (a["severity"] != "critical", -abs(a["delta"])))
    return alerts


# ----------------------------------------------------------------------------- comparison
def compare(db: Session, f: Filters, a: Dict[str, str], b: Dict[str, str]) -> Dict[str, Any]:
    """Side-by-side comparison of two model configurations or two runs (``{'model_id':..}`` / ``{'run_id':..}``)."""
    allowed = {"model_id", "run_id", "provider", "suite", "dataset_version"}
    if not a or not b or not set(a) <= allowed or not set(b) <= allowed:
        raise ValueError("Each comparison side needs one of: " + ", ".join(sorted(allowed)))
    fa, fb = replace(f, **a), replace(f, **b)
    kpis_a, ctx_a = build_kpis(db, fa, alerts=[])
    kpis_b, ctx_b = build_kpis(db, fb, alerts=[])
    rows = []
    for m in observation_metrics():
        va = [float(x) for x in db.scalars(_obs_select(fa, MetricObservation.value).where(MetricObservation.catalog_key == m.key).limit(MAX_ROWS))]
        vb = [float(x) for x in db.scalars(_obs_select(fb, MetricObservation.value).where(MetricObservation.catalog_key == m.key).limit(MAX_ROWS))]
        da, db_ = describe(va), describe(vb)
        enough = len(va) >= settings.MIN_OBSERVATIONS and len(vb) >= settings.MIN_OBSERVATIONS
        row = {"key": m.key, "name": m.name, "unit": m.unit, "direction": m.direction, "a": da, "b": db_,
               "delta": (db_["mean"] - da["mean"]) if enough else None, "test": None, "na_reason": None}
        if not enough:
            row["na_reason"] = (f"Insufficient observations (A n={len(va)}, B n={len(vb)}, minimum {settings.MIN_OBSERVATIONS}).")
        else:
            row["test"] = compare_samples(va, vb)
        rows.append(row)
    return {"a": {"filters": a, "kpis": kpis_a, "quality_index": ctx_a["qi"]},
            "b": {"filters": b, "kpis": kpis_b, "quality_index": ctx_b["qi"]},
            "metrics": rows, "last_event_id": latest_event_id(db), "generated_at": datetime.utcnow().isoformat() + "Z"}


# ----------------------------------------------------------------------------- drill-down
def metric_detail(db: Session, f: Filters, key: str) -> Dict[str, Any]:
    m = CATALOG_BY_KEY.get(key)
    if m is None:
        raise KeyError(key)
    kpis, ctx = build_kpis(db, f)
    kpi = next(k for k in kpis if k["key"] == key)
    detail: Dict[str, Any] = {"metric": m.public(), "kpi": kpi, "filters": f.public(),
                              "evaluation_method": {"method": m.method or m.calculation, "version": m.method_version,
                                                    "producer": m.producer},
                              "failed_cases": [], "related_cases": [], "models": [], "dataset_versions": [],
                              "evidence_refs": [], "trend": None, "distribution": None}
    if m.kind == "observation":
        threshold = m.failure_threshold if m.failure_threshold is not None else 0.5
        bad = (MetricObservation.value > threshold) if m.direction == "lower_better" else (MetricObservation.value < threshold)
        cols = (MetricObservation.id, MetricObservation.sample_id, MetricObservation.result_id, MetricObservation.run_id,
                MetricObservation.value, MetricObservation.metric_key, EvaluationRun.model_id, EvaluationRun.dataset_version,
                EvaluationResult.prompt, EvaluationResult.mubit_request_id, EvaluationResult.status, EvaluationResult.error_type)

        def case_q():
            q = (select(*cols).select_from(MetricObservation).join(EvaluationRun, EvaluationRun.id == MetricObservation.run_id)
                 .outerjoin(EvaluationResult, EvaluationResult.id == MetricObservation.result_id)
                 .where(MetricObservation.catalog_key == key))
            for c in _run_conditions(f):
                q = q.where(c)
            if f.status:
                q = q.where(EvaluationResult.status == f.status)
            if f.date_from:
                q = q.where(MetricObservation.created_at >= f.date_from)
            if f.date_to:
                q = q.where(MetricObservation.created_at <= f.date_to)
            return q

        def to_case(r):
            return {"observation_id": r[0], "sample_id": r[1], "result_id": r[2], "run_id": r[3], "value": r[4],
                    "raw_metric": r[5], "model_id": r[6], "dataset_version": r[7], "prompt_excerpt": (r[8] or "")[:200],
                    "mubit_request_id": r[9], "status": r[10], "error_type": r[11],
                    "evidence_ref": f"result:{r[2]}" if r[2] else f"run:{r[3]}"}
        worst_order = MetricObservation.value.desc() if m.direction == "lower_better" else MetricObservation.value.asc()
        detail["failed_cases"] = [to_case(r) for r in db.execute(case_q().where(bad).order_by(worst_order).limit(25)).all()]
        detail["related_cases"] = [to_case(r) for r in db.execute(case_q().order_by(MetricObservation.created_at.desc()).limit(10)).all()]
        detail["models"] = sorted({r[0] or "unknown" for r in db.execute(_obs_select(f, EvaluationRun.model_id).where(MetricObservation.catalog_key == key).distinct())})
        detail["dataset_versions"] = sorted({r[0] for r in db.execute(_obs_select(f, EvaluationRun.dataset_version).where(MetricObservation.catalog_key == key).distinct()) if r[0]})
        detail["evidence_refs"] = sorted({c["evidence_ref"] for c in detail["failed_cases"]})
        bins = [0] * 10
        for b, n in db.execute(_obs_select(f, cast(MetricObservation.value * 10, Integer), func.count())
                               .where(MetricObservation.catalog_key == key).group_by(cast(MetricObservation.value * 10, Integer))):
            bins[min(max(int(b), 0), 9)] += int(n)
        detail["distribution"] = {"bins": [i / 10 for i in range(10)], "counts": bins}
        detail["failure_threshold"] = threshold
    else:
        failed = db.execute(_result_select(f, EvaluationResult.id, EvaluationResult.sample_id, EvaluationResult.evaluation_run_id,
                                           EvaluationResult.status, EvaluationResult.error_type, EvaluationRun.model_id,
                                           EvaluationRun.dataset_version, EvaluationResult.mubit_request_id)
                            .where(EvaluationResult.status.in_(FAILING)).order_by(EvaluationResult.created_at.desc()).limit(25)).all()
        detail["failed_cases"] = [{"result_id": r[0], "sample_id": r[1], "run_id": r[2], "status": r[3], "error_type": r[4],
                                  "model_id": r[5], "dataset_version": r[6], "mubit_request_id": r[7],
                                  "evidence_ref": f"result:{r[0]}"} for r in failed]
        detail["evidence_refs"] = [c["evidence_ref"] for c in detail["failed_cases"]]
    trend_metric = key if (m.kind == "observation" or key in TREND_OPERATIONAL or key == "quality_index") else None
    trend_metric = {"total_cost": "cost", "token_consumption": "tokens", "total_runs": "runs"}.get(key, trend_metric)
    if trend_metric:
        detail["trend"] = trends(db, f, trend_metric, "day")
    return detail


# ----------------------------------------------------------------------------- legacy summary
def legacy_summary(db: Session) -> Dict[str, Any]:
    kpis, ctx = build_kpis(db, Filters(), alerts=[])
    by = {k["key"]: k for k in kpis}

    def pct(k):
        v = by[k]["value"]
        return None if v is None else round(v * 100, 2)
    return {"quality_index": None if by["quality_index"]["value"] is None else round(by["quality_index"]["value"], 2),
            "total_evaluations": by["total_runs"]["value"], "llm_correctness": pct("llm_correctness"),
            "rag_faithfulness": pct("rag_faithfulness"), "agent_completion": pct("agent_task_completion"),
            "verified_failures": ctx["ops"]["failed"], "avg_latency_ms": by["latency_median"]["value"],
            "eval_cost_usd": by["total_cost"]["value"], "is_demo_data": False}
