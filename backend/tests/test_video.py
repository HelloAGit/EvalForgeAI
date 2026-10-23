import json
import os
from datetime import timedelta

import pytest
from pypdf import PdfReader

from app.config import settings
from app.database import SessionLocal
from app.models.entities import GeneratedArtifact, VideoJob, utcnow
from app.services import narrative as nv, video_renderer as vr, video_worker as vw
from app.services.mubit_gateway import GatewayError
from app.services.tts import MockTTS, NoTTS, TTSError, wav_info, HttpTTS
from tests.test_narrative import FakeGateway, good_json


@pytest.fixture
def report_id(client, user_h, seeded):
    r = client.post("/api/v1/reports", headers=user_h, json={"title": "R", "template": "executive", "project_id": seeded["project"]})
    assert r.status_code == 201
    return r.json()["id"]


def make_video(client, user_h, report_id, **kw):
    body = {"report_id": report_id, "duration_seconds": 60, "mode": "silent", "captions": True, **kw}
    r = client.post("/api/v1/videos", headers=user_h, json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def state(client, user_h, vid):
    return client.get(f"/api/v1/videos/{vid}", headers=user_h).json()


def claude_json(client, user_h, report_id):
    snap = client.get(f"/api/v1/reports/{report_id}/snapshot", headers=user_h).json()["payload"]
    return json.dumps(good_json(snap))


def run_worker(db, **kw):
    return vw.process_next(db, "test-worker", **kw)


def probe(data: bytes, tmp_path):
    p = tmp_path / "out.mp4"
    p.write_bytes(data)
    return vr.inspect_mp4(str(p)), str(p)


def test_create_validation_and_permissions(client, user_h, other_h, report_id, monkeypatch):
    body = {"report_id": report_id}
    assert client.post("/api/v1/videos", json=body).status_code == 401
    assert client.post("/api/v1/videos", headers=other_h, json=body).status_code == 404  # not the report owner
    assert client.post("/api/v1/videos", headers=user_h, json={**body, "duration_seconds": 45}).status_code == 422
    assert client.post("/api/v1/videos", headers=user_h, json={**body, "mode": "loud"}).status_code == 422
    assert client.post("/api/v1/videos", headers=user_h, json={**body, "sections": ["nope"]}).status_code == 422
    assert client.post("/api/v1/videos", headers=user_h, json={"report_id": "missing"}).status_code == 404
    r = client.post("/api/v1/videos", headers=user_h, json={**body, "mode": "narrated"})
    assert r.status_code == 422 and "TTS" in r.json()["detail"]
    vid = make_video(client, user_h, report_id)
    for method, path in (("get", ""), ("get", "/download"), ("post", "/cancel"), ("post", "/approve"), ("post", "/render")):
        assert getattr(client, method)(f"/api/v1/videos/{vid}{path}", headers=other_h).status_code == 404, path
        assert getattr(client, method)(f"/api/v1/videos/{vid}{path}").status_code == 401, path
    assert client.put(f"/api/v1/videos/{vid}/storyboard", headers=other_h, json={}).status_code == 404
    assert client.get("/api/v1/videos", headers=other_h).json() == []
    assert len(client.get("/api/v1/videos", headers=user_h).json()) == 1


def test_capabilities_reflect_configuration(client, user_h, monkeypatch):
    c = client.get("/api/v1/videos/capabilities", headers=user_h).json()
    assert c["tts_available"] is False and c["voices"] == [] and c["mubit_configured"] is False
    import app.routers.videos as rv
    monkeypatch.setattr(rv, "get_tts", lambda: MockTTS())
    c = client.get("/api/v1/videos/capabilities", headers=user_h).json()
    assert c["tts_available"] is True and c["voices"] == ["mock-voice"]


def test_active_job_limit(client, user_h, report_id, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_MAX_ACTIVE_PER_USER", 2)
    make_video(client, user_h, report_id)
    make_video(client, user_h, report_id)
    r = client.post("/api/v1/videos", headers=user_h, json={"report_id": report_id})
    assert r.status_code == 429


def test_full_state_machine_silent_mp4(client, user_h, db, report_id, tmp_path):
    vid = make_video(client, user_h, report_id)
    j = state(client, user_h, vid)
    assert j["state"] == "QUEUED" and j["storyboard"] is None
    assert client.get(f"/api/v1/videos/{vid}/download", headers=user_h).status_code == 409  # not ready
    assert client.post(f"/api/v1/videos/{vid}/render", headers=user_h).status_code == 409  # not awaiting approval

    assert run_worker(db, gateway=FakeGateway(claude_json(client, user_h, report_id))) == 1
    j = state(client, user_h, vid)
    assert j["state"] == "AWAITING_APPROVAL" and j["storyboard_source"] == "claude" and j["validation"]["ok"]
    assert j["approved"] is False and j["storyboard"]["scenes"][0]["type"] == "title"
    assert client.post(f"/api/v1/videos/{vid}/render", headers=user_h).status_code == 409  # not approved

    assert client.post(f"/api/v1/videos/{vid}/approve", headers=user_h).json()["approved"] is True
    r = client.post(f"/api/v1/videos/{vid}/render", headers=user_h)
    assert r.status_code == 202 and r.json()["state"] == "RENDERING"
    assert run_worker(db) == 1
    j = state(client, user_h, vid)
    assert j["state"] == "COMPLETED" and j["progress"] == 1.0 and j["artifact"]["size_bytes"] > 1000

    dl = client.get(f"/api/v1/videos/{vid}/download", headers=user_h)
    assert dl.status_code == 200 and dl.headers["content-type"] == "video/mp4" and dl.headers["x-content-type-options"] == "nosniff"
    info, _ = probe(dl.content, tmp_path)
    assert dl.content[4:8] == b"ftyp" and info["codec"] == "h264" and info["has_audio"] is False
    assert (info["width"], info["height"]) == (settings.VIDEO_WIDTH, settings.VIDEO_HEIGHT)
    assert abs(info["duration"] - j["storyboard"]["total_duration_seconds"]) < 1.0
    assert client.post(f"/api/v1/videos/{vid}/cancel", headers=user_h).status_code == 409  # terminal
    assert os.listdir(os.path.join(os.environ["ARTIFACT_DIR"], "tmp")) == []  # temp files cleaned up


def test_template_fallback_when_claude_unavailable(client, user_h, db, report_id):
    vid = make_video(client, user_h, report_id)
    run_worker(db, gateway=FakeGateway(exc=GatewayError("down")))
    j = state(client, user_h, vid)
    assert j["state"] == "AWAITING_APPROVAL" and j["storyboard_source"] == "template"
    assert j["validation"]["flags"][0]["type"] == "claude_unavailable" and j["validation"]["ok"]


def test_flags_require_acknowledgement_and_edits_reset_approval(client, user_h, db, report_id):
    vid = make_video(client, user_h, report_id)
    bad = good_json(client.get(f"/api/v1/reports/{report_id}/snapshot", headers=user_h).json()["payload"])
    bad["scenes"][1]["narration"] = "Correctness reached 99.9 percent."
    run_worker(db, gateway=FakeGateway(json.dumps(bad)))
    j = state(client, user_h, vid)
    assert j["validation"]["ok"] is False
    r = client.post(f"/api/v1/videos/{vid}/approve", headers=user_h)
    assert r.status_code == 409 and r.json()["detail"]["flags"][0]["type"] == "unsupported_number"
    # user edits the script to fix the claim -> re-validated -> approvable without acknowledgement
    sb = j["storyboard"]
    sb["scenes"][1]["narration"] = "Correctness was 68.8 percent."
    e = client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json={"storyboard": sb})
    assert e.status_code == 200 and e.json()["validation"]["ok"] and e.json()["validation"]["edited"]
    assert client.post(f"/api/v1/videos/{vid}/approve", headers=user_h).json()["approved"] is True
    # editing after approval invalidates the approval
    sb["scenes"][1]["narration"] = "Correctness was about 69 percent."
    assert client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json=sb).json()["approved"] is False
    assert client.post(f"/api/v1/videos/{vid}/render", headers=user_h).status_code == 409
    # acknowledging flags allows approval of an unverifiable claim
    sb["scenes"][1]["narration"] = "Correctness reached 99.9 percent."
    client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json=sb)
    assert client.post(f"/api/v1/videos/{vid}/approve", headers=user_h, json={"acknowledge_flags": True}).json()["approved"] is True


