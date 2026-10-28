"""A stand-in for GitHub's release API, for container/systemd-test.sh.

It serves, over HTTPS on localhost:8443 with a certificate from the test CA,
the releases in the /releases directories named in /tmp/listed (one name per
line) as GitHub lists them, and their files. Only the test CA vouches for its
certificate, as only an inspecting proxy's CA would for the certificates the
proxy makes up.
"""

import http.server
import json
import ssl
from pathlib import Path

ROOT = Path("/releases")
LISTED = Path("/tmp/listed")
ORIGIN = "https://localhost:8443"


def releases() -> list[dict]:
    """The listed releases, as GitHub's API describes them."""
    found = []
    for name in LISTED.read_text().split():
        files = sorted(p.name for p in (ROOT / name).iterdir())
        package = next(f for f in files if f.endswith("_amd64.deb"))
        version = package.split("_")[1].replace("~", "-")
        assets = [
            {"name": f, "browser_download_url": f"{ORIGIN}/files/{name}/{f}"}
            for f in files
        ]
        found.append(
            {"tag_name": f"v{version}", "body": f"Test {version}", "assets": assets}
        )
    return found


class GitHub(http.server.BaseHTTPRequestHandler):
    """The release list, and each release's files."""

    def do_GET(self) -> None:
        if self.path.startswith("/repos/") and "/releases?" in self.path:
            body = json.dumps(releases()).encode()
        elif self.path.startswith("/files/") and ".." not in self.path:
            body = (ROOT / self.path.removeprefix("/files/")).read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(ROOT / "pki/server.pem", ROOT / "pki/server.key")
server = http.server.ThreadingHTTPServer(("127.0.0.1", 8443), GitHub)
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
