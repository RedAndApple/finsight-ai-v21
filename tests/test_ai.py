from app.ai import _chat_endpoint, _extract_json


def test_chat_endpoint_accepts_base_or_full_endpoint():
    assert _chat_endpoint("https://example.test/v1") == "https://example.test/v1/chat/completions"
    assert _chat_endpoint("https://example.test/v1/chat/completions") == "https://example.test/v1/chat/completions"


def test_extract_json_accepts_code_fence():
    value = _extract_json('```json\n{"executive_summary":"ok","strengths":[]}\n```')
    assert value["executive_summary"] == "ok"