def test_invalid_storyboard_edit_rejected_and_wrong_state(client, user_h, db, report_id):
    vid = make_video(client, user_h, report_id)
    assert client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json={}).status_code == 409  # still queued
    run_worker(db, gateway=FakeGateway(exc=GatewayError("x")))
    assert client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json={"title": "x", "scenes": []}).status_code == 422
    long = state(client, user_h, vid)["storyboard"]
    long["scenes"][0]["duration_seconds"] = 61
    assert client.put(f"/api/v1/videos/{vid}/storyboard", headers=user_h, json=long).status_code == 422


def approve_to_render(client, user_h, db, report_id, **kw):
    vid = make_video(client, user_h, report_id, **kw)
    run_worker(db, gateway=FakeGateway(exc=GatewayError("offline")))
    assert client.post(f"/api/v1/videos/{vid}/approve", headers=user_h).status_code == 200
    assert client.post(f"/api/v1/videos/{vid}/render", headers=user_h).status_code == 202
    return vid


def test_cancel_before_start_and_while_awaiting(client, user_h, db, report_id):
    vid = make_video(client, user_h, report_id)
    assert client.post(f"/api/v1/videos/{vid}/cancel", headers=user_h).json()["state"] == "CANCELLED"
    assert run_worker(db, gateway=FakeGateway("{}")) == 0  # cancelled jobs are never claimed
    vid2 = make_video(client, user_h, report_id)
    run_worker(db, gateway=FakeGateway(exc=GatewayError("x")))
    assert client.post(f"/api/v1/videos/{vid2}/cancel", headers=user_h).json()["state"] == "CANCELLED"
    assert client.post(f"/api/v1/videos/{vid2}/approve", headers=user_h).status_code == 409


