"""Unit tests for Coroot id parsing / AppMap mapping (no network)."""

from rca_agent.topology.coroot_client import CorootClient, _parse_app_id, _node_from_id


def test_parse_app_id_formats():
    assert _parse_app_id("npd-movie:Deployment:movie-api") == (
        "npd-movie",
        "Deployment",
        "movie-api",
    )
    assert _parse_app_id("abc123:npd-movie:Deployment:movie-api")[2] == "movie-api"
    assert _parse_app_id("npd-movie/movie-api")[2] == "movie-api"


def test_service_map_direction_mapping():
    """Coroot upstreams=deps → our downstream; downstreams=callers → our upstream."""
    client = CorootClient()
    client.project_id = "demo"
    apps = [
        {
            "id": "npd-movie:Deployment:movie-api",
            "upstreams": [{"id": "redis:StatefulSet:redis-ha"}],
            "downstreams": [{"id": "npd-movie:Deployment:movie-web"}],
        },
        {
            "id": "redis:StatefulSet:redis-ha",
            "upstreams": [],
            "downstreams": [{"id": "npd-movie:Deployment:movie-api"}],
        },
        {
            "id": "npd-movie:Deployment:movie-web",
            "upstreams": [{"id": "npd-movie:Deployment:movie-api"}],
            "downstreams": [],
        },
    ]
    topo = client._topology_from_service_map(apps, "npd-movie", "movie-api", hops=1)
    assert topo is not None
    assert topo["source"] == "coroot"
    up_names = {n["name"] for n in topo["upstream"]}
    down_names = {n["name"] for n in topo["downstream"]}
    assert "movie-web" in up_names
    assert "redis-ha" in down_names


def test_app_map_clients_dependencies():
    client = CorootClient()
    client.project_id = "demo"
    payload = {
        "data": {
            "app_map": {
                "application": {"id": "npd-banking:Deployment:transfer-service"},
                "clients": [{"id": "npd-banking:Deployment:api-producer"}],
                "dependencies": [{"id": "npd-banking:Deployment:account-service"}],
            }
        }
    }
    topo = client._topology_from_app_map(payload, "npd-banking", "transfer-service")
    assert topo is not None
    assert {n["name"] for n in topo["upstream"]} == {"api-producer"}
    assert {n["name"] for n in topo["downstream"]} == {"account-service"}


def test_node_from_id():
    n = _node_from_id("npd-movie:Deployment:movie-api", hops=2)
    assert n["namespace"] == "npd-movie"
    assert n["name"] == "movie-api"
    assert n["hops"] == 2
