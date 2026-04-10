from models import ActionType, IncidentAction
from server.incident_response_environment import IncidentResponseEnvironment


def test_reset_triggers_proxy_probe(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        "server.incident_response_environment.ensure_proxy_probe",
        lambda: calls.append("probe") or True,
    )

    env = IncidentResponseEnvironment()
    observation = env.reset(task_id="easy_cpu_overload")

    assert calls == ["probe"]
    assert observation.task_id == "easy_cpu_overload"


def test_step_triggers_proxy_probe(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(
        "server.incident_response_environment.ensure_proxy_probe",
        lambda: calls.append("probe") or True,
    )

    env = IncidentResponseEnvironment()
    env.reset(task_id="easy_cpu_overload")
    env.step(IncidentAction(action_type=ActionType.CHECK_METRICS))

    assert calls == ["probe", "probe"]
