"""Phase 7 topology graph smoke tests."""

from rca_agent.topology.graph import get_topology, related_workloads, topology_evidence_lines


def test_transfer_service_neighbors():
    topo = get_topology("npd-banking", "transfer-service", hops=2)
    assert topo["center"]["name"] == "transfer-service"
    names_up = {n["name"] for n in topo["upstream"]}
    names_down = {n["name"] for n in topo["downstream"]}
    assert "api-producer" in names_up or "api-producer" in names_down
    assert "account-service" in names_up or "account-service" in names_down
    assert related_workloads(
        "npd-banking", "transfer-service", "npd-banking", "account-service"
    )
    assert not related_workloads(
        "npd-banking", "transfer-service", "npd-movie", "movie-api"
    )
    lines = topology_evidence_lines(topo)
    assert any(line.startswith("Topo ") for line in lines)


def test_movie_api_neighbors():
    topo = get_topology("npd-movie", "movie-api", hops=2)
    names = {n["name"] for n in topo["upstream"] + topo["downstream"]}
    assert "media-worker" in names or "movie-web" in names
