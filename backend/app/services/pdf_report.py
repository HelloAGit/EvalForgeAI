"""Server-side PDF generation with ReportLab (pure Python, vector charts, A4).

Three templates share one snapshot payload: ``executive``, ``technical`` and ``statistical``.
All numbers are read from the immutable snapshot; nothing is recomputed or invented here.
"""
import io
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    NextPageTemplate,
)
from reportlab.platypus.tableofcontents import TableOfContents

NAVY = colors.HexColor("#0F172A")
TEAL = colors.HexColor("#0D9488")
AMBER = colors.HexColor("#D97706")
RED = colors.HexColor("#DC2626")
GREY = colors.HexColor("#64748B")
LIGHT = colors.HexColor("#F1F5F9")
PALETTE = [colors.HexColor(c) for c in ("#0D9488", "#1E3A8A", "#D97706", "#7C3AED", "#DC2626", "#0891B2")]

TEMPLATES = {"executive": "Executive Summary", "technical": "Technical Evaluation Report",
             "statistical": "Statistical Analysis Report"}
PAGE_W, PAGE_H = A4
MARGIN = 18 * mm
CONTENT_W = PAGE_W - 2 * MARGIN

_REPL = {"\u2265": ">=", "\u2264": "<=", "\u0394": "Delta ", "\u2192": "->", "\u2013": "-", "\u2014": "-", "\u2212": "-",
         "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2022": "-", "\u00a0": " "}


def safe(text: Any) -> str:
    """Helvetica is a Latin-1 font: map common symbols and replace the rest."""
    s = "" if text is None else str(text)
    for k, v in _REPL.items():
        s = s.replace(k, v)
    return s.encode("cp1252", "replace").decode("cp1252")


def P(text: Any, style) -> Paragraph:
    return Paragraph(escape(safe(text)), style)


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13.5, alignment=TA_LEFT),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=GREY),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8, leading=10),
        "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceBefore=6, spaceAfter=8),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=NAVY, spaceBefore=10, spaceAfter=5),
        "caption": ParagraphStyle("caption", fontName="Helvetica-Oblique", fontSize=8, leading=10, textColor=GREY, spaceAfter=8),
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=26, leading=32, textColor=colors.white),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=13, leading=17, textColor=colors.HexColor("#CBD5E1")),
        "card_v": ParagraphStyle("card_v", fontName="Helvetica-Bold", fontSize=16, leading=19, textColor=NAVY),
        "card_l": ParagraphStyle("card_l", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=GREY),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.5, leading=13.5, leftIndent=12, bulletIndent=2),
    }


# ----------------------------------------------------------------------------- value formatting
def fmt(value: Optional[float], unit: str) -> str:
    if value is None:
        return "N/A"
    if unit == "ratio":
        return f"{value * 100:.1f}%"
    if unit == "ms":
        return f"{value:,.0f} ms"
    if unit == "usd":
        return f"${value:,.4f}" if value < 1 else f"${value:,.2f}"
    if unit == "tokens":
        return f"{value:,.0f}"
    if unit == "index":
        return f"{value:.1f}"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:.3f}"


def _ci(m: Dict[str, Any]) -> str:
    lo, hi = m.get("ci_low"), m.get("ci_high")
    if lo is None or hi is None:
        return "n/a"
    return f"[{fmt(lo, m['unit'])}, {fmt(hi, m['unit'])}]"


