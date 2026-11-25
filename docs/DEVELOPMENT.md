# Development

## Layout

| Path | What |
|---|---|
| `backend/` | Python, FastAPI, managed with uv. Model and validation (`model.py`), YAML loader, API, CLI, mock generators (`mockgen.py`, and `mocklayers.py` for the layered sample). |
| `frontend/` | SvelteKit single-page app (Svelte 5, TypeScript), built static and served by the backend. MapLibre GL for the map; Cytoscape.js with fcose for the graph views. `src/lib/graph/` is shared by the graph views, `hierarchy/`, `topo/`, and `logical/` are the three views; `layers.ts` works out each named network's slice. |
| `data/sample/` | Mock topologies. |
| `packaging/` | The Debian package: its spec (`nfpm.yaml`), the clean-container build, the service unit, account, directories, maintainer scripts, settings template, release keys, and the package tests. |
| `tools/release/` | The release tool, copied from vakr, with Sunstone's `release.toml`. |
| `tools/dev-instance/` | The dev instance's image, compose file, and nginx snippet. |
| `tools/md2html/` | The Markdown-to-HTML converter for the documentation site, copied from segl. |
| `scripts/build_docs.py` | Builds the documentation site with `tools/md2html`. |
| `docs/` | The documentation, published as the site. |
| `VERSION`, `CHANGELOG.md` | The one version everything takes, and each release's notes. |

## Testing

`make test` runs backend tests (pytest), ruff, ty, svelte-check, prettier, frontend unit tests (Vitest), and the release tool's tests. CI runs it for every push to `main`. `make e2e` builds the UI and runs Playwright tests against the real backend. `make package-test` builds three test releases signed with a throwaway key, one that fails to start, and two that must be refused, then installs, runs, updates, rolls back, and removes them in a container booted with systemd; and runs the daily timer's update against a stand-in for GitHub whose certificate only a test CA in `/etc/sunstone/ca.d` vouches for, as behind an inspecting proxy: the broken release rolls back and is not tried again, the hold keeps the next back, and lifting it installs it.

Where Chromium's system libraries are missing, run the browser in the Playwright container and point the tests at it:

```console
$ docker run --rm --network host --init mcr.microsoft.com/playwright:v1.64.1-noble \
    /bin/sh -c "cd /tmp && npx -y playwright@1.64.1 run-server --port 3124 --host 127.0.0.1" &
$ PW_WS_ENDPOINT=ws://127.0.0.1:3124/ make e2e
```

## Documentation site

`make docs` (`python3 scripts/build_docs.py`) renders every Markdown file in the repository to HTML in `_site/` with `tools/md2html`, copied from segl. Each page has an index of every page down the left, with the project name above it linking to the GitHub repository, and a GitHub link in its top bar. `README.md` becomes the home page and `.md` links become `.html` links. It fails, naming each one, on a broken link, anchor, or image, so `make test` runs it too.

`.github/workflows/pages.yml` builds the site the same way on every push to `main` and publishes it to GitHub Pages, at <https://robert-patrick-texas.github.io/sunstone/>. A broken link stops the deployment, and the last good site stays up. md2html's only dependencies are in its script's inline metadata, which `uv run` reads.

## Measuring speed

Open the app with `?perf` (for example http://127.0.0.1:8000/?perf) to show, in a corner: frames per second, the worst frame in the last second, the longest stretch the page was blocked, and timings of the heavy work (layouts, drawing, live updates, map updates). `make bench` runs the same measurements over scripted scenarios on the large sample (zooming the map, live updates, expanding every site in the hierarchy and topology views) and prints a table. It takes `PW_WS_ENDPOINT` like `make e2e`, and `BENCH_HEADED=1` to watch it in a browser window.

The Playwright container draws without a GPU, so its frame rates say little about real screens: run `make bench`, or open `?perf`, on the machines people will use. Measured in the container on the large sample, before and after this round of work:

| | Before | After |
|---|---|---|
| Page blocked laying out the topology view, every site expanded | 5.1 s | 1.5 s (layout runs in a worker) |
| Page blocked expanding every site in the hierarchy | 1.8 s | 0.9 s |
| Live update, fetch to screen | 0.8–1.5 s | 30–50 ms |
| Problems for each update | 40–190 ms in every browser | 20–50 ms to fetch, worked out once on the server |
| First load of the day's events | 5.8 s | 0.2 s |
| Server time per viewer per update | about 0.35 s | none beyond sending a cached copy |
