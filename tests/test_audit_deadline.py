import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hardware_hub.config import Settings


class _SlowSyncStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes], delay_seconds: float) -> None:
        self._chunks = chunks
        self._delay_seconds = delay_seconds

    def __iter__(self):
        for chunk in self._chunks:
            time.sleep(self._delay_seconds)
            yield chunk


class _SlowAsyncStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes], delay_seconds: float) -> None:
        self._chunks = chunks
        self._delay_seconds = delay_seconds

    async def __aiter__(self):
        for chunk in self._chunks:
            await asyncio.sleep(self._delay_seconds)
            yield chunk


class _TrickleTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    def __init__(self, body: bytes, *, chunk_count: int, delay_seconds: float) -> None:
        chunk_size = max(1, (len(body) + chunk_count - 1) // chunk_count)
        self._chunks = [
            body[index : index + chunk_size] for index in range(0, len(body), chunk_size)
        ]
        self._delay_seconds = delay_seconds

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            stream=_SlowSyncStream(self._chunks, self._delay_seconds),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            stream=_SlowAsyncStream(self._chunks, self._delay_seconds),
        )


def test_deepseek_trickle_response_obeys_total_deadline(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = client.post(
        "/login",
        data={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303

    app.state.settings.llm_base_url = "https://api.deepseek.test/v1/"
    app.state.settings.llm_model = "deepseek-v4-flash"
    app.state.settings.llm_api_key = "test-deepseek-key"
    monkeypatch.setattr("hardware_hub.audit._TOTAL_TIMEOUT_SECONDS", 0.05)
    provider_body = json.dumps(
        {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": '{"findings":[]}'},
                }
            ]
        }
    ).encode()
    app.state.llm_transport = _TrickleTransport(
        provider_body,
        chunk_count=20,
        delay_seconds=0.02,
    )

    started = time.monotonic()
    response = client.post("/admin/audit/llm")
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < 0.25
    assert "DeepSeek audit was unavailable or invalid." in response.text
    assert "Deterministic findings remain complete." in response.text
    assert "AI suggestions — not operational decisions" not in response.text
