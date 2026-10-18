import copy

import pytest
import requests

from jevloop import client
from jevloop.battery import build_questions, run_battery


class Response:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self.data = data
        self.text = text

    def json(self):
        return self.data


@pytest.fixture
def answers(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    return client.MockDecisionClient(seed=1).ask({}, build_questions(), 5)[0]


def test_openrouter_wire_contract(monkeypatch, answers):
    def post(self, url, **kwargs):
        assert url == "https://openrouter.ai/api/alpha/decisions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["json"] == {
            "model": "typesafe/jev-1.14", "state": {"mid": 100},
            "questions": build_questions(),
        }
        assert kwargs["allow_redirects"] is False
        return Response(data={"answers": answers, "model": "typesafe/jev-1.14-test", "usage": {}})
    monkeypatch.setattr(client.requests.Session, "post", post)
    result, meta = run_battery(client.OpenRouterDecisionClient("test-key"), {"mid": 100}, 5)
    assert result == answers
    assert meta["route"] == "OpenRouter"
    assert meta["model"] == "typesafe/jev-1.14-test"


@pytest.mark.parametrize("status", [401, 402, 403, 404, 429, 500, 302])
def test_api_failure_never_echoes_response(monkeypatch, status):
    monkeypatch.setattr(client.requests.Session, "post", lambda *a, **k: Response(status, text="secret-key"))
    with pytest.raises(client.DecisionClientError) as error:
        client.OpenRouterDecisionClient("secret-key").ask({}, {}, 5)
    assert "secret-key" not in str(error.value)
    if status == 429:
        assert isinstance(error.value, client.RateLimited)


def test_timeout_is_handled(monkeypatch):
    def fail(*a, **k):
        raise requests.Timeout("secret-key")
    monkeypatch.setattr(client.requests.Session, "post", fail)
    with pytest.raises(client.DecisionClientError, match="deadline"):
        client.OpenRouterDecisionClient("test-key").ask({}, {}, 5)


@pytest.mark.parametrize("bad", [None, {}, {"answers": []}, {"error": "denied"}])
def test_bad_envelope_rejected(monkeypatch, bad):
    monkeypatch.setattr(client.requests.Session, "post", lambda *a, **k: Response(data=bad))
    with pytest.raises(client.DecisionClientError):
        run_battery(client.OpenRouterDecisionClient("test-key"), {}, 5)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2, "0.8", True])
def test_bad_probability_rejected(monkeypatch, answers, value):
    changed = copy.deepcopy(answers)
    changed["toxic_flow"]["noul"] = value
    monkeypatch.setattr(client.requests.Session, "post", lambda *a, **k: Response(data={"answers": changed}))
    with pytest.raises(client.DecisionClientError, match="invalid battery"):
        run_battery(client.OpenRouterDecisionClient("test-key"), {}, 5)


def test_legacy_credentials_are_ignored(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("TYPESAFE_API_KEY", "unused")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "unused")
    assert isinstance(client.resolve_decision_client(), client.MockDecisionClient)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert isinstance(client.resolve_decision_client(), client.OpenRouterDecisionClient)
    assert isinstance(client.resolve_decision_client(mock=True), client.MockDecisionClient)