# ----------------------------------------------------------------------------- tables / charts
def make_table(rows: List[List[Any]], widths: List[float], st, header: bool = True, zebra: bool = True) -> Table:
    """Cells are wrapped Paragraphs, widths are scaled to fit the frame and the header repeats on each page."""
    total = sum(widths)
    widths = [w * CONTENT_W / total for w in widths]
    data = []
    for i, r in enumerate(rows):
        data.append([c if not isinstance(c, (str, int, float, type(None))) else P(c, st["cellb"] if header and i == 0 else st["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0, splitByRow=1)
    style = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
             ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        style += [("BACKGROUND", (0, i), (-1, i), LIGHT) for i in range(2 if header else 1, len(rows), 2)]
    t.setStyle(TableStyle(style))
    return t


def _empty(msg: str, st) -> List[Any]:
    return [P(f"Chart not available: {msg}", st["small"]), Spacer(1, 6)]


def bar_chart(title: str, categories: List[str], series: Dict[str, List[Optional[float]]], st, *, pct=True, horizontal=False,
              height=170, alt: str = "") -> List[Any]:
    if not categories or not any(v is not None for vals in series.values() for v in vals):
        return [P(title, st["h2"])] + _empty("no data in this scope.", st)
    d = Drawing(CONTENT_W, height)
    ch = HorizontalBarChart() if horizontal else VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 55, 30, CONTENT_W - 75, height - 55
    ch.data = [[(v * 100 if (pct and v is not None) else (v or 0)) for v in vals] for vals in series.values()]
    ch.categoryAxis.categoryNames = [safe(c)[:18] for c in categories]
    ch.categoryAxis.labels.fontSize = 7
    ch.categoryAxis.labels.fontName = "Helvetica"
    ch.valueAxis.labels.fontSize = 7
    ch.valueAxis.valueMin = 0
    if pct:
        ch.valueAxis.valueMax = 100
    ch.bars.strokeColor = None
    for i in range(len(series)):
        ch.bars[i].fillColor = PALETTE[i % len(PALETTE)]
    ch.valueAxis.visibleGrid = True
    ch.valueAxis.gridStrokeColor = colors.HexColor("#E2E8F0")
    d.add(ch)
    if len(series) > 1:
        lg = Legend()
        lg.x, lg.y, lg.fontSize, lg.alignment = 60, height - 8, 7, "right"
        lg.colorNamePairs = [(PALETTE[i % len(PALETTE)], safe(n)) for i, n in enumerate(series)]
        lg.columnMaximum = 1
        d.add(lg)
    flow = [P(title, st["h2"]), KeepTogether([d, P(alt or f"{title}: values shown per category; 'N/A' categories have no data.", st["caption"])])]
    return flow


def line_chart(title: str, series: Dict[str, List[tuple]], st, unit_label: str, height=180) -> List[Any]:
    pts = {k: v for k, v in series.items() if v}
    if not pts:
        return [P(title, st["h2"])] + _empty("no trend points in this scope.", st)
    d = Drawing(CONTENT_W, height)
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 50, 28, CONTENT_W - 70, height - 55
    lp.data = [[(i, y) for i, (_, y) in enumerate(v)] for v in pts.values()]
    for i in range(len(pts)):
        lp.lines[i].strokeColor = PALETTE[i % len(PALETTE)]
        lp.lines[i].strokeWidth = 1.5
        lp.lines[i].symbol = None
    lp.yValueAxis.labels.fontSize = 7
    lp.xValueAxis.labels.fontSize = 7
    longest = max(pts.values(), key=len)
    labels = [t[5:10] if len(t) >= 10 else t for t, _ in longest]
    lp.xValueAxis.valueMin = 0
    lp.xValueAxis.valueMax = max(len(longest) - 1, 1)
    lp.xValueAxis.valueSteps = list(range(len(longest)))
    lp.xValueAxis.labelTextFormat = lambda v, labels=labels: labels[int(v)] if 0 <= int(v) < len(labels) else ""
    lp.yValueAxis.visibleGrid = True
    lp.yValueAxis.gridStrokeColor = colors.HexColor("#E2E8F0")
    d.add(lp)
    lg = Legend()
    lg.x, lg.y, lg.fontSize, lg.alignment = 60, height - 6, 7, "right"
    lg.colorNamePairs = [(PALETTE[i % len(PALETTE)], safe(n)) for i, n in enumerate(pts)]
    lg.columnMaximum = 1
    d.add(lg)
    return [P(title, st["h2"]), KeepTogether([d, P(f"{title} ({unit_label}); x-axis shows MM-DD of each day with data.", st["caption"])])]


def ci_chart(title: str, items: List[Dict[str, Any]], st) -> List[Any]:
    items = [i for i in items if i.get("ci_low") is not None]
    if not items:
        return [P(title, st["h2"])] + _empty("no metric has enough observations for a confidence interval.", st)
    row_h = 16
    height = 30 + row_h * len(items)
    d = Drawing(CONTENT_W, height)
    x0, w = 150, CONTENT_W - 190
    d.add(Line(x0, 15, x0 + w, 15, strokeColor=GREY))
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        d.add(String(x0 + t * w - 8, 4, f"{int(t * 100)}%", fontSize=6, fillColor=GREY))
    for i, it in enumerate(items):
        y = height - 20 - i * row_h
        d.add(String(4, y - 2, safe(it["name"])[:30], fontSize=7))
        lo, hi, mean = (min(max(it[k], 0), 1) for k in ("ci_low", "ci_high", "mean"))
        d.add(Line(x0 + lo * w, y, x0 + hi * w, y, strokeColor=NAVY, strokeWidth=1.6))
        d.add(Rect(x0 + mean * w - 2.5, y - 2.5, 5, 5, fillColor=TEAL, strokeColor=None))
    return [P(title, st["h2"]), KeepTogether([d, P("Points show the mean; bars show the 95% confidence interval (ratio metrics, 0-100%).", st["caption"])])]


def bullets(items: List[str], st) -> List[Any]:
    return [Paragraph(escape(safe(t)), st["bullet"], bulletText="-") for t in items] or [P("None.", st["body"])]


def cards(items: List[tuple], st) -> Table:
    n = 4
    cells = [[P(v, st["card_v"]), P(l, st["card_l"])] for l, v in items]
    rows = []
    for i in range(0, len(cells), n):
        chunk = cells[i:i + n]
        chunk += [[P("", st["card_v"]), P("", st["card_l"])]] * (n - len(chunk))
        rows.append([[c[0], c[1]] for c in chunk])
    t = Table(rows, colWidths=[CONTENT_W / n] * n)
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                           ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("LINEABOVE", (0, 0), (-1, 0), 2.5, TEAL),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


# ----------------------------------------------------------------------------- document
class _Doc(BaseDocTemplate):
    def __init__(self, buf, meta):
        super().__init__(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm, bottomMargin=20 * mm,
                         title=safe(meta["title"]), author="EvalForgeAI", subject=safe(meta["template_name"]),
                         creator="EvalForgeAI 3.0 (ReportLab)")
        self.meta = meta
        frame = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - 42 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        cover = Frame(MARGIN, 20 * mm, CONTENT_W, PAGE_H - 40 * mm, id="c")
        self.addPageTemplates([PageTemplate(id="cover", frames=[cover], onPage=self._cover),
                               PageTemplate(id="body", frames=[frame], onPage=self._body)])

    def _cover(self, canv, doc):
        canv.saveState()
        canv.setFillColor(NAVY)
        canv.rect(0, PAGE_H * 0.42, PAGE_W, PAGE_H * 0.58, stroke=0, fill=1)
        canv.setFillColor(TEAL)
        canv.rect(0, PAGE_H * 0.42 - 4, PAGE_W, 4, stroke=0, fill=1)
        canv.setFillColor(colors.white)
        canv.setFont("Helvetica-Bold", 14)
        canv.drawString(MARGIN, PAGE_H - 25 * mm, "EvalForge AI")
        canv.setFont("Helvetica", 9)
        canv.setFillColor(colors.HexColor("#94A3B8"))
        canv.drawString(MARGIN, PAGE_H - 31 * mm, "AI quality testing and evaluation")
        canv.restoreState()

    def _body(self, canv, doc):
        canv.saveState()
        canv.setStrokeColor(colors.HexColor("#CBD5E1"))
        canv.line(MARGIN, PAGE_H - 16 * mm, PAGE_W - MARGIN, PAGE_H - 16 * mm)
        canv.setFont("Helvetica", 8)
        canv.setFillColor(GREY)
        canv.drawString(MARGIN, PAGE_H - 13 * mm, safe(self.meta["title"])[:80])
        canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 13 * mm, safe(self.meta["template_name"]))
        canv.line(MARGIN, 16 * mm, PAGE_W - MARGIN, 16 * mm)
        canv.drawString(MARGIN, 11 * mm, f"EvalForgeAI | Report {self.meta['report_id']} | Snapshot {self.meta['snapshot_id'][:8]}")
        canv.drawRightString(PAGE_W - MARGIN, 11 * mm, f"Page {doc.page}")
        canv.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ("h1", "h2") and getattr(flowable, "_toc", False):
            level = 0 if flowable.style.name == "h1" else 1
            text = flowable.getPlainText()
            key = f"h{self.seq.nextf('toc')}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (level, text, self.page, key))


def H(text, st, level=1):
    p = Paragraph(escape(safe(text)), st["h1" if level == 1 else "h2"])
    p._toc = True
    return p


# ----------------------------------------------------------------------------- shared sections
def _metrics_table(metrics, st, categories=None, with_n=True):
    rows = [["Metric", "Value", "n", "95% CI", "Status / reason"]]
    for m in metrics:
        if categories and m["category"] not in categories:
            continue
        rows.append([m["name"], fmt(m["value"], m["unit"]), m["n_observations"], _ci(m),
                     "Measured" if m["status"] == "ok" else f"N/A - {m['na_reason']}"])
    if len(rows) == 1:
        return [P("No metrics in this group were selected.", st["body"])]
    return [make_table(rows, [48, 22, 12, 36, 70], st)]


def _kpi_cards(p, st):
    ops = {o["key"]: o for o in p["operational"]}
    m = {x["key"]: x for x in p["metrics"]}
    qi = p["quality_index"]
    items = [("Overall Quality Index", fmt(qi["value"], "index") if qi["value"] is not None else "N/A"),
             ("Quality band", qi["band"]["label"]), ("Evaluation runs", fmt(ops["total_runs"]["value"], "count")),
             ("Failure rate", fmt(ops["failure_rate"]["value"], "ratio")),
             ("Median latency", fmt(ops["latency_median"]["value"], "ms")), ("P95 latency", fmt(ops["latency_p95"]["value"], "ms")),
             ("Total cost", fmt(ops["total_cost"]["value"], "usd")), ("Regression alerts", fmt(ops["regression_alerts"]["value"], "count"))]
    return cards(items, st)


def _model_ranking(p, st):
    rk = p["chart_datasets"].get("model_ranking", [])
    out = []
    if rk:
        rows = [["Rank", "Model", "Quality index", "Metric coverage"]]
        for r in rk:
            rows.append([r.get("rank", "-") if r["quality_index"] is not None else "-", r["model_id"],
                         fmt(r["quality_index"], "index") if r["quality_index"] is not None else f"N/A - {r['na_reason']}",
                         f"{r['coverage'] * 100:.0f}%"])
        out.append(make_table(rows, [14, 50, 60, 30], st))
        out += bar_chart("Quality index by model", [r["model_id"] for r in rk], {"Quality index": [r["quality_index"] for r in rk]}, st, pct=False,
                         alt="Bar chart of overall quality index (0-100) per model; models without a computable index are shown as 0 and labelled N/A in the table.")
    else:
        out.append(P("Model ranking is not part of this report's chart selection.", st["body"]))
    return out


def _model_metric_chart(p, st, keys, title):
    ms = [m for m in p["metrics"] if m["key"] in keys and m["status"] == "ok"]
    models = p["models"]
    if not ms or not models:
        return bar_chart(title, [], {}, st)
    series = {}
    for m in ms:
        by = {x["model_id"]: x["value"] for x in m["per_model"]}
        series[m["name"]] = [by.get(mod) for mod in models]
    return bar_chart(title, models, series, st, alt=f"{title}: grouped bars per model, one series per metric (percent).")


def _failures(p, st, detail=False):
    f = p["failures"]
    out = [P(f"{f['total_failed']} of {f['total_results']} evaluation results failed or errored.", st["body"])]
    if f["by_classification"]:
        out.append(make_table([["Classification", "Count"]] + [[c["classification"], c["count"]] for c in f["by_classification"]], [100, 30], st))
        out += bar_chart("Failure classification", [c["classification"] for c in f["by_classification"][:8]],
                         {"Failures": [c["count"] for c in f["by_classification"][:8]]}, st, pct=False, horizontal=True)
    if detail and f["failed_cases"]:
        rows = [["Evidence ref", "Model", "Status", "Error type", "Mubit request"]]
        for c in f["failed_cases"][:50]:
            rows.append([c["evidence_ref"], c["model_id"], c["status"], c["error_type"] or "-", c["mubit_request_id"] or "-"])
        out += [P("Failed cases (most recent)", st["h2"]), make_table(rows, [58, 30, 16, 28, 38], st)]
        if f["failed_cases_truncated"]:
            out.append(P(f"Showing {len(f['failed_cases'])} of {f['total_failed']} failed results.", st["small"]))
    return out


def _regressions(p, st):
    a = p["regressions"]
    if not a:
        return [P("No regressions against the previous comparable run were detected.", st["body"])]
    rows = [["Metric", "Model", "Previous", "Latest", "Severity", "p-value"]]
    for x in a:
        unit = next((m["unit"] for m in p["metrics"] if m["key"] == x["metric_key"]), "ratio")
        rows.append([x["name"], x["model_id"], fmt(x["previous_mean"], unit), fmt(x["latest_mean"], unit), x["severity"],
                     "n/a" if x["p_value"] is None else f"{x['p_value']:.4f}"])
    return [make_table(rows, [42, 36, 22, 22, 22, 18], st)]


def _operations(p, st):
    rows = [["Measure", "Value", "n", "Note"]]
    for o in p["operational"]:
        if o["key"] in ("quality_index",):
            continue
        rows.append([o["name"], fmt(o["value"], o["unit"]), o["n_observations"], o["na_reason"] or ""])
    return [make_table(rows, [50, 28, 14, 70], st)]


def _stats_table(p, st):
    rs = p["statistical_results"]
    if not rs:
        return [P("No statistical comparison was possible: at least two models (or two runs) with enough observations are required.", st["body"])]
    rows = [["Metric", "Baseline", "Candidate", "n (b/c)", "Mean diff", "95% CI diff", "p", "Cohen's d", "Result"]]
    for s in rs:
        if not s.get("testable"):
            rows.append([s["metric_name"], s["baseline"], s["candidate"], f"{s['n_baseline']}/{s['n_candidate']}", "N/A", "N/A", "N/A", "N/A", s["reason"]])
            continue
        unit = next((m["unit"] for m in p["metrics"] if m["key"] == s["metric_key"]), "ratio")
        rows.append([s["metric_name"], s["baseline"], s["candidate"], f"{s['n_baseline']}/{s['n_candidate']}",
                     fmt(s["mean_difference"], unit), f"[{fmt(s['ci_low'], unit)}, {fmt(s['ci_high'], unit)}]", f"{s['p_value']:.4f}",
                     "n/a" if s["effect_size"] is None else f"{s['effect_size']:.2f}",
                     f"Significant at alpha={s['alpha']}" if s["significant"] else f"Not significant at alpha={s['alpha']}"])
    return [make_table(rows, [26, 24, 24, 14, 18, 30, 12, 14, 28], st)]


def _recommendations_section(p, st):
    recs = p["recommendations"]
    return bullets([f"[{r['priority'].upper()}] {r['text']}" for r in recs], st) if recs else [P("No data-driven recommendations were triggered.", st["body"])]


def _limitations(p, st):
    return bullets(p["limitations"], st)


def _methodology(p, st):
    md = p["methodology"]
    out = bullets([f"Confidence intervals: {md['ci_method']} at {int(md['confidence_level'] * 100)}%.",
                   f"Comparisons: {md['comparison_method']}; alpha = {md['alpha']}.",
                   f"A metric needs at least {md['min_observations']} observations, otherwise it is reported as N/A.",
                   f"Metric catalogue version {p['catalog_version']}; snapshot schema {p['schema_version']}.",
                   "Overall Quality Index: weighted mean of available metric scores (lower-is-better metrics inverted); missing metrics are excluded and weights re-normalised; N/A below the minimum metric coverage."], st)
    rows = [["Metric", "Category", "Unit", "Method", "Definition"]]
    for d in p["metric_definitions"]:
        rows.append([d["name"], d["category"], d["unit"], f"{d['method'] or '-'} v{d['method_version']}", d["definition"]])
    return out + [Spacer(1, 6), make_table(rows, [34, 16, 12, 30, 68], st)]


def _scope_table(p, st):
    rows = [["Run", "Model", "Provider", "Suite", "Dataset ver.", "Category", "Status"]]
    for r in p["runs"]:
        rows.append([r["id"][:8], r["model_id"], r["provider"] or "-", r["suite"] or "-", r["dataset_version"] or "-", r["category"] or "-", r["status"]])
    return [make_table(rows, [16, 34, 22, 26, 20, 16, 20], st)]


def _trend_chart(p, st):
    ts = p["chart_datasets"].get("quality_trend")
    if ts is None:
        return []
    return line_chart("Quality index trend", {s["model_id"]: [(pt["t"], pt["value"]) for pt in s["points"]] for s in ts["series"]}, st, "index 0-100")


# ----------------------------------------------------------------------------- templates
def _cover(p, meta, st):
    return [Spacer(1, 62 * mm), P(meta["title"], st["title"]), Spacer(1, 6), P(meta["template_name"], st["subtitle"]),
            Spacer(1, 70 * mm),
            make_table([["Report ID", meta["report_id"]], ["Snapshot ID", meta["snapshot_id"]], ["Project", p["project"]["name"]],
                        ["Generated", meta["generated_at"]], ["Data created", p["created_at"]],
                        ["Models", ", ".join(p["models"]) or "-"], ["Snapshot SHA-256", meta["sha256"][:32] + "..."]],
                       [38, 130], st, header=False, zebra=False),
            NextPageTemplate("body"), PageBreak()]


def _toc(st):
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("t0", fontName="Helvetica-Bold", fontSize=10, leading=15, leftIndent=0),
                       ParagraphStyle("t1", fontName="Helvetica", fontSize=9, leading=13, leftIndent=14)]
    return [P("Table of contents", st["h1"]), toc, PageBreak()]


def _executive(p, st):
    qi = p["quality_index"]
    status = qi["band"]["label"]
    f = []
    f += [H("Executive summary", st),
          P(f"This report summarises {len(p['runs'])} evaluation run(s) across {len(p['models'])} model(s) for project "
            f"'{p['project']['name']}', based on {p['evidence']['n_results']} persisted evaluation results. "
            f"Overall quality status: {status}"
            + (f" (Overall Quality Index {qi['value']:.1f}/100)." if qi["value"] is not None else f" - {qi['na_reason']}"), st["body"]),
          Spacer(1, 6), _kpi_cards(p, st), Spacer(1, 4), P(qi["band"]["rule"], st["small"])]
    f += [H("Main KPIs", st)] + _metrics_table(p["metrics"], st)
    f += [H("Model comparison", st)] + _model_ranking(p, st) + _model_metric_chart(p, st, {"llm_correctness", "rag_faithfulness", "agent_task_completion"}, "Headline quality metrics by model")
    f += [H("Significant failures", st)] + _failures(p, st)
    f += [H("Operational risks", st)] + _regressions(p, st) + _operations(p, st)
    f += [H("Improvement priorities and recommended actions", st)] + _recommendations_section(p, st)
    f += [H("Limitations", st, 2)] + _limitations(p, st)
    return f


def _technical(p, st):
    f = [H("Project metadata", st), make_table([["Project", p["project"]["name"]], ["Description", p["project"]["description"] or "-"],
                                              ["Evaluation window", f"{p['evaluation_time_range']['start']} to {p['evaluation_time_range']['end']}"],
                                              ["Runs / results / observations", f"{len(p['runs'])} / {p['evidence']['n_results']} / {p['evidence']['n_observations']}"]],
                                             [45, 125], st, header=False, zebra=False)]
    f += [H("Models and datasets evaluated", st), P("Models: " + (", ".join(p["models"]) or "-"), st["body"]),
          P("Dataset versions: " + (", ".join(p["dataset_versions"]) or "not recorded"), st["body"]), Spacer(1, 4)] + _scope_table(p, st)
    f += [H("Evaluation methodology", st)] + _methodology(p, st)
    f += [H("LLM quality metrics", st)] + _metrics_table(p["metrics"], st, {"llm"}) + _model_metric_chart(p, st, {m["key"] for m in p["metrics"] if m["category"] == "llm"}, "LLM metrics by model")
    f += [H("RAG quality metrics", st)] + _metrics_table(p["metrics"], st, {"rag"})
    rag = p["chart_datasets"].get("rag_quality")
    if rag:
        keys = ["context_precision", "context_recall", "retrieval_ndcg", "rag_faithfulness", "answer_relevancy", "citation_accuracy"]
        names = {m["key"]: m["name"] for m in p["metrics"]}
        f += bar_chart("Retrieval versus generation quality", [r["model_id"] for r in rag],
                       {"Retrieval (mean of available)": [_mean([v for v in r["retrieval"].values() if v is not None]) for r in rag],
                        "Generation (mean of available)": [_mean([v for v in r["generation"].values() if v is not None]) for r in rag]}, st,
                       alt="Mean of available retrieval metrics versus mean of available generation metrics per model.")
    f += [H("Agent reliability", st)] + _metrics_table(p["metrics"], st, {"agent"})
    ao = p["chart_datasets"].get("agent_outcomes")
    if ao:
        f += bar_chart("Agent outcomes", [a["model_id"] for a in ao], {"Success": [a["success"] for a in ao], "Failure": [a["failure"] for a in ao]}, st, pct=False)
    dist = p["chart_datasets"].get("distributions")
    f += [H("Metric distributions", st)]
    if dist:
        for d in dist[:6]:
            f += bar_chart(f"Distribution: {d['name']}", [f"{b:.1f}" for b in d["bins"]], {"Observations": d["counts"]}, st, pct=False, height=130,
                           alt=f"Histogram of {d['name']} observations in ten bins of width 0.1 from 0.0 to 1.0.")
    else:
        f += [P("Distributions were not selected or no data is available.", st["body"])]
    f += [H("Statistical analysis", st)] + _stats_table(p, st) + ci_chart("Confidence intervals", p["chart_datasets"].get("confidence_intervals", []), st)
    f += _trend_chart(p, st)
    f += [H("Failure diagnostics", st)] + _failures(p, st, detail=True) + _regressions(p, st)
    f += [H("Latency and cost", st)] + _operations(p, st)
    lat = p["chart_datasets"].get("latency_percentiles")
    if lat:
        f += bar_chart("Latency percentiles by model (ms)", [r["model_id"] for r in lat], {"P50": [r["p50"] for r in lat], "P95": [r["p95"] for r in lat], "P99": [r["p99"] for r in lat]}, st, pct=False)
    f += [H("Limitations and assumptions", st)] + _limitations(p, st)
    f += [H("Raw observation references", st)]
    f += bullets([f"{x}" for x in p["evidence_index"] if x.split(":")[0] in ("run", "result", "stat", "model")][:200], st)
    if p["evidence"]["mubit_request_ids"]:
        f += [P("Mubit request IDs: " + ", ".join(p["evidence"]["mubit_request_ids"]), st["small"])]
    return f


def _mean(v):
    return sum(v) / len(v) if v else None


def _statistical(p, st):
    models, runs = p["models"], p["runs"]
    f = [H("Research question", st),
         P("Do the evaluated models (or successive runs of the same model) differ in measured quality? "
           f"Scope: {len(models)} model(s), {len(runs)} run(s), project '{p['project']['name']}'.", st["body"]),
         H("Hypotheses", st),
         P("H0: the mean metric score is equal for the baseline and the candidate. H1: the mean scores differ (two-sided).", st["body"]),
         P(f"Baseline is the first model in the report scope ({models[0] if models else 'n/a'}); with a single model the first and last run are compared.", st["small"]),
         H("Sampling methodology", st),
         P("All persisted observations in scope are used; observations are not randomly sampled by this report and the samples are those "
           "present in the evaluation datasets. Observations are treated as independent.", st["body"])]
    rows = [["Metric", "Model", "n", "Mean", "SD", "95% CI"]]
    for m in p["metrics"]:
        for pm in m["per_model"]:
            rows.append([m["name"], pm["model_id"], pm["n"], fmt(pm["value"], m["unit"]) if pm["value"] is not None else "N/A (n<%d)" % p["methodology"]["min_observations"],
                         "-", f"[{fmt(pm['ci_low'], m['unit'])}, {fmt(pm['ci_high'], m['unit'])}]" if pm["ci_low"] is not None else "n/a"])
    f += [H("Sample sizes and descriptive statistics", st)]
    f += [make_table(rows, [38, 34, 12, 26, 12, 46], st)] if len(rows) > 1 else [P("No per-model observations are available.", st["body"])]
    f += _metrics_table(p["metrics"], st)
    f += ci_chart("Confidence intervals (all models pooled)", p["chart_datasets"].get("confidence_intervals", []), st)
    f += [H("Statistical tests and effect sizes", st)] + _stats_table(p, st)
    f += [H("Findings", st)]
    findings = []
    for s in p["statistical_results"]:
        if s.get("testable"):
            direction = "higher" if s["mean_difference"] > 0 else "lower" if s["mean_difference"] < 0 else "equal"
            unit = next((m["unit"] for m in p["metrics"] if m["key"] == s["metric_key"]), "ratio")
            findings.append(f"{s['metric_name']}: {s['candidate']} is {direction} than {s['baseline']} by {fmt(abs(s['mean_difference']), unit) if unit != 'ratio' else '%.1f percentage points' % abs(s['mean_difference'] * 100)} "
                            f"(p={s['p_value']:.4f}, {'significant' if s['significant'] else 'not significant'} at alpha={s['alpha']}; n={s['n_baseline']}/{s['n_candidate']}).")
        else:
            findings.append(f"{s['metric_name']}: not testable - {s['reason']}")
    f += bullets(findings or ["No testable comparisons in this scope."], st)
    f += [H("Model comparisons", st)] + _model_ranking(p, st)
    f += [H("Limitations", st)] + _limitations(p, st)
    f += [H("Deployment implications", st)]
    sig_neg = [s for s in p["statistical_results"] if s.get("testable") and s["significant"] and s["mean_difference"] < 0]
    f += bullets(([f"Significant decreases were found for: {', '.join(sorted({s['metric_name'] + ' (' + s['candidate'] + ')' for s in sig_neg}))}. Review before deployment."] if sig_neg
                  else ["No statistically significant decreases were found among the tests that could be run; absence of evidence is not evidence of equivalence."]), st)
    f += _recommendations_section(p, st)
    f += [H("Methodology appendix", st)] + _methodology(p, st)
    return f


BUILDERS = {"executive": _executive, "technical": _technical, "statistical": _statistical}


def render_pdf(payload: Dict[str, Any], template: str, title: str, report_id: str, generated_at: str) -> bytes:
    if template not in BUILDERS:
        raise ValueError(f"Unknown template {template!r}")
    from app.services.snapshot import canonical_hash
    meta = {"title": title, "template_name": TEMPLATES[template], "report_id": report_id, "snapshot_id": payload["snapshot_id"],
            "generated_at": generated_at, "sha256": canonical_hash(payload)}
    st = _styles()
    buf = io.BytesIO()
    doc = _Doc(buf, meta)
    story = _cover(payload, meta, st) + _toc(st) + BUILDERS[template](payload, st)
    doc.multiBuild(story)
    return buf.getvalue()
