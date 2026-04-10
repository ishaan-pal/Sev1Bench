from models import ActionType, IncidentAction, ServiceName
from simulator import IncidentResponseSimulator


def test_easy_task_recovers_after_scaling_api():
    sim = IncidentResponseSimulator()
    sim.reset(task_id="easy_cpu_overload")
    sim.step(IncidentAction(action_type=ActionType.CHECK_METRICS))
    observation, reward, done, info = sim.step(
        IncidentAction(action_type=ActionType.SCALE_SERVICE, service=ServiceName.API)
    )

    assert reward.total > 0
    assert done is True
    assert info["resolved"] is True
    assert observation.metadata["health_score"] >= 80.0
    assert observation.recent_changes
    assert "queue" in observation.alerts[0].message


def test_medium_task_is_reproducible():
    sim_a = IncidentResponseSimulator()
    sim_b = IncidentResponseSimulator()

    obs_a = sim_a.reset(task_id="medium_hidden_db_leak", seed=999)
    obs_b = sim_b.reset(task_id="medium_hidden_db_leak", seed=999)

    assert obs_a.model_dump() == obs_b.model_dump()
