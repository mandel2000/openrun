import os
import tempfile

os.environ["OPENRUN_DB"] = os.path.join(tempfile.mkdtemp(), "coach.db")

from types import SimpleNamespace  # noqa: E402

from sqlmodel import Session  # noqa: E402

from app import services as S  # noqa: E402
from app.ai import coach  # noqa: E402
from app.db import engine, init_db  # noqa: E402


class Block(SimpleNamespace):
    def model_dump(self, exclude_none=True):
        return {k: v for k, v in self.__dict__.items() if v is not None or not exclude_none}


class FakeClient:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                Block(type="text", text="Creo la sesión."),
                Block(type="tool_use", id="t1", name="create_workout", input={
                    "date": "2026-12-03", "title": "Umbral 3×10'", "type": "threshold", "intensity": "moderate",
                    "description": "Umbral de lactato",
                    "steps": [{"kind": "warmup", "duration_type": "time", "duration_value": 900, "zone": "easy"},
                              {"kind": "repeat", "repeat": 3, "steps": [
                                  {"kind": "run", "duration_type": "time", "duration_value": 600, "zone": "threshold"},
                                  {"kind": "recovery", "duration_type": "time", "duration_value": 120}]},
                              {"kind": "cooldown", "duration_type": "time", "duration_value": 600, "zone": "easy"}]}),
            ])
        return SimpleNamespace(stop_reason="end_turn", content=[Block(type="text", text="Listo: 3×10' a umbral.")])


def test_chat_tool_loop(monkeypatch):
    init_db()
    fake = FakeClient()
    monkeypatch.setattr(coach, "_client", lambda: fake)
    with Session(engine) as s:
        S.update_athlete(s, vdot=50)
        out = coach.chat(s, "Hazme un umbral el jueves")
        assert out["reply"] == "Listo: 3×10' a umbral."
        assert out["tools"] == [{"tool": "create_workout", "ok": True}]
        ws = S.list_workouts(s, "2026-12-03", "2026-12-03")
        assert len(ws) == 1
        rep = ws[0]["steps"][1]
        assert rep["steps"][0]["pace_slow"] and rep["steps"][0]["pace_fast"] < rep["steps"][0]["pace_slow"]
        # second request carries assistant tool_use + user tool_result (append-only history)
        msgs = fake.calls[1]["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
        assert msgs[2]["content"][0]["type"] == "tool_result"
        assert fake.calls[0]["model"] == coach.MODEL
        assert [m["role"] for m in coach.visible_history(s)] == ["user", "assistant", "assistant"]


def test_extra_run_warns_on_volume_jump():
    init_db()
    with Session(engine) as s:
        S.update_athlete(s, vdot=45)
        S.create_plan(s, {"goal": "10k", "start_date": "2027-01-04", "days_per_week": 3, "long_run_day": 5,
                          "current_weekly_km": 30, "level": "intermediate"})
        r = S.add_extra_run(s, "2027-01-14", 10)
        assert r["extra"] and r["type"] == "easy" and r["intensity"] == "low"
        assert any("+10 %" in w for w in r["warnings"])
        assert any(x["id"] == r["id"] for x in S.list_workouts(s, "2027-01-14", "2027-01-14"))


class _Fn(SimpleNamespace):
    pass


class FakeOpenAI:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if len(self.calls) == 1:
            call = Block(id="c1", type="function", function=Block(name="calculate_vdot", arguments='{"distance": "5k", "time": "20:00"}'))
            msg = SimpleNamespace(content=None, tool_calls=[call])
        else:
            msg = SimpleNamespace(content="VDOT ~49.8", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_openai_compat_loop(monkeypatch):
    init_db()
    fake = FakeOpenAI()
    monkeypatch.setenv("OPENRUN_PROVIDER", "gemini")
    monkeypatch.setattr(coach, "_openai_client", lambda: fake)
    with Session(engine) as s:
        coach.reset(s)
        out = coach.chat(s, "¿Qué VDOT tengo con 5K en 20:00?")
        assert out == {"reply": "VDOT ~49.8", "tools": [{"tool": "calculate_vdot", "ok": True}]}
        msgs = fake.calls[1]["messages"]
        assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
        assert msgs[2]["tool_calls"][0]["function"]["name"] == "calculate_vdot"
        assert fake.calls[0]["tools"][0]["type"] == "function"
        assert [m["role"] for m in coach.visible_history(s)] == ["user", "tool", "assistant"]


def test_nvidia_provider_config(monkeypatch):
    monkeypatch.setenv("OPENRUN_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.delenv("OPENRUN_MODEL", raising=False)
    info = coach.provider_info()
    assert info == {"provider": "nvidia", "model": "minimaxai/minimax-m3.1-flash", "configured": True}
    c = coach._openai_client()
    assert str(c.base_url).startswith("https://integrate.api.nvidia.com/v1") and c.max_retries == 4


def _chunk(content=None, calls=None):
    delta = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _tc(index, id=None, name=None, args=None):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=args))


class FakeStreaming:
    """First model times out; fallback streams a tool call in pieces, then a text answer."""

    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        import httpx
        import openai
        self.calls.append(kw)
        if kw["model"] == "bad/model":
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://x"))
        if sum(1 for c in self.calls if c["model"] == "good/model") == 1:
            return iter([_chunk(calls=[_tc(0, "c1", "calculate_vdot", '{"distance": "5k",')]),
                         _chunk(calls=[_tc(0, args=' "time": "20:00"}')])])
        return iter([_chunk("Tu VDOT ronda "), _chunk("49,8 ристи."), _chunk(" 좋아")])


def test_streaming_events_fallback_and_sanitize(monkeypatch):
    init_db()
    fake = FakeStreaming()
    monkeypatch.setenv("OPENRUN_PROVIDER", "nvidia")
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("OPENRUN_MODEL", "bad/model")
    monkeypatch.setenv("OPENRUN_MODEL_FALLBACKS", "good/model")
    monkeypatch.setattr(coach, "_openai_client", lambda: fake)
    with Session(engine) as s:
        coach.reset(s)
        evs = list(coach.chat_events(s, "¿VDOT con 5K en 20:00?"))
        kinds = [e["type"] for e in evs]
        assert kinds[0] == "status" and "good/model" in evs[0]["text"]
        assert {"type": "tool", "name": "calculate_vdot"} in evs
        done = evs[-1]
        assert done["type"] == "done" and done["tools"] == [{"tool": "calculate_vdot", "ok": True}]
        assert done["reply"] == "Tu VDOT ronda 49,8 . " and "".join(e["delta"] for e in evs if e["type"] == "text") == done["reply"]
        sys_msg = fake.calls[-1]["messages"][0]["content"]
        assert "RESUMEN ACTUAL DEL ATLETA" in sys_msg and '"hoy"' in sys_msg
        assert fake.calls[-1]["stream"] is True and fake.calls[-1]["temperature"] == 0.3 and fake.calls[-1]["reasoning_effort"] == "low"
        tool_msg = fake.calls[-1]["messages"][-1]
        assert tool_msg["role"] == "tool" and '"vdot"' in tool_msg["content"]


def test_context_snapshot_is_compact_json():
    import json as _json
    init_db()
    with Session(engine) as s:
        snap = _json.loads(coach.context_snapshot(s))
        assert "hoy" in snap and "atleta" in snap
        assert len(coach.context_snapshot(s)) < 12000
