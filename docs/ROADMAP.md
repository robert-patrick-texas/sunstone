# Roadmap

What is next comes first, then what is not done yet, then what is done. A checked box is done. Sunstone is still a prototype for a workshop: it runs on sample data with visible results, and it connects to no other system yet (see [Decisions so far](DECISIONS.md)).

The latest release is [v0.12.0](https://github.com/robert-patrick-texas/sunstone/releases/tag/v0.12.0).

## Next

### Documentation and organization

Done on a branch of its own, not a milestone. Not released on its own (see "Next release" below).

- [x] This roadmap: what is next, what is not done yet, and what is done, each with a checkbox.
- [x] README Next moved here.
- [x] No real-world host names in the README: the dev instance's nginx example uses `dev.example.com`.
- [x] Installing behind nginx, for a production host: at `/sunstone/` by default, at the root of a site, or under another name (docs/INSTALL.md, "Behind nginx").
- [x] README revised to the introduction, running and using Sunstone, and links into `docs/`.
- [x] The rest of the README moved into `docs/`: installing, the data model, decisions, development (layout, testing, measuring speed), and releasing.
- [x] A Markdown-to-HTML converter, `tools/md2html`, copied from segl: an index down the left of each page, the project name in the upper left, and a link to the GitHub repository.
- [x] `make docs` builds the site and fails on a broken link, anchor, or image.
- [x] The site published to GitHub Pages from `main`.
- [x] `make release-tables` counts `docs/` as documentation (it counts every Markdown file already).
- [x] The package build installs `docs/` beside the README and CHANGELOG, in `/opt/sunstone/share/doc/docs/`; the next release is the first to ship it.

### Milestone 34 (0.13.0)

- [ ] `git switch -c milestone-34`, VERSION 0.13.0, and `uv sync --reinstall-package sunstone`.
- [ ] CHANGELOG 0.13.0 in the release notes format: a summary; New, Changed, Fixed, and Additional Notes (each only when it has entries); Lines of Code; Versions (`make release-tables`). Changed includes the documentation work above.
- [ ] Every component and dependency at its latest production release (`make outdated`), not betas and not held to LTS. One is held back only when tests fail with no simple fix, and that goes under Additional Notes, to be tried again at its next version.
  - [ ] Node.js 24 → 26: `.node-version`, the `engines` range (`<25`), the `node:` builder image and its digest in `packaging/Dockerfile`, and @types/node 26.
  - [ ] Python, as of 2026-11-14: fastapi 0.163.0, pytest 9.2.0, ruff 0.17.5, ty 0.0.104.
  - [ ] npm, as of 2026-11-14: Playwright 1.65.1, SvelteKit 3.2.0, Svelte 5.57.3, Vite 8.3.8, Vitest 5.1.0, MapLibre 6.18.0, Cytoscape 3.35.0, prettier 3.10.1, TypeScript 7.0.2 (a major version).
  - [ ] The builder's uv, nfpm, and Ubuntu base image, checked by hand.
- [ ] Scope agreed: four options from "Not done yet", the recommended one first.

### Next release

- [ ] Held until the source code changes, not only the documentation. It is the first to ship `docs/` in the package.

## Not done yet

### Installing

- [ ] The nginx files in the package, and a setup command that writes them with the site's prefix, as hirdir's `hirdir-setup --prefix` does, once the projects share one way of doing it. The steps are written out in docs/INSTALL.md so far.

### Rules and overrides

- [ ] Rules renaming by template ("BRV- as bravo-", "also `{name}.corp`"), and matching by label. Rules match on tags, platforms, roles, and names so far.
- [ ] What started or stopped matching each rule in a shift, in the handover. It lists rules made, withdrawn, and expired so far.

### Paging and on-call

- [ ] Priorities in paging: a high-priority problem paging with high urgency, and one the party downstream answers for going to them first. Urgency is by problem kind today.
- [ ] Paging for real: PagerDuty or Opsgenie for pages and schedules, so the directory and the paging service cannot disagree.

### Resources and shared risk

- [ ] Resources chosen like a network, filtering the views to their members, and shared risk for each: what one device, link, or provider would take a resource down with.

### Layer 2, tunnels, and routing

- [ ] Port channels into a transport or to someone else's device, such as two circuits bundled to a provider's PE. Channels are between two of our devices so far.
- [ ] MACsec with one connectivity association for several far ends on an E-LAN port, and to someone else's device in the samples (a cloud's direct circuit).
- [ ] Fixes for tunnels: moving a tunnel's documented end to the tunnel interface CDP shows.
- [ ] Roles checked against routing: once there is a source for BGP sessions and the prefixes exchanged, whether a circuit for peering exchanges routes only with its community, and one for egress takes none in.

