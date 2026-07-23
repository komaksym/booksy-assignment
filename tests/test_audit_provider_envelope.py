import copy
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hardware_hub.config import Settings


def _login_admin(client: TestClient, settings: Settings) -> None:
    response = client.post(
        "/login",
        data={
            "email": settings.bootstrap_admin_email,
            "password": settings.bootstrap_admin_password,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def _configure_llm(app: FastAPI) -> None:
    app.state.settings.llm_base_url = "https://api.deepseek.test/v1/"
    app.state.settings.llm_model = "deepseek-v4-flash"
    app.state.settings.llm_api_key = "test-deepseek-key"


@pytest.mark.parametrize("failure_mode", ["unexpected-envelope", "non-stop"])
def test_unexpected_or_incomplete_provider_envelope_falls_back(
    failure_mode: str,
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    _login_admin(client, settings)
    _configure_llm(app)
    before = copy.deepcopy(app.state.hardware.all())
    explanation = "This incomplete suggestion must never render."
    valid_content = json.dumps(
        {
            "findings": [
                {
                    "hardware_id": before[0]["id"],
                    "severity": "warning",
                    "explanation": explanation,
                    "recommendation": "Do not render this row.",
                }
            ]
        }
    )

    def provider(_request: httpx.Request) -> httpx.Response:
        if failure_mode == "unexpected-envelope":
            return httpx.Response(200, json={"choices": [None]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": valid_content},
                    }
                ]
            },
        )

    app.state.llm_transport = httpx.MockTransport(provider)
    response = client.post("/admin/audit/llm")

    assert response.status_code == 200
    assert "DeepSeek audit was unavailable or invalid." in response.text
    assert "Deterministic findings remain complete." in response.text
    assert "AI suggestions — not operational decisions" not in response.text
    assert explanation not in response.text
    assert app.state.hardware.all() == before
