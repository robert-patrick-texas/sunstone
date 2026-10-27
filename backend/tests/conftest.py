import pytest


@pytest.fixture
def topology_data() -> dict:
    """A minimal valid topology: one site, two devices, one link."""
    return {
        "sites": [{"code": "DAL", "name": "Dallas", "lat": 32.8, "lon": -96.8}],
        "devices": [
            {"name": "r1", "site": "DAL", "role": "core"},
            {"name": "r2", "site": "DAL", "role": "access"},
        ],
        "links": [
            {
                "a": {"device": "r1", "interface": "Te1/0/1"},
                "b": {"device": "r2", "interface": "Te1/0/49"},
                "speed_mbps": 10000,
            }
        ],
    }
