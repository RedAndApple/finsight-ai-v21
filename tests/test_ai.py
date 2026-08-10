import asyncio
from types import SimpleNamespace

from app import ai
from app.ai import _analysis_item_text, _chat_endpoint, _extract_json


def test_chat_endpoint_accepts_base_or_full_endpoint():
    assert _chat_endpoint("https://example.test/v1") == "https://example.test/v1/chat/completions"
    assert _chat_endpoint("https://example.test/v1/chat/completions") == "https://example.test/v1/chat/completions"


def test_extract_json_accepts_code_fence():
    value = _extract_json('```json\n{"executive_summary":"ok","strengths":[]}\n```')
    assert value["executive_summary"] == "ok"


def test_structured_action_is_rendered_as_prose_not_python_dict():
    item = {
        "id": "A1",
        "responds_to": ["F1", "F2"],
        "action": "Сформировать ежемесячный финансовый мониторинг с подтвержденными границами.",
    }
    text = _analysis_item_text(item)
    assert text == item["action"]
    assert "responds_to" not in text
    assert "{'id'" not in text


def test_reasoning_model_retries_with_legacy_token_parameter(monkeypatch):
    requests = []

    class Response:
        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self._payload = payload or {}
            self.text = "unsupported parameter"
            self.is_success = status_code < 400

        def raise_for_status(self):
            if not self.is_success:
                raise AssertionError(f"unexpected final HTTP {self.status_code}")

        def json(self):
            return self._payload

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _endpoint, headers, json):
            requests.append(json)
            if "max_completion_tokens" in json:
                return Response(400)
            return Response(200, {
                "model": "openai/gpt-5.6-sol",
                "choices": [{"message": {"content": '{"executive_summary":"ok"}'}}],
            })

    monkeypatch.setattr(ai, "settings", SimpleNamespace(
        ai_api_key="test", ai_auth_scheme="Bearer", ai_auth_header="Authorization",
        ai_base_url="https://gateway.test/v1", ai_model="openai/gpt-5.6-sol",
        ai_site_url="http://localhost", ai_app_name="FinSight AI",
    ))
    monkeypatch.setattr(ai.httpx, "AsyncClient", Client)
    result = asyncio.run(ai.compatible_chat([{"role": "user", "content": "test"}], 500))
    assert "max_completion_tokens" in requests[0]
    assert "max_tokens" in requests[1]
    assert result["executive_summary"] == "ok"