### Sources of truth and discovery

- [ ] Source-of-truth round trip: an import shaped like NetBox or Nautobot through an adapter, and the change set back out. Recommended for many milestones and not picked yet.
- [ ] Sources: NetBox or Nautobot import, then NMS import and LLDP/CDP discovery.
- [ ] The change set to the source of truth: sent to NetBox or Nautobot once there is one, each change dropped once the source has it.
- [ ] Discovery for real: a collector reading LLDP-MIB and CDP-MIB, or an NMS's neighbor tables, as a `DiscoverySource`.

### Live state and monitoring

- [ ] Live state from real sources: vakr first, then other monitoring tools, each as a `StateSource`. vakr needs the read-only integration role its design calls for, and its round-trip times are per device, not per link. Each source needs history, from the tool or recorded by Sunstone.

### Handover, wall display, and incidents

- [ ] The handover posted to chat or email at each shift change. The message is written; sending it to a Slack or Teams channel or a mailing list is what is left.
- [ ] The wall display showing when no one has signed for the handover of the shift on now, as the header does, and which incidents are open.
- [ ] Incidents to and from a ticketing system (ServiceNow, Jira), once there is one. The postmortem is written; filing it is what is left.

### Capacity and speed

- [ ] Capacity trends: 30 days of load, and when each link crosses 80% and 95%.
- [ ] Frame rates on real GPUs: `make bench` on the hardware the NOC uses. The map and the fully expanded graphs are the ones to watch; the container's software rendering gives 6 to 12 fps zooming the map.

## Done

Newest first. Versions 0.3.0 to 0.5.0 were never released on their own: v0.6.0's release notes cover them.

### Since v0.12.0 (not released)

- [x] Release notes at full width, with Lines of Code and Versions tables (`make release-tables`), `make outdated`, and the README "Releasing" checklist.

### v0.12.0 (2026-11-10)

- [x] Milestone 33: rules, one override for everything that matches.

### v0.11.0 (2026-11-09)

- [x] Milestone 32: overrides, Sunstone's own exceptions to what the topology says.

### v0.10.0 (2026-11-08)

- [x] Milestone 31: priorities on cables and circuits, and resources with a status of their own.

### v0.9.0 (2026-11-08)

- [x] Milestone 30: carrier Ethernet, MACsec, port channels, and CDP over tunnels.
- [x] Milestone 29: what each connection is for, the IDs it goes by, and discovery across circuits.

### v0.8.0 (2026-11-08)

- [x] Milestone 28: problems and events by network and region, a site's networks, and spoke tunnels in the Logical view.

### v0.7.0 (2026-11-08)

- [x] Milestone 27: problems across the networks, and shared risk as things stand.

### v0.6.0 (2026-11-07)

- [x] Milestone 26: "what if" on request, faster, and release notes that catch up.
- [x] Milestone 25 (0.5.0): impact across the layers.
- [x] Milestone 24 (0.4.0): network status.
- [x] Milestone 23 (0.3.0): WAN transports and overlays.

### v0.2.0 (2026-10-28)

- [x] Milestone 22: incident timeline.
- [x] Milestone 21: updates on a timer.

### v0.1.0 (2026-10-28)

- [x] Milestone 20: handover sign-off.
- [x] Milestone 19: `.deb` package and self-update.
- [x] Milestone 18: handover at shift change.
- [x] Milestone 17: shift handover report.
- [x] Milestone 16: expected findings.
- [x] Milestone 15: fixing the documentation from discovery.
- [x] Milestone 14: discovery history and replay.
- [x] Milestone 13: undocumented links on the map.
- [x] Milestone 12: discovered vs documented.
- [x] Milestone 11: alert routing and on-call.
- [x] Milestone 10: search and navigation.
- [x] Milestone 9: shareable links and wall display.
- [x] Milestone 8: maintenance and acknowledgement.
- [x] Milestone 7: scale and speed.
- [x] Milestone 6: history and replay.
- [x] Milestone 5: problems and impact.
- [x] Milestone 4: live state from a simulated source.
- [x] Milestone 3: paths between devices and saved layouts.
- [x] Milestone 2: topology view with automatic and neighborhood layouts.
- [x] Milestone 1: geographic and hierarchy views on mock topology data.
