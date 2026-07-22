import copy
import json
from uuid import uuid4

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


def _provider_response(content: str, *, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": finish_reason,
                    "message": {"content": content},
                }
            ]
        },
    )


def test_audit_access_and_deterministic_get(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    for method, route in (
        (client.get, "/admin/audit"),
        (client.post, "/admin/audit/llm"),
    ):
        response = method(route, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    calls = 0

    def unexpected_call(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError(f"GET must not call the provider: {request.url}")

    app.state.llm_transport = httpx.MockTransport(unexpected_call)
    _login_admin(client, settings)

    response = client.get("/admin/audit")

    assert response.status_code == 200
    assert calls == 0
    assert "Deterministic findings" in response.text
    assert "These findings govern application safety decisions." in response.text
    assert "INVALID_STATUS" in response.text
    assert "SAFETY_RISK" in response.text
    assert "Request DeepSeek second opinion" in response.text
    assert "disabled" in response.text
    assert "LLM_BASE_URL" in response.text
    assert "LLM_MODEL" in response.text
    assert "LLM_API_KEY" in response.text
    assert "AI suggestions — not operational decisions" not in response.text

    records = app.state.hardware.all()
    source_ten = next(record for record in records if record["source_id"] == 10)
    assert f'href="/hardware/{source_ten["id"]}"' in response.text
    assert response.text.index("Unknown Device") < response.text.index(
        "Duplicate ID Test Laptop"
    )

    create_response = client.post(
        "/admin/users",
        data={"email": "ordinary@booksy.test", "password": "ordinary-password"},
        follow_redirects=False,
    )
    assert create_response.status_code == 303
    client.post("/logout", follow_redirects=False)
    login_response = client.post(
        "/login",
        data={"email": "ordinary@booksy.test", "password": "ordinary-password"},
        follow_redirects=False,
    )
    assert login_response.status_code == 303

    assert client.get("/admin/audit").status_code == 403
    assert client.post("/admin/audit/llm").status_code == 403
    assert calls == 0


def test_audit_falls_back_without_mutating_inventory(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    _login_admin(client, settings)
    before = copy.deepcopy(app.state.hardware.all())
    calls = 0

    def should_not_run(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _provider_response('{"findings":[]}')

    app.state.llm_transport = httpx.MockTransport(should_not_run)
    missing = client.post("/admin/audit/llm")

    assert missing.status_code == 200
    assert calls == 0
    assert "DeepSeek audit is unavailable until" in missing.text
    assert "Deterministic findings" in missing.text
    assert app.state.hardware.all() == before

    _configure_llm(app)

    def provider_failure(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("credential-bearing provider failure", request=request)

    app.state.llm_transport = httpx.MockTransport(provider_failure)
    failed = client.post("/admin/audit/llm")

    assert failed.status_code == 200
    assert calls == 1
    assert "DeepSeek audit was unavailable or invalid." in failed.text
    assert "Deterministic findings remain complete." in failed.text
    assert "credential-bearing provider failure" not in failed.text
    assert "INVALID_STATUS" in failed.text
    assert app.state.hardware.all() == before


def test_valid_deepseek_response_uses_allowlist_and_renders_suggestions(
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    _login_admin(client, settings)
    _configure_llm(app)
    records = app.state.hardware.all()
    target = next(record for record in records if record["source_id"] == 9)
    before = copy.deepcopy(records)
    captured: list[httpx.Request] = []

    def valid_provider(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return _provider_response(
            json.dumps(
                {
                    "findings": [
                        {
                            "hardware_id": target["id"],
                            "severity": "warning",
                            "explanation": "The imported brand may contain a spelling error.",
                            "recommendation": (
                                "Verify the manufacturer against purchase records."
                            ),
                        }
                    ]
                }
            )
        )

    app.state.llm_transport = httpx.MockTransport(valid_provider)
    response = client.post("/admin/audit/llm")

    assert response.status_code == 200
    assert len(captured) == 1
    assert "AI suggestions — not operational decisions" in response.text
    assert "The imported brand may contain a spelling error." in response.text
    assert f'href="/hardware/{target["id"]}"' in response.text
    assert "DeepSeek audit was unavailable or invalid." not in response.text
    assert app.state.hardware.all() == before

    request = captured[0]
    assert str(request.url) == "https://api.deepseek.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-deepseek-key"
    assert request.headers["content-type"].startswith("application/json")
    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["stream"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 4096
    assert "JSON" in payload["messages"][0]["content"]

    user_payload = json.loads(payload["messages"][1]["content"])
    snapshot = user_payload["hardware_snapshot"]
    assert len(snapshot) == 11
    expected_keys = {
        "hardware_id",
        "name",
        "brand",
        "purchase_date",
        "status",
        "notes",
        "legacy_history",
        "legacy_assignee_present",
        "deterministic_findings",
    }
    assert all(set(item) == expected_keys for item in snapshot)
    assert {item["hardware_id"] for item in snapshot} == {
        record["id"] for record in records
    }

    unknown_device = next(item for item in snapshot if item["name"] == "Unknown Device")
    assert unknown_device["status"] is None
    sony = next(item for item in snapshot if item["name"] == "Sony WH-1000XM4")
    assert sony["legacy_assignee_present"] is True
    assert all(
        set(finding) == {"code", "severity"}
        for item in snapshot
        for finding in item["deterministic_findings"]
    )

    serialized_snapshot = json.dumps(snapshot)
    for forbidden in (
        "raw_payload",
        "source_id",
        "holder_user_id",
        "rental_history",
        "created_at",
        "updated_at",
        "j.doe@booksy.com",
        settings.bootstrap_admin_email,
        settings.bootstrap_admin_password,
        settings.session_secret,
        "test-deepseek-key",
    ):
        assert forbidden not in serialized_snapshot


@pytest.mark.parametrize("failure_mode", ["malformed-json", "schema", "unknown-hardware"])
def test_invalid_deepseek_output_is_rejected_atomically(
    failure_mode: str,
    client: TestClient,
    app: FastAPI,
    settings: Settings,
) -> None:
    _login_admin(client, settings)
    _configure_llm(app)
    known_id = app.state.hardware.all()[0]["id"]
    before = copy.deepcopy(app.state.hardware.all())
    valid_explanation = "This valid-looking row must not render after atomic rejection."

    if failure_mode == "malformed-json":
        content = "not json"
    elif failure_mode == "schema":
        content = json.dumps(
            {
                "findings": [
                    {
                        "hardware_id": known_id,
                        "severity": "warning",
                        "explanation": valid_explanation,
                        "recommendation": "Review it.",
                        "unexpected": "field",
                    }
                ]
            }
        )
    else:
        content = json.dumps(
            {
                "findings": [
                    {
                        "hardware_id": known_id,
                        "severity": "warning",
                        "explanation": valid_explanation,
                        "recommendation": "Review it.",
                    },
                    {
                        "hardware_id": str(uuid4()),
                        "severity": "critical",
                        "explanation": "Unknown record.",
                        "recommendation": "Ignore it.",
                    },
                ]
            }
        )

    app.state.llm_transport = httpx.MockTransport(
        lambda _request: _provider_response(content)
    )
    response = client.post("/admin/audit/llm")

    assert response.status_code == 200
    assert "DeepSeek audit was unavailable or invalid." in response.text
    assert "AI suggestions — not operational decisions" not in response.text
    assert valid_explanation not in response.text
    assert "INVALID_STATUS" in response.text
    assert app.state.hardware.all() == before
