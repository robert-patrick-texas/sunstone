# Sunstone

**Sunstone** — Network mapping and visualization tool

Sunstone shows network operations staff a map of the network they can pan, zoom, and switch between views of: a geographic map with sites and links, a top-down hierarchy, automatic topology layouts of the whole network or of the neighborhood around a device, and a logical view of the named networks layered over the links, without geography.

> **Status:** workshop prototype. It runs on a generated mock topology and simulated live state, and has no integrations yet.

## Running it

Requires [uv](https://docs.astral.sh/uv/) and Node.js 24.

```console
$ make setup
$ make serve                                    # http://127.0.0.1:8000, small sample
$ make serve TOPOLOGY=data/sample/large.yaml    # about 3,000 devices
```

For development, run `make dev-api` and `make dev-web` in two terminals and open http://127.0.0.1:5173. `make help` lists the other tasks.

**Dev instance.** `make dev-up` runs the working tree in a container (`tools/dev-instance/`), on 127.0.0.1:8000, for checking work in progress without a release:
- The API restarts when its code or the topology file changes.
- The web UI is rebuilt once its source has been still for 3 seconds, so a change shows on reload about 13 seconds after the last save (measured). A build that fails leaves the last good one, and `make dev-logs` shows why.
- It shows the layered sample; `SUNSTONE_DEV_TOPOLOGY=data/sample/large.yaml make dev-up` shows another.
- It mounts the tree read-only and keeps its saved state in a Docker volume. `make dev-down` stops it and keeps the state; `docker compose -f tools/dev-instance/compose.yaml down -v` deletes the state too. It restarts with Docker, so it comes back after a reboot.
- It holds port 8000, so stop it before `make serve` or `make dev-api`.
- `tools/dev-instance/nginx.conf` serves it at `/sunstone/` on an existing nginx site, behind a password in `/etc/nginx/sunstone-dev.htpasswd` (written with `openssl passwd -6`), for example at `https://dev.example.com/sunstone/`.

Sunstone has no sign-in: anyone who can reach it can save and delete layouts, plan and delete maintenance, acknowledge and page problems, cover shifts, and fix the documentation, under whatever name they type. It listens on 127.0.0.1 by default; give `sunstone serve` `--host`, or set `host` in its settings file, only on a network you trust.

`sunstone serve` takes the topology and where saved files go on the command line (`--topology`, `--oncall`, `--state-dir`, and one option per kind of saved file), or from a settings file with `--config`; the command line wins. `sunstone check` loads everything as the server would and says what it found or what is wrong, and `sunstone --version` says which release this is.

## Documentation

The documentation is in `docs/`, and is published as a site at <https://robert-patrick-texas.github.io/sunstone/>.

- [Installing Sunstone](docs/INSTALL.md): the `.deb` package and checking a release's signature, the files it installs, running it behind nginx at `/sunstone/`, at the root of a site, or under another name, updating, the daily timer, holding a version, and self-update through a proxy.
- [Using Sunstone](docs/USING.md): the views, networks and their status, resources, paths, live state, problems, maintenance, history, "what if", shared risk and impact, search, on-call and paging, discovery and fixing the documentation, overrides, rules, the shift handover, incidents, and the wall display.
- [Data model](docs/DATA-MODEL.md): the topology file and the samples, priorities, resources, live state, problems, maintenance, on-call, discovery, fixes, overrides, rules, the handover, incidents, and saved state, with the API that serves each.
- [Decisions so far](docs/DECISIONS.md): why Sunstone works the way it does.
- [Development](docs/DEVELOPMENT.md): the repository's layout, testing, and measuring speed.
- [Releasing](docs/RELEASING.md): the release checklist.
- [Roadmap](docs/ROADMAP.md): what is next, what is not done yet, and what is done.
- [Changelog](CHANGELOG.md): what changed in each version.

`make docs` builds the site into `_site/` with `tools/md2html` (copied from segl) and fails on a broken link or anchor. GitHub Pages publishes it from `main`.

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
