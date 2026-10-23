"""Claude-assisted storyboard generation with deterministic grounding validation.

Claude only writes prose (narration / on-screen text / recommendations). Every number that
is *rendered* as a KPI or chart comes from the immutable snapshot, never from this module's
output. Numeric claims inside prose are checked against the snapshot and flagged when they
cannot be matched, so a human has to acknowledge them before rendering.
"""
import json
import logging
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import settings
from app.services.mubit_gateway import GatewayError, MubitGateway
from app.services.snapshot import CHART_IDS

logger = logging.getLogger("evalforge.narrative")

STORYBOARD_SCHEMA_VERSION = "1.0"
SCENE_TYPES = ["title", "kpis", "llm", "rag", "agent", "failures", "stats", "recommendations", "closing"]
SECTION_ALIASES = {"title": "title", "kpis": "kpis", "llm": "llm", "rag": "rag", "agent": "agent", "failures": "failures",
                   "stats": "stats", "recommendations": "recommendations", "closing": "closing"}
DURATION_TARGETS = (60, 120, 180)
MAX_SCENES = 14


class NarrativeError(ValueError):
    """The model response could not be used (malformed or ungrounded)."""


class Finding(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    evidence_refs: List[str] = Field(default_factory=list, max_length=12)


class ChartExplanation(BaseModel):
    chart_id: str = Field(max_length=60)
    text: str = Field(min_length=1, max_length=600)


class Recommendation(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    priority: str = "medium"
    evidence_refs: List[str] = Field(default_factory=list, max_length=12)

    @field_validator("priority")
    @classmethod
    def _p(cls, v):
        if v not in ("high", "medium", "low"):
            raise ValueError("priority must be high|medium|low")
        return v


class Scene(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: str
    title: str = Field(min_length=1, max_length=120)
    on_screen_text: List[str] = Field(default_factory=list, max_length=6)
    narration: str = Field(default="", max_length=1200)
    duration_seconds: float = Field(ge=2, le=60)
    metric_refs: List[str] = Field(default_factory=list, max_length=20)
    evidence_refs: List[str] = Field(default_factory=list, max_length=20)

    @field_validator("type")
    @classmethod
    def _t(cls, v):
        if v not in SCENE_TYPES:
            raise ValueError(f"scene type must be one of {SCENE_TYPES}")
        return v

    @field_validator("on_screen_text")
    @classmethod
    def _o(cls, v):
        if any(len(x) > 200 for x in v):
            raise ValueError("on_screen_text lines must be <= 200 characters")
        return v


class Storyboard(BaseModel):
    schema_version: str = STORYBOARD_SCHEMA_VERSION
    title: str = Field(min_length=1, max_length=200)
    executive_narrative: str = Field(default="", max_length=3000)
    key_findings: List[Finding] = Field(default_factory=list, max_length=12)
    chart_explanations: List[ChartExplanation] = Field(default_factory=list, max_length=12)
    failure_analysis: str = Field(default="", max_length=3000)
    statistical_interpretation: str = Field(default="", max_length=3000)
    recommendations: List[Recommendation] = Field(default_factory=list, max_length=12)
    scenes: List[Scene] = Field(min_length=1, max_length=MAX_SCENES)
    total_duration_seconds: float = 0

    def normalised(self) -> "Storyboard":
        self.total_duration_seconds = round(sum(s.duration_seconds for s in self.scenes), 2)
        return self


# ----------------------------------------------------------------------------- grounding
_NUM_RE = re.compile(r"(?<![\w.:/-])[-+]?\d[\d,]*(?:\.\d+)?%?")
_STRIP_RE = [re.compile(r"\b(?:metric|run|model|result|stat|chart):[^\s,;)\]]+"),   # evidence refs
             re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)?"),  # ISO dates / times
             re.compile(r"\b[A-Za-z]+[-_]\d+[A-Za-z0-9._-]*"),                             # identifiers like model-3, gpt-4o
             re.compile(r"@\d+\b|\bk\s*=\s*\d+|\b(?:NDCG|Recall|Precision)@\d+|\bp\d{2}\b", re.I)]  # NDCG@5, p95, k=3


def _render(v: float) -> Set[str]:
    out: Set[str] = set()
    for dp in range(0, 5):
        r = round(v, dp)
        s = f"{r:.{dp}f}"
        out.add(s)
        out.add(s.rstrip("0").rstrip(".") if "." in s else s)
    return out


def _numbers_in(obj: Any, acc: List[float]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and not math.isfinite(obj):
            return
        acc.append(float(obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("evidence_index", "id", "snapshot_id", "result_id", "run_id", "sample_id"):
                continue
            _numbers_in(v, acc)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, acc)


def allowed_numbers(payload: Dict[str, Any]) -> Set[str]:
    """Every textual rendering of every number in the snapshot: raw, rounded, and x100 percentages."""
    vals: List[float] = []
    _numbers_in(payload, vals)
    vals += [len(payload.get("runs") or []), len(payload.get("models") or []), len(payload.get("dataset_versions") or []),
             len(payload.get("statistical_results") or []), len(payload.get("recommendations") or []),
             len(payload.get("limitations") or []), len((payload.get("quality_index") or {}).get("missing") or []),
             len((payload.get("quality_index") or {}).get("components") or []),
             sum(1 for m in payload.get("metrics") or [] if m.get("value") is not None),
             sum(1 for m in payload.get("metrics") or [] if m.get("value") is None)]
    allowed: Set[str] = set()
    for v in vals:
        allowed |= _render(v)
        allowed |= _render(abs(v))
        if abs(v) <= 1.0:
            allowed |= _render(v * 100)
            allowed |= _render(abs(v) * 100)
    return allowed


def extract_numbers(text: str) -> List[str]:
    cleaned = text
    for rx in _STRIP_RE:
        cleaned = rx.sub(" ", cleaned)
    out = []
    for m in _NUM_RE.finditer(cleaned):
        tok = m.group(0).rstrip("%").replace(",", "").lstrip("+")
        if tok:
            out.append(tok)
    return out


def _is_supported(tok: str, allowed: Set[str]) -> bool:
    forms = {tok, tok.lstrip("-")}
    if "." in tok:
        forms.add(tok.rstrip("0").rstrip("."))
        forms.add(tok.lstrip("-").rstrip("0").rstrip("."))
    return bool(forms & allowed)


def _texts(sb: Storyboard) -> Iterable[Tuple[Optional[str], str, str]]:
    yield None, "executive_narrative", sb.executive_narrative
    yield None, "failure_analysis", sb.failure_analysis
    yield None, "statistical_interpretation", sb.statistical_interpretation
    for i, f in enumerate(sb.key_findings):
        yield None, f"key_findings[{i}]", f.text
    for i, c in enumerate(sb.chart_explanations):
        yield None, f"chart_explanations[{i}]", c.text
    for i, r in enumerate(sb.recommendations):
        yield None, f"recommendations[{i}]", r.text
    for s in sb.scenes:
        yield s.id, "title", s.title
        yield s.id, "narration", s.narration
        for j, line in enumerate(s.on_screen_text):
            yield s.id, f"on_screen_text[{j}]", line


def _refs(sb: Storyboard) -> Iterable[Tuple[Optional[str], List[str]]]:
    for f in sb.key_findings:
        yield None, f.evidence_refs
    for r in sb.recommendations:
        yield None, r.evidence_refs
    for s in sb.scenes:
        yield s.id, s.metric_refs + s.evidence_refs


_SIG_RE = re.compile(r"\bsignifican(?:t|tly|ce)\b", re.I)
_NOT_SIG_RE = re.compile(r"\b(?:not|no|non|insufficient|without)\b[^.]{0,30}\bsignifican", re.I)
_CAUSAL_RE = re.compile(r"\b(?:caused by|because of|due to|is responsible for|root cause)\b", re.I)


def validate_grounding(sb: Storyboard, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic checks. Returns {ok, flags[{scene_id,type,severity,message}], stats}. ``ok`` is True only with no flags."""
    allowed = allowed_numbers(payload)
    index = set(payload.get("evidence_index") or [])
    flags: List[Dict[str, Any]] = []
    checked = unsupported = 0
    for scene_id, where, text in _texts(sb):
        for tok in extract_numbers(text):
            checked += 1
            if not _is_supported(tok, allowed):
                unsupported += 1
                flags.append({"scene_id": scene_id, "type": "unsupported_number", "severity": "error",
                              "message": f"'{tok}' in {where} does not match any value in the report snapshot."})
    for scene_id, refs in _refs(sb):
        for r in refs:
            if r not in index:
                flags.append({"scene_id": scene_id, "type": "unknown_reference", "severity": "error",
                              "message": f"Reference '{r}' does not exist in the snapshot evidence index."})
    sig_ok = any(s.get("testable") and s.get("significant") for s in payload.get("statistical_results") or [])
    causal_re_seen = False
    for scene_id, where, text in _texts(sb):
        if not sig_ok and _SIG_RE.search(text) and not _NOT_SIG_RE.search(text):
            flags.append({"scene_id": scene_id, "type": "unsupported_significance", "severity": "error",
                          "message": f"{where} claims statistical significance but no statistically significant result exists in the snapshot."})
        if _CAUSAL_RE.search(text):
            causal_re_seen = True
            flags.append({"scene_id": scene_id, "type": "causal_language", "severity": "warning",
                          "message": f"{where} uses causal wording; evaluation data alone does not establish causes."})
    known_charts = set((payload.get("chart_datasets") or {}).keys()) or set(CHART_IDS)
    for c in sb.chart_explanations:
        if c.chart_id not in known_charts:
            flags.append({"scene_id": None, "type": "unknown_chart", "severity": "error",
                          "message": f"chart_id '{c.chart_id}' is not part of this snapshot."})
    return {"ok": not flags, "flags": flags, "numbers_checked": checked, "numbers_unsupported": unsupported}


def parse_storyboard(raw: str) -> Storyboard:
    """Accepts bare JSON or JSON in a fenced block / surrounded by prose; raises NarrativeError otherwise."""
    if not raw or not raw.strip():
        raise NarrativeError("Empty model response.")
    text = raw.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    if not text.startswith("{"):
        a, b = text.find("{"), text.rfind("}")
        if a == -1 or b <= a:
            raise NarrativeError("Model response contains no JSON object.")
        text = text[a:b + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise NarrativeError(f"Model response is not valid JSON: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise NarrativeError("Model response JSON must be an object.")
    try:
        return Storyboard.model_validate(data).normalised()
    except ValidationError as exc:
        first = exc.errors()[0]
        raise NarrativeError(f"Storyboard schema violation at {'.'.join(str(p) for p in first['loc'])}: {first['msg']}") from exc


# ----------------------------------------------------------------------------- prompts
SYSTEM_PROMPT = """You are an evaluation analyst writing a short video briefing from an immutable AI-evaluation report snapshot.
Rules (strict):
- Use ONLY facts and numbers present in the snapshot JSON. Never introduce a number that is not in it. Copy metric values with their units (ratio metrics as percentages).
- Metrics whose status is "na" must be described as not available with the supplied reason; never estimate them.
- Keep observations and recommendations separate. Do not invent causes; do not claim statistical significance unless a statistical result has significant=true; mention sample sizes and confidence intervals where relevant.
- Cite evidence in evidence_refs / metric_refs using ONLY ids from the snapshot evidence_index (e.g. "metric:llm_correctness", "stat:stat-1", "run:<id>").
- Do not quote prompts, answers or other source content.
- Respond with ONE JSON object and nothing else, matching this schema:
{"schema_version":"1.0","title":str,"executive_narrative":str,"key_findings":[{"text":str,"evidence_refs":[str]}],
"chart_explanations":[{"chart_id":str,"text":str}],"failure_analysis":str,"statistical_interpretation":str,
"recommendations":[{"text":str,"priority":"high|medium|low","evidence_refs":[str]}],
"scenes":[{"id":str,"type":"title|kpis|llm|rag|agent|failures|stats|recommendations|closing","title":str,"on_screen_text":[str],
"narration":str,"duration_seconds":number,"metric_refs":[str],"evidence_refs":[str]}],"total_duration_seconds":number}
Scenes must follow the requested sections in order, one scene per section, and their durations must sum to about the target duration."""


def _compact_payload(payload: Dict[str, Any], limit: int) -> str:
    """Trims bulky, non-essential parts until the JSON fits the input budget; never alters values."""
    p = {k: payload.get(k) for k in ("project", "runs", "models", "dataset_versions", "evaluation_time_range", "metrics", "operational",
                                     "quality_index", "statistical_results", "failures", "limitations", "recommendations", "evidence_index",
                                     "chart_datasets")}
    f = dict(p.get("failures") or {})
    f["failed_cases"] = [{k: c.get(k) for k in ("model_id", "status", "error_type", "evidence_ref")} for c in (f.get("failed_cases") or [])[:10]]
    p["failures"] = f
    p["metrics"] = [{k: v for k, v in m.items() if k != "per_model"} | {"per_model": m.get("per_model")} for m in p.get("metrics") or []]
    qi = dict(p.get("quality_index") or {})
    qi.pop("components", None)
    p["quality_index"] = qi
    for drop in (None, "chart_datasets", "limitations", "runs"):
        if drop:
            p[drop] = (p[drop][:3] if isinstance(p[drop], list) else None)
        s = json.dumps(p, default=str, separators=(",", ":"))
        if len(s) <= limit:
            return s
    raise NarrativeError("Snapshot is too large for the configured MUBIT_MAX_INPUT_CHARS budget.")


def build_prompt(payload: Dict[str, Any], options: Dict[str, Any], sections: List[str]) -> Tuple[str, str]:
    limit = max(1000, settings.MUBIT_MAX_INPUT_CHARS - len(SYSTEM_PROMPT) - 1500)
    snap = _compact_payload(payload, limit)
    target = int(options.get("duration_seconds") or 120)
    user = (f"Target total duration: {target} seconds. Narrated: {options.get('mode') == 'narrated'}.\n"
            f"Sections (in order): {', '.join(sections)}.\nSnapshot JSON:\n{snap}")
    return SYSTEM_PROMPT, user


# ----------------------------------------------------------------------------- deterministic template storyboard
def pct(v: Optional[float]) -> str:
    return "N/A" if v is None else f"{v * 100:.1f}%"


def _metric(payload, key):
    return next((m for m in payload.get("metrics") or [] if m["key"] == key), None)


def _fmt_metric(m: Optional[Dict[str, Any]]) -> str:
    if not m or m.get("value") is None:
        return "N/A"
    return pct(m["value"]) if m["unit"] == "ratio" else f"{m['value']:.1f}"


def _lines(payload, keys, limit=4) -> Tuple[List[str], List[str]]:
    lines, refs = [], []
    for k in keys:
        m = _metric(payload, k)
        if not m:
            continue
        lines.append(f"{m['name']}: {_fmt_metric(m)}" + (f" (n={m['n_observations']})" if m.get("value") is not None else " (insufficient data)"))
        refs.append(f"metric:{k}")
    return lines[:limit], refs[:limit]


def _split_duration(target: float, sections: List[str]) -> Dict[str, float]:
    weights = {"title": 1.0, "kpis": 2.0, "llm": 2.0, "rag": 2.0, "agent": 2.0, "failures": 2.0, "stats": 2.0, "recommendations": 2.0, "closing": 1.0}
    total_w = sum(weights[s] for s in sections) or 1
    return {s: max(3.0, round(target * weights[s] / total_w, 1)) for s in sections}


def template_storyboard(payload: Dict[str, Any], options: Dict[str, Any]) -> Storyboard:
    """Rule-based storyboard built only from snapshot values. Used when Claude is unavailable or rejected."""
    sections = normalise_sections(options.get("sections"))
    dur = _split_duration(float(options.get("duration_seconds") or 120), sections)
    qi = payload.get("quality_index") or {}
    ops = {o["key"]: o for o in payload.get("operational") or []}
    fl = payload.get("failures") or {}
    stats = [s for s in payload.get("statistical_results") or [] if s.get("testable")]
    scenes: List[Scene] = []

    def add(t, title, lines, narr, refs=(), ev=()):
        scenes.append(Scene(id=f"s{len(scenes) + 1}", type=t, title=title, on_screen_text=lines[:6], narration=narr,
                            duration_seconds=dur[t], metric_refs=list(refs), evidence_refs=list(ev)))

    n_runs, n_models = len(payload["runs"]), len(payload["models"])
    for t in sections:
        if t == "title":
            add("title", payload["project"]["name"], [f"{n_runs} evaluation run(s)", f"{n_models} model(s): " + ", ".join(payload["models"][:4])],
                f"Evaluation briefing for {payload['project']['name']}, covering {n_runs} runs across {n_models} models.")
        elif t == "kpis":
            qv = None if qi.get("value") is None else f"{qi['value']:.1f}"
            lines = [f"Overall Quality Index: {qv}" if qv else "Overall Quality Index: N/A (insufficient metric coverage)",
                     f"Failure rate: {_fmt_metric(ops.get('failure_rate'))}"]
            narr = (f"The overall quality index is {qv} out of 100." if qv else
                    "The overall quality index is not available because too few quality metrics have enough observations.")
            add("kpis", "Key indicators", lines, narr, ["qi"], ["qi"])
        elif t in ("llm", "rag", "agent"):
            keys = {"llm": ["llm_correctness", "factual_precision", "hallucination_rate", "instruction_adherence"],
                    "rag": ["rag_faithfulness", "context_precision", "context_recall", "retrieval_ndcg"],
                    "agent": ["agent_task_completion", "tool_use_accuracy", "agent_recovery_success"]}[t]
            title = {"llm": "LLM quality", "rag": "RAG quality", "agent": "Agent reliability"}[t]
            lines, refs = _lines(payload, keys)
            ok = [ln for ln in lines if "insufficient" not in ln]
            narr = (" ".join(ln + "." for ln in ok) if ok else f"No {title.lower()} metrics have enough observations in this scope.")
            add(t, title, lines or ["No data in this scope"], narr, refs, refs)
        elif t == "failures":
            tot, n = fl.get("total_failed", 0), fl.get("total_results", 0)
            lines = [f"{tot} of {n} results failed"] + [f"{c['classification']}: {c['count']}" for c in (fl.get("by_classification") or [])[:3]]
            add("failures", "Significant failures", lines, f"{tot} of {n} evaluated results failed.")
        elif t == "stats":
            lines, ev = [], []
            for s in stats[:3]:
                lines.append(f"{s['metric_name']}: {s['candidate'].split(':')[-1]} vs {s['baseline'].split(':')[-1]}, difference {s['mean_difference'] * 100:+.1f} pts, p={s['p_value']:.4f}")
                ev.append(f"stat:{s['id']}")
            if not stats:
                narr = "Not enough data for model comparisons: at least two models with sufficient observations are required."
            elif any(x.get("significant") for x in stats):
                narr = "Welch t-tests compare each model with the first model as baseline; significant differences are listed on screen."
            else:
                narr = "Welch t-tests compare each model with the first model as baseline; no difference is statistically significant."
            add("stats", "Statistical findings", lines or ["Not enough data for comparisons"], narr, [], ev)
        elif t == "recommendations":
            recs = payload.get("recommendations") or []
            add("recommendations", "Recommendations", [r["text"][:190] for r in recs[:4]] or ["No recommendations triggered by the data"],
                " ".join(r["text"] for r in recs[:3]) or "The data did not trigger any rule-based recommendation.",
                [], [e for r in recs[:4] for e in r["evidence_refs"]][:12])
        elif t == "closing":
            add("closing", "Summary", ["Immutable report snapshot", "Figures come from persisted evaluation results"],
                "This briefing was generated from the persisted evaluation snapshot. Review the full report for methodology and limitations.")
    recs = [Recommendation(text=r["text"][:590], priority=r["priority"], evidence_refs=r["evidence_refs"]) for r in (payload.get("recommendations") or [])[:8]]
    findings = []
    for k in ("llm_correctness", "rag_faithfulness", "agent_task_completion"):
        m = _metric(payload, k)
        if m and m.get("value") is not None:
            findings.append(Finding(text=f"{m['name']} is {pct(m['value'])} (n={m['n_observations']}).", evidence_refs=[f"metric:{k}"]))
    title = f"{payload['project']['name']} - evaluation briefing"
    sb = Storyboard(title=title[:200], executive_narrative=f"Based on {n_runs} runs and {n_models} models.", key_findings=findings,
                    recommendations=recs, scenes=scenes)
    return sb.normalised()


def normalise_sections(sections: Optional[List[str]]) -> List[str]:
    if not sections:
        return list(SCENE_TYPES)
    wanted = {SECTION_ALIASES[s] for s in sections if s in SECTION_ALIASES}
    wanted |= {"title", "closing"}  # always present
    return [s for s in SCENE_TYPES if s in wanted]


def fit_duration(sb: Storyboard, target: float) -> Storyboard:
    """Scales scene durations (never below the schema minimum) so the total approximates the target."""
    total = sum(s.duration_seconds for s in sb.scenes)
    if total > 0:
        k = target / total
        for s in sb.scenes:
            s.duration_seconds = round(min(60.0, max(2.0, s.duration_seconds * k)), 2)
    return sb.normalised()


# ----------------------------------------------------------------------------- orchestration
def generate_storyboard(payload: Dict[str, Any], options: Dict[str, Any], gateway: Optional[MubitGateway] = None
                        ) -> Tuple[Storyboard, str, Dict[str, Any]]:
    """Returns (storyboard, source, validation). source is 'claude' or 'template'. Never raises for provider problems."""
    gateway = gateway or MubitGateway()
    sections = normalise_sections(options.get("sections"))
    notice: Optional[Dict[str, Any]] = None
    if gateway.is_configured():
        try:
            system, user = build_prompt(payload, options, sections)
            resp = gateway.complete(system, user)
            sb = parse_storyboard(resp.text)
            sb = _restrict_sections(sb, sections)
            validation = validate_grounding(sb, payload)
            checked = validation["numbers_checked"]
            if checked >= 4 and validation["numbers_unsupported"] / checked > 0.5:
                raise NarrativeError("Rejected: most numeric claims are not supported by the snapshot.")
            validation["usage"] = {"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens, "request_id": resp.request_id}
            return fit_duration(sb, float(options.get("duration_seconds") or 120)), "claude", validation
        except (NarrativeError, GatewayError) as exc:
            logger.warning("Claude storyboard unavailable, using template: %s", exc)
            notice = {"scene_id": None, "type": "claude_unavailable", "severity": "info",
                      "message": f"Claude storyboard was not used ({type(exc).__name__}: {exc}); a rule-based storyboard built from the snapshot is shown."}
    sb = fit_duration(template_storyboard(payload, options), float(options.get("duration_seconds") or 120))
    validation = validate_grounding(sb, payload)
    if notice:
        validation["flags"].insert(0, notice)
    elif not gateway.is_configured():
        validation["flags"].insert(0, {"scene_id": None, "type": "claude_not_configured", "severity": "info",
                                       "message": "MUBIT_API_KEY is not configured; a rule-based storyboard built from the snapshot is shown."})
    validation["ok"] = not [f for f in validation["flags"] if f["severity"] != "info"]
    return sb, "template", validation


def _restrict_sections(sb: Storyboard, sections: List[str]) -> Storyboard:
    kept = [s for s in sb.scenes if s.type in sections]
    if not kept:
        raise NarrativeError("Storyboard contains none of the requested sections.")
    sb.scenes = kept
    return sb.normalised()


def blocking_flags(validation: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [f for f in (validation or {}).get("flags", []) if f.get("severity") in ("error", "warning")]
