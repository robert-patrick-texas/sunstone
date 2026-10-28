import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from fastapi.testclient import TestClient

from sunstone.api import create_app

SAMPLE = Path(__file__).parents[2] / "data" / "sample"


def sunstone(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sunstone", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_check_loads_what_the_settings_file_names(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        f'topology = "{SAMPLE / "small.yaml"}"\n'
        f'oncall = "{SAMPLE / "small.oncall.yaml"}"\n'
        f'state_dir = "{tmp_path / "state"}"\n'
        "port = 8080\n"
        '[update]\nrepository = "someone/fork"\n',
        encoding="utf-8",
    )
    done = sunstone("check", "--config", str(config))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        f"sunstone check: {SAMPLE / 'small.yaml'}: 5 sites, 52 devices, 106 links",
        f"sunstone check: {SAMPLE / 'small.oncall.yaml'}: 4 teams",
        f"sunstone check: saved files in {tmp_path / 'state'} are readable",
        "sunstone check: ok",
    ]


def test_check_names_what_is_wrong(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('topolgy = "/etc/sunstone/topology.yaml"\n', encoding="utf-8")
    done = sunstone("check", "--config", str(config))
    assert done.returncode == 2
    assert str(config) in done.stderr and "topolgy" in done.stderr

    broken = tmp_path / "topology.yaml"
    broken.write_text("sites: [}\n", encoding="utf-8")
    done = sunstone("check", "--topology", str(broken))
    assert done.returncode == 1
    assert str(broken) in done.stderr


def test_the_server_says_which_version_it_is(tmp_path: Path) -> None:
    topology = tmp_path / "small.yaml"
    topology.write_text((SAMPLE / "small.yaml").read_text())
    client = TestClient(create_app(topology, warm=False))
    assert client.get("/api/version").json() == {"version": version("sunstone")}
    assert sunstone("--version").stdout.strip() == f"sunstone {version('sunstone')}"