def test_cancel_during_render_stops_ffmpeg_and_leaves_no_artifact(client, user_h, db, report_id):
    vid = approve_to_render(client, user_h, db, report_id)

    class CancellingRenderer:
        def render(self, payload, sb, out, cancel_check=None, **kw):
            with SessionLocal() as other:  # user presses cancel while the worker is rendering
                other.get(VideoJob, vid).state = "CANCELLED"
                other.commit()
            return vr.render_video(payload, sb, out, cancel_check=cancel_check, **{k: v for k, v in kw.items() if k != "timeout"})

    run_worker(db, renderer=CancellingRenderer())
    j = state(client, user_h, vid)
    assert j["state"] == "CANCELLED" and j["artifact"] is None
    assert db.query(GeneratedArtifact).filter_by(video_id=vid).count() == 0
    assert os.listdir(os.path.join(os.environ["ARTIFACT_DIR"], "tmp")) == []


def test_failed_render_retries_then_reports_error(client, user_h, db, report_id, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_MAX_ATTEMPTS", 2)
    vid = approve_to_render(client, user_h, db, report_id)

    class Boom:
        def render(self, *a, **k):
            raise vr.RenderError("encoder exploded")

    run_worker(db, renderer=Boom())
    j = state(client, user_h, vid)
    assert j["state"] == "RENDERING" and "encoder exploded" in j["error_message"]  # first attempt: re-queued
    run_worker(db, renderer=Boom())
    j = state(client, user_h, vid)
    assert j["state"] == "FAILED" and "encoder exploded" in j["error_message"] and j["artifact"] is None
    assert client.get(f"/api/v1/videos/{vid}/download", headers=user_h).status_code == 409


def test_timeout_is_not_retried(client, user_h, db, report_id):
    vid = approve_to_render(client, user_h, db, report_id)

    class Slow:
        def render(self, *a, **k):
            raise vr.RenderTimeout("Render exceeded VIDEO_RENDER_TIMEOUT_SECONDS.")

    run_worker(db, renderer=Slow())
    assert state(client, user_h, vid)["state"] == "FAILED"


def test_real_timeout_kills_render(db, seeded):
    from app.services.snapshot import build_payload
    p = build_payload(db, "user1", {"project_id": seeded["project"]}, "s")
    sb = nv.fit_duration(nv.template_storyboard(p, {"duration_seconds": 60}), 20)
    with pytest.raises(vr.RenderTimeout):
        vr.render_video(p, sb, os.path.join(os.environ["ARTIFACT_DIR"], "t.mp4"), timeout=0.0001)
    assert not os.path.exists(os.path.join(os.environ["ARTIFACT_DIR"], "t.mp4"))


def test_unapproved_or_tampered_storyboard_is_never_rendered(client, user_h, db, report_id):
    vid = approve_to_render(client, user_h, db, report_id)
    job = db.get(VideoJob, vid)
    sb = dict(job.storyboard)
    sb["title"] = "Tampered after approval"
    job.storyboard = sb
    db.commit()
    run_worker(db)
    j = state(client, user_h, vid)
    assert j["state"] == "FAILED" and "not approved" in j["error_message"]


def test_expired_lease_is_recovered_then_fails_after_max_attempts(client, user_h, db, report_id, monkeypatch):
    monkeypatch.setattr(settings, "VIDEO_MAX_ATTEMPTS", 2)
    vid = make_video(client, user_h, report_id)
    job = db.get(VideoJob, vid)
    job.state, job.locked_by, job.attempts = "GENERATING_SCRIPT", "dead-worker", 1
    job.lease_expires_at = utcnow() - timedelta(seconds=5)
    db.commit()
    assert vw.recover_expired(db) == 1 and db.get(VideoJob, vid).state == "QUEUED"
    job = db.get(VideoJob, vid)
    job.state, job.locked_by, job.attempts, job.lease_expires_at = "GENERATING_SCRIPT", "dead", 2, utcnow() - timedelta(seconds=5)
    db.commit()
    vw.recover_expired(db)
    assert db.get(VideoJob, vid).state == "FAILED"


def test_atomic_claim_gives_job_to_one_worker(client, user_h, db, report_id):
    make_video(client, user_h, report_id)
    with SessionLocal() as db2:
        a = vw._claim(db, "QUEUED", "w1", "GENERATING_SCRIPT", "x")
        b = vw._claim(db2, "QUEUED", "w2", "GENERATING_SCRIPT", "x")
    assert a is not None and b is None


def test_narrated_mode_uses_tts_and_muxes_audio(client, user_h, db, report_id, monkeypatch, tmp_path):
    import app.routers.videos as rv
    tts = MockTTS()
    monkeypatch.setattr(rv, "get_tts", lambda: tts)
    vid = make_video(client, user_h, report_id, mode="narrated", voice="mock-voice")
    run_worker(db, gateway=FakeGateway(exc=GatewayError("offline")))
    client.post(f"/api/v1/videos/{vid}/approve", headers=user_h)
    client.post(f"/api/v1/videos/{vid}/render", headers=user_h)
    run_worker(db, tts=tts)
    j = state(client, user_h, vid)
    assert j["state"] == "COMPLETED", j["error_message"]
    assert tts.calls and all(v == "mock-voice" for _, v in tts.calls)
    info, _ = probe(client.get(f"/api/v1/videos/{vid}/download", headers=user_h).content, tmp_path)
    assert info["has_audio"] is True and info["duration"] >= j["storyboard"]["total_duration_seconds"] - 1


def test_narrated_without_provider_fails_cleanly(client, user_h, db, report_id, monkeypatch):
    import app.routers.videos as rv
    monkeypatch.setattr(rv, "get_tts", lambda: MockTTS())
    vid = make_video(client, user_h, report_id, mode="narrated")
    run_worker(db, gateway=FakeGateway(exc=GatewayError("x")))
    client.post(f"/api/v1/videos/{vid}/approve", headers=user_h)
    client.post(f"/api/v1/videos/{vid}/render", headers=user_h)
    run_worker(db, tts=NoTTS())
    j = state(client, user_h, vid)
    assert j["state"] == "FAILED" and "TTS" in j["error_message"]


def test_plan_narration_extends_scene_durations_to_fit_speech(tmp_path, db, seeded):
    from app.services.snapshot import build_payload
    p = build_payload(db, "user1", {"project_id": seeded["project"]}, "s")
    sb = nv.template_storyboard(p, {"duration_seconds": 60})
    sb.scenes[0].duration_seconds = 2
    sb.scenes[0].narration = "word " * 100
    wav, durs = vr.plan_narration(sb, MockTTS(seconds_per_char=0.05), "v", str(tmp_path))
    assert durs[0] >= 25 and len(durs) == len(sb.scenes)
    assert abs(wav_info(open(wav, "rb").read())["seconds"] - sum(durs)) < 0.05
    sb.scenes[1].narration = "x" * (settings.TTS_MAX_CHARS_PER_SCENE + 1)
    with pytest.raises(vr.RenderError):
        vr.plan_narration(sb, MockTTS(), "v", str(tmp_path))


def test_tts_provider_interface(monkeypatch):
    assert NoTTS().available() is False
    with pytest.raises(TTSError):
        NoTTS().synthesize("x", "v")
    monkeypatch.setattr(settings, "TTS_ENDPOINT_URL", "")
    assert HttpTTS().available() is False
    with pytest.raises(TTSError):
        wav_info(b"not wav")


def test_renderer_uses_snapshot_values_not_storyboard_numbers(db, seeded, tmp_path):
    """A storyboard cannot alter chart/KPI numbers: frames are drawn from the snapshot."""
    from app.services.snapshot import build_payload
    p = build_payload(db, "user1", {"project_id": seeded["project"]}, "s")
    sb = nv.fit_duration(nv.template_storyboard(p, {"duration_seconds": 60, "sections": ["llm"]}), 8)
    sb.scenes[1].on_screen_text = ["Correctness 12.3%"]
    a = vr.SceneDrawer(p, sb, 640, 360, False).draw(1, 1.0).tobytes()
    p2 = json.loads(json.dumps(p))
    next(m for m in p2["metrics"] if m["key"] == "llm_correctness")["value"] = 0.2
    b = vr.SceneDrawer(p2, sb, 640, 360, False).draw(1, 1.0).tobytes()
    assert a != b  # drawing depends on the snapshot value
    sb2 = sb.model_copy(deep=True)
    sb2.scenes[1].narration = "completely different narration"
    assert vr.SceneDrawer(p, sb2, 640, 360, False).draw(1, 1.0).tobytes() == a  # narration alone does not change the chart


def test_validate_mp4_rejects_bad_files(tmp_path):
    f = tmp_path / "x.mp4"
    f.write_bytes(b"nope")
    with pytest.raises(vr.RenderError):
        vr.validate_mp4(str(f), expected_duration=1, width=2, height=2, audio=False)
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000)
    with pytest.raises(vr.RenderError):
        vr.validate_mp4(str(f), expected_duration=1, width=2, height=2, audio=False)


