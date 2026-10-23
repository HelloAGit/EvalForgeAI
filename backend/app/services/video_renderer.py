"""Report-to-video renderer: Pillow draws animated 16:9 scenes from the immutable snapshot, FFmpeg encodes H.264 MP4.

KPI values, chart values and statistics are read from the snapshot payload. The storyboard only
supplies titles, takeaway text and captions, so Claude (or a user edit) cannot change a number
that is drawn as a chart or KPI card.
"""
import io
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.config import settings
from app.services.narrative import Storyboard
from app.services.pdf_report import fmt
from app.services.tts import TTSProvider, wav_info

NAVY, TEAL, AMBER, RED = (11, 31, 58), (15, 157, 143), (245, 166, 35), (214, 69, 69)
LIGHT, INK, MUTED, CARD, LINE = (244, 247, 251), (15, 23, 42), (100, 116, 139), (255, 255, 255), (203, 213, 225)
ANIM_SECONDS = 1.4
FADE_SECONDS = 0.35
_FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/dejavu",
              "/usr/share/fonts/TTF", "/Library/Fonts"]
_FONT_FILES = {False: ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
               True: ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"]}


class RenderError(RuntimeError):
    pass


class RenderCancelled(Exception):
    pass


class RenderTimeout(RenderError):
    pass


@dataclass
class RenderResult:
    path: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    has_audio: bool
    frames: int


def ffmpeg_exe() -> str:
    if settings.FFMPEG_PATH:
        return settings.FFMPEG_PATH
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


# ----------------------------------------------------------------------------- drawing helpers
class _Fonts:
    def __init__(self):
        self._cache: Dict[Tuple[int, bool], Any] = {}

    def get(self, size: int, bold: bool = False):
        size = max(6, int(size))
        key = (size, bold)
        if key not in self._cache:
            font = None
            for d in _FONT_DIRS:
                for f in _FONT_FILES[bold]:
                    p = os.path.join(d, f)
                    if os.path.exists(p):
                        font = ImageFont.truetype(p, size)
                        break
                if font:
                    break
            self._cache[key] = font or ImageFont.load_default(size)
        return self._cache[key]


def _wrap(draw, text: str, font, max_w: int) -> List[str]:
    lines: List[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return lines


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


class SceneDrawer:
    def __init__(self, payload: Dict[str, Any], sb: Storyboard, width: int, height: int, captions: bool):
        self.p, self.sb, self.W, self.H, self.captions = payload, sb, width, height, captions
        self.S = width / 1920.0
        self.fonts = _Fonts()
        self.n = len(sb.scenes)
        self.ops = {o["key"]: o for o in payload.get("operational") or []}

    def px(self, v: float) -> int:
        return max(1, int(round(v * self.S)))

    def f(self, size: int, bold=False):
        return self.fonts.get(self.px(size), bold)

    # -- generic pieces
    def _text(self, d, xy, text, size, fill=INK, bold=False, max_w=None, max_lines=None, line_gap=1.25, anchor="la"):
        font = self.f(size, bold)
        lines = _wrap(d, text, font, max_w or self.W) if max_w else [text]
        if max_lines and len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .,;") + "..."
        y = xy[1]
        for ln in lines:
            d.text((xy[0], y), ln, font=font, fill=fill, anchor=anchor)
            y += int(self.px(size) * line_gap)
        return y

    def _frame_chrome(self, img, d, idx: int, title: str):
        d.rectangle([0, 0, self.W, self.px(110)], fill=NAVY)
        d.rectangle([0, self.px(110), self.W, self.px(116)], fill=TEAL)
        self._text(d, (self.px(70), self.px(30)), "EvalForge AI", 44, (255, 255, 255), True)
        self._text(d, (self.W - self.px(70), self.px(38)), title, 36, (203, 213, 225), False, anchor="ra")
        sid = self.p.get("snapshot_id", "")[:8]
        self._text(d, (self.px(70), self.H - self.px(46)), f"Snapshot {sid} | schema {self.p.get('schema_version')}", 22, MUTED)
        self._text(d, (self.W - self.px(70), self.H - self.px(46)), f"{idx + 1} / {self.n}", 22, MUTED, anchor="ra")

    def _takeaways(self, d, scene, y0):
        y = y0
        for line in scene.on_screen_text[:3]:
            d.ellipse([self.px(80), y + self.px(12), self.px(92), y + self.px(24)], fill=TEAL)
            y = self._text(d, (self.px(110), y), line, 32, INK, max_w=self.W - self.px(260), max_lines=2)
            y += self.px(8)

    def _caption(self, img, text: str):
        if not text:
            return img
        d = ImageDraw.Draw(img, "RGBA")
        font = self.f(34)
        lines = _wrap(d, text, font, self.W - self.px(300))[:3]
        lh = int(self.px(34) * 1.3)
        h = lh * len(lines) + self.px(30)
        top = self.H - self.px(110) - h
        d.rounded_rectangle([self.px(120), top, self.W - self.px(120), top + h], radius=self.px(14), fill=(11, 31, 58, 215))
        y = top + self.px(15)
        for ln in lines:
            d.text((self.W // 2, y), ln, font=font, fill=(255, 255, 255, 255), anchor="ma")
            y += lh
        return img

    # -- scene renderers; ``a`` is the 0..1 animation progress
    def draw(self, idx: int, a: float, caption: str = "") -> Image.Image:
        scene = self.sb.scenes[idx]
        img = Image.new("RGB", (self.W, self.H), NAVY if scene.type in ("title", "closing") else LIGHT)
        d = ImageDraw.Draw(img)
        handler = {"title": self._title, "closing": self._closing, "kpis": self._kpis, "llm": self._bars, "rag": self._bars,
                   "agent": self._bars, "failures": self._failures, "stats": self._stats,
                   "recommendations": self._recs}.get(scene.type, self._generic)
        if scene.type not in ("title", "closing"):
            self._frame_chrome(img, d, idx, scene.title)
        handler(img, d, scene, a)
        if self.captions and caption:
            img = self._caption(img, caption)
        return img

    def _title(self, img, d, scene, a):
        for i in range(0, self.H, self.px(6)):  # subtle vertical gradient
            c = tuple(int(NAVY[k] + (TEAL[k] - NAVY[k]) * (i / self.H) * 0.35) for k in range(3))
            d.rectangle([0, i, self.W, i + self.px(6)], fill=c)
        off = int((1 - _ease(a)) * self.px(60))
        self._text(d, (self.px(140), self.px(220) + off), "EvalForge AI", 48, (153, 246, 228), True)
        y = self._text(d, (self.px(140), self.px(310) + off), self.sb.title, 84, (255, 255, 255), True, max_w=self.W - self.px(280), max_lines=3)
        y = self._text(d, (self.px(140), y + self.px(30)), scene.title, 46, (203, 213, 225), False, max_w=self.W - self.px(280), max_lines=2)
        for line in scene.on_screen_text[:3]:
            y = self._text(d, (self.px(140), y + self.px(14)), line, 36, (226, 232, 240), max_w=self.W - self.px(280), max_lines=2)
        d.rectangle([self.px(140), self.px(280), self.px(140) + int(self.px(520) * _ease(a)), self.px(286)], fill=TEAL)

    def _closing(self, img, d, scene, a):
        self._title(img, d, scene, a)

    def _status_color(self, o):
        return MUTED if o.get("value") is None else TEAL

    def _kpis(self, img, d, scene, a):
        qi = self.p.get("quality_index") or {}
        cards = []
        qv = qi.get("value")
        cards.append(("Overall Quality Index", qv, "index", qi.get("band", {}).get("label", ""), qi.get("na_reason")))
        for k in ("total_runs", "failure_rate", "latency_median", "latency_p95", "cost"):
            o = self.ops.get(k)
            if o:
                cards.append((o["name"], o.get("value"), o["unit"], "", o.get("na_reason")))
        cards = cards[:6]
        cw, ch, gap = self.px(540), self.px(250), self.px(40)
        x0, y0 = (self.W - (3 * cw + 2 * gap)) // 2, self.px(180)
        for i, (name, val, unit, sub, reason) in enumerate(cards):
            x, y = x0 + (i % 3) * (cw + gap), y0 + (i // 3) * (ch + gap)
            prog = _ease((a * 1.6) - 0.12 * i)
            dy = int((1 - prog) * self.px(40))
            d.rounded_rectangle([x, y + dy, x + cw, y + ch + dy], radius=self.px(18), fill=CARD, outline=LINE, width=max(1, self.px(2)))
            d.rectangle([x, y + dy + self.px(20), x + self.px(8), y + ch + dy - self.px(20)], fill=TEAL if val is not None else MUTED)
            self._text(d, (x + self.px(34), y + dy + self.px(24)), name, 30, MUTED, max_w=cw - self.px(60), max_lines=1)
            if val is None:
                self._text(d, (x + self.px(34), y + dy + self.px(70)), "N/A", 78, MUTED, True)
                self._text(d, (x + self.px(34), y + dy + self.px(172)), (reason or "insufficient data")[:60], 22, MUTED, max_w=cw - self.px(60), max_lines=2)
            else:
                shown = val * prog if prog < 1 else val  # count-up; the final frame shows the exact snapshot value
                self._text(d, (x + self.px(34), y + dy + self.px(70)), fmt(shown, unit), 78, INK, True, max_w=cw - self.px(60))
                if sub:
                    self._text(d, (x + self.px(34), y + dy + self.px(176)), sub, 28, TEAL if "Good" in sub else AMBER)
        self._takeaways(d, scene, y0 + 2 * (ch + gap) + self.px(10))

    def _bars(self, img, d, scene, a):
        cat = scene.type
        metrics = [m for m in self.p.get("metrics") or [] if m.get("category") == cat]
        x0, y = self.px(80), self.px(160)
        label_w, bar_w, row_h = self.px(520), self.px(900), self.px(92)
        if not metrics:
            self._text(d, (x0, y), "No metrics of this category are part of the report scope.", 40, MUTED)
        for i, m in enumerate(metrics[:7]):
            ry = y + i * row_h
            self._text(d, (x0, ry + self.px(8)), m["name"], 32, INK, max_w=label_w - self.px(20), max_lines=2, line_gap=1.1)
            bx = x0 + label_w
            d.rounded_rectangle([bx, ry + self.px(10), bx + bar_w, ry + self.px(50)], radius=self.px(8), fill=(226, 232, 240))
            v = m.get("value")
            if v is None:
                self._text(d, (bx + self.px(16), ry + self.px(14)), "N/A - " + (m.get("na_reason") or "insufficient data"), 24, MUTED, max_w=bar_w, max_lines=1)
                continue
            frac = max(0.0, min(1.0, v if m["unit"] == "ratio" else v / max(v, 1.0)))
            w = int(bar_w * frac * _ease(a * 1.3 - 0.08 * i))
            color = AMBER if m.get("direction") == "lower_better" else TEAL
            if w > 0:
                d.rounded_rectangle([bx, ry + self.px(10), bx + w, ry + self.px(50)], radius=self.px(8), fill=color)
            if m.get("ci_low") is not None and a >= 1:
                for c in (m["ci_low"], m["ci_high"]):
                    cx = bx + int(bar_w * max(0.0, min(1.0, c)))
                    d.line([cx, ry + self.px(4), cx, ry + self.px(56)], fill=NAVY, width=max(1, self.px(4)))
            self._text(d, (bx + bar_w + self.px(24), ry + self.px(8)), fmt(v, m["unit"]), 36, INK, True)
            self._text(d, (bx, ry + self.px(56)), f"n = {m['n_observations']}" + (f"   95% CI [{fmt(m['ci_low'], m['unit'])}, {fmt(m['ci_high'], m['unit'])}]" if m.get("ci_low") is not None else ""), 22, MUTED)
        self._takeaways(d, scene, self.px(160) + min(len(metrics), 7) * row_h + self.px(10))

    def _failures(self, img, d, scene, a):
        f = self.p.get("failures") or {}
        tot, n = f.get("total_failed", 0), f.get("total_results", 0)
        d.rounded_rectangle([self.px(80), self.px(170), self.px(640), self.px(470)], radius=self.px(18), fill=CARD, outline=LINE, width=max(1, self.px(2)))
        self._text(d, (self.px(120), self.px(200)), "Failed results", 32, MUTED)
        shown = int(round(tot * _ease(a)))
        self._text(d, (self.px(120), self.px(250)), f"{shown} of {n}", 84, RED if tot else TEAL, True)
        self._text(d, (self.px(120), self.px(370)), f"{(tot / n * 100):.1f}% failure rate" if n else "no results", 34, INK)
        rows = (f.get("by_classification") or [])[:6]
        mx = max([r["count"] for r in rows] or [1])
        y = self.px(180)
        for i, r in enumerate(rows):
            self._text(d, (self.px(720), y), r["classification"], 30, INK, max_w=self.px(520), max_lines=1)
            w = int(self.px(520) * (r["count"] / mx) * _ease(a * 1.3 - 0.1 * i))
            d.rounded_rectangle([self.px(1260), y + self.px(4), self.px(1260) + max(w, 1), y + self.px(44)], radius=self.px(8), fill=RED)
            self._text(d, (self.px(1260) + self.px(530), y), str(r["count"]), 32, INK, True)
            y += self.px(70)
        if not rows:
            self._text(d, (self.px(720), y), "No failure classifications in this scope.", 34, MUTED)
        self._takeaways(d, scene, self.px(560))

    def _stats(self, img, d, scene, a):
        stats = [s for s in self.p.get("statistical_results") or [] if s.get("testable")][:6]
        y = self.px(170)
        if not stats:
            self._text(d, (self.px(80), y), "Not enough data for statistical comparisons in this scope.", 40, MUTED)
        for i, s in enumerate(stats):
            prog = _ease(a * 1.5 - 0.15 * i)
            rh = self.px(100)
            ry = y + i * rh
            if prog <= 0:
                continue
            d.rounded_rectangle([self.px(80), ry, self.W - self.px(80), ry + rh - self.px(12)], radius=self.px(12), fill=CARD,
                                outline=AMBER if s.get("significant") else LINE, width=max(1, self.px(3)))
            self._text(d, (self.px(110), ry + self.px(12)), s["metric_name"], 30, INK, True, max_w=self.px(520), max_lines=1)
            self._text(d, (self.px(110), ry + self.px(50)), f"{s['candidate'].split(':')[-1]} vs {s['baseline'].split(':')[-1]} (n={s['n_candidate']} / {s['n_baseline']})", 22, MUTED, max_w=self.px(560), max_lines=1)
            self._text(d, (self.px(700), ry + self.px(12)), f"diff {s['mean_difference'] * 100:+.1f} pts", 32, INK)
            self._text(d, (self.px(700), ry + self.px(50)), f"95% CI [{s['ci_low'] * 100:+.1f}, {s['ci_high'] * 100:+.1f}]", 22, MUTED)
            self._text(d, (self.px(1130), ry + self.px(12)), f"p = {s['p_value']:.4f}", 32, INK)
            self._text(d, (self.px(1130), ry + self.px(50)), f"effect size {s['effect_size']:.2f}" if s.get("effect_size") is not None else "", 22, MUTED)
            self._text(d, (self.px(1500), ry + self.px(22)), "Significant" if s.get("significant") else "Not significant", 30, AMBER if s.get("significant") else MUTED, True)
        self._takeaways(d, scene, y + max(len(stats), 1) * self.px(100) + self.px(10))

    def _recs(self, img, d, scene, a):
        recs = scene.on_screen_text[:5] or ["No recommendations triggered by the data."]
        y = self.px(170)
        for i, t in enumerate(recs):
            prog = _ease(a * 1.6 - 0.2 * i)
            if prog <= 0:
                continue
            off = int((1 - prog) * self.px(50))
            d.rounded_rectangle([self.px(80), y + off, self.W - self.px(80), y + self.px(120) + off], radius=self.px(14), fill=CARD, outline=LINE, width=max(1, self.px(2)))
            d.ellipse([self.px(110), y + self.px(34) + off, self.px(162), y + self.px(86) + off], fill=TEAL)
            self._text(d, (self.px(136), y + self.px(40) + off), str(i + 1), 34, (255, 255, 255), True, anchor="ma")
            self._text(d, (self.px(190), y + self.px(24) + off), t, 32, INK, max_w=self.W - self.px(400), max_lines=2)
            y += self.px(140)

    def _generic(self, img, d, scene, a):
        self._takeaways(d, scene, self.px(180))


# ----------------------------------------------------------------------------- timing / captions
def caption_chunks(text: str, max_chars: int = 90) -> List[str]:
    words, chunks, cur = (text or "").split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def caption_at(chunks: List[str], t: float, duration: float) -> Tuple[int, str]:
    if not chunks:
        return -1, ""
    total = sum(len(c) for c in chunks)
    acc = 0.0
    for i, c in enumerate(chunks):
        acc += len(c) / total * duration
        if t < acc:
            return i, c
    return len(chunks) - 1, chunks[-1]


# ----------------------------------------------------------------------------- audio
def plan_narration(sb: Storyboard, tts: TTSProvider, voice: str, workdir: str,
                   cancel_check: Optional[Callable[[], None]] = None) -> Tuple[str, List[float]]:
    """Synthesises each scene's narration, returns (wav path for the full timeline, scene durations).
    Scene duration = max(planned duration, narration length + 0.6 s) so speech is never cut off."""
    clips: List[Tuple[bytes, dict]] = []
    for scene in sb.scenes:
        if cancel_check:
            cancel_check()
        text = (scene.narration or "").strip()
        if len(text) > settings.TTS_MAX_CHARS_PER_SCENE:
            raise RenderError(f"Narration of scene {scene.id} exceeds TTS_MAX_CHARS_PER_SCENE.")
        if text:
            data = tts.synthesize(text, voice)
            clips.append((data, wav_info(data)))
        else:
            clips.append((b"", {}))
    first = next((i for _, i in clips if i), None)
    if not first:
        raise RenderError("Narrated mode requires narration text in at least one scene.")
    channels, rate = first["channels"], first["rate"]
    durations: List[float] = []
    out_path = os.path.join(workdir, "narration.wav")
    with wave.open(out_path, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        for scene, (data, info) in zip(sb.scenes, clips):
            dur = float(scene.duration_seconds)
            frames = b""
            if info:
                if info["channels"] != channels or info["rate"] != rate:
                    raise RenderError("TTS provider returned audio with inconsistent format between scenes.")
                with wave.open(io.BytesIO(data), "rb") as w:
                    frames = w.readframes(w.getnframes())
                dur = max(dur, info["seconds"] + 0.6)
            dur = min(dur, 90.0)
            durations.append(dur)
            want = int(round(dur * rate)) * channels * 2
            out.writeframes((frames[:want] + b"\x00" * max(0, want - len(frames))))
    return out_path, durations


# ----------------------------------------------------------------------------- rendering
def render_video(payload: Dict[str, Any], sb: Storyboard, out_path: str, *, captions: bool = True, audio_path: Optional[str] = None,
                 scene_durations: Optional[List[float]] = None, progress: Optional[Callable[[float], None]] = None,
                 cancel_check: Optional[Callable[[], None]] = None, timeout: Optional[float] = None,
                 width: Optional[int] = None, height: Optional[int] = None, fps: Optional[int] = None) -> RenderResult:
    width = (width or settings.VIDEO_WIDTH) // 2 * 2
    height = (height or settings.VIDEO_HEIGHT) // 2 * 2
    fps = fps or settings.VIDEO_FPS
    durations = scene_durations or [float(s.duration_seconds) for s in sb.scenes]
    if len(durations) != len(sb.scenes):
        raise RenderError("scene_durations must match the number of scenes")
    total_seconds = sum(durations)
    if total_seconds > settings.VIDEO_MAX_DURATION_SECONDS:
        raise RenderError(f"Video of {total_seconds:.0f}s exceeds VIDEO_MAX_DURATION_SECONDS ({settings.VIDEO_MAX_DURATION_SECONDS}).")
    counts = [max(1, int(round(d * fps))) for d in durations]
    total_frames = sum(counts)
    drawer = SceneDrawer(payload, sb, width, height, captions)
    deadline = time.monotonic() + timeout if timeout else None

    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
           "-r", str(fps), "-i", "-"]
    if audio_path:
        cmd += ["-i", audio_path]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "23", "-r", str(fps), "-movflags", "+faststart"]
    cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"] if audio_path else ["-an"]
    cmd.append(out_path)

    errlog = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=errlog)
    written = 0
    prev_final: Optional[Image.Image] = None
    try:
        for si, nframes in enumerate(counts):
            if cancel_check:
                cancel_check()
            if deadline and time.monotonic() > deadline:
                raise RenderTimeout("Render exceeded VIDEO_RENDER_TIMEOUT_SECONDS.")
            chunks = caption_chunks(sb.scenes[si].narration) if captions else []
            cache: Dict[int, bytes] = {}
            anim_frames = int(ANIM_SECONDS * fps)
            fade_frames = int(FADE_SECONDS * fps) if prev_final is not None else 0
            for fi in range(nframes):
                t = fi / fps
                a = 1.0 if fi >= anim_frames else fi / max(1, anim_frames)
                ci, cap = caption_at(chunks, t, durations[si])
                if fi >= anim_frames and fi >= fade_frames and ci in cache:
                    raw = cache[ci]
                else:
                    img = drawer.draw(si, a, cap)
                    if fi < fade_frames and prev_final is not None:
                        img = Image.blend(prev_final, img, _ease((fi + 1) / (fade_frames + 1)))
                    raw = img.tobytes()
                    if fi >= anim_frames and fi >= fade_frames:
                        cache[ci] = raw
                try:
                    proc.stdin.write(raw)
                except (BrokenPipeError, OSError):
                    raise RenderError("ffmpeg terminated unexpectedly: " + _read_err(errlog))
                written += 1
                if fi % fps == 0:
                    if cancel_check:
                        cancel_check()
                    if deadline and time.monotonic() > deadline:
                        raise RenderTimeout("Render exceeded VIDEO_RENDER_TIMEOUT_SECONDS.")
                    if progress:
                        progress(written / total_frames)
            prev_final = drawer.draw(si, 1.0, "")
        proc.stdin.close()
        rc = proc.wait(timeout=120)
        if rc != 0:
            raise RenderError("ffmpeg failed: " + _read_err(errlog))
    except BaseException:
        _kill(proc)
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass
        raise
    finally:
        errlog.close()
    if progress:
        progress(1.0)
    return RenderResult(out_path, written / fps, width, height, fps, bool(audio_path), written)


def _read_err(f) -> str:
    try:
        f.seek(0)
        return f.read().decode("utf-8", "replace")[-500:]
    except Exception:
        return ""


def _kill(proc):
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception:
        pass
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


# ----------------------------------------------------------------------------- validation
def inspect_mp4(path: str) -> Dict[str, Any]:
    proc = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", path], capture_output=True, text=True, timeout=60)
    err = proc.stderr
    dm = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", err)
    vm = re.search(r"Video: (\w+).*?, (\d{2,5})x(\d{2,5})", err)
    fm = re.search(r"(\d+(?:\.\d+)?) fps", err)
    return {"duration": int(dm[1]) * 3600 + int(dm[2]) * 60 + float(dm[3]) if dm else None,
            "codec": vm[1] if vm else None, "width": int(vm[2]) if vm else None, "height": int(vm[3]) if vm else None,
            "fps": float(fm[1]) if fm else None, "has_audio": bool(re.search(r"Stream #.*Audio:", err))}


def validate_mp4(path: str, *, expected_duration: float, width: int, height: int, audio: bool) -> Dict[str, Any]:
    """Raises RenderError unless the file is a decodable H.264 MP4 of the expected size and runtime."""
    if not os.path.isfile(path) or os.path.getsize(path) < 1024:
        raise RenderError("Rendered file is missing or too small.")
    with open(path, "rb") as fh:
        if fh.read(12)[4:8] != b"ftyp":
            raise RenderError("Output is not an MP4 container.")
    info = inspect_mp4(path)
    if info["codec"] != "h264":
        raise RenderError(f"Unexpected video codec: {info['codec']}")
    if (info["width"], info["height"]) != (width, height):
        raise RenderError(f"Unexpected resolution {info['width']}x{info['height']}")
    if info["duration"] is None or abs(info["duration"] - expected_duration) > max(1.0, expected_duration * 0.03):
        raise RenderError(f"Runtime {info['duration']}s differs from expected {expected_duration:.1f}s")
    if info["has_audio"] != audio:
        raise RenderError("Audio track presence does not match the requested mode.")
    dec = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", path, "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    if dec.returncode != 0 or dec.stderr.strip():
        raise RenderError("Decode check failed: " + dec.stderr.strip()[:300])
    return info


class PillowRenderer:
    """Default renderer: default entry point used by the worker (replaceable in tests / future Remotion backend)."""
    name = "pillow"

    def render(self, payload, sb, out_path, **kw) -> RenderResult:
        return render_video(payload, sb, out_path, **kw)
