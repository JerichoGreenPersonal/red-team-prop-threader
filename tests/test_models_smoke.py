from review_prep.models import ClPolicy, DEFAULT_CL_POLICIES, RouteState


def test_wip_default_is_sync_and_open():
    assert DEFAULT_CL_POLICIES["WIP"] == ClPolicy.SYNC_AND_OPEN


def test_route_state_values_are_stable():
    assert RouteState.READY_TO_LAUNCH.value == "ready_to_launch"