def test_caption_timing():
    chunks = vr.caption_chunks("one two three four five six seven eight nine ten", 15)
    assert len(chunks) >= 3 and " ".join(chunks) == "one two three four five six seven eight nine ten"
    assert vr.caption_at(chunks, 0, 10)[0] == 0 and vr.caption_at(chunks, 9.99, 10)[0] == len(chunks) - 1
    assert vr.caption_at([], 1, 5) == (-1, "")


def test_end_to_end_results_to_snapshot_pdf_storyboard_silent_mp4(client, user_h, db, seeded, tmp_path):
    """eval results -> immutable snapshot -> PDF -> (mocked) Claude storyboard -> approved -> silent MP4."""
    r = client.post("/api/v1/reports", headers=user_h, json={"title": "E2E", "template": "technical", "project_id": seeded["project"]})
    rid = r.json()["id"]
    snap = client.get(f"/api/v1/reports/{rid}/snapshot", headers=user_h).json()
    pdf = client.get(f"/api/v1/reports/{rid}/download", headers=user_h).content
    assert len(PdfReader(__import__("io").BytesIO(pdf)).pages) >= 3
    vid = make_video(client, user_h, rid, duration_seconds=60)
    run_worker(db, gateway=FakeGateway(json.dumps(good_json(snap["payload"]))))
    j = state(client, user_h, vid)
    assert j["storyboard_source"] == "claude" and j["validation"]["ok"]
    client.post(f"/api/v1/videos/{vid}/approve", headers=user_h)
    client.post(f"/api/v1/videos/{vid}/render", headers=user_h)
    run_worker(db)
    j = state(client, user_h, vid)
    assert j["state"] == "COMPLETED"
    mp4 = client.get(f"/api/v1/videos/{vid}/download", headers=user_h).content
    info, path = probe(mp4, tmp_path)
    assert info["codec"] == "h264" and not info["has_audio"]
    art = db.query(GeneratedArtifact).filter_by(video_id=vid).one()
    assert art.meta["snapshot_sha256"] == snap["payload_sha256"]  # video is traceable to the exact snapshot the PDF used
    assert vr.validate_mp4(path, expected_duration=info["duration"], width=info["width"], height=info["height"], audio=False)
