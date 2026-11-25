# Installing Sunstone

Sunstone ships as one `.deb` for Ubuntu 26.04 LTS on amd64, built the way vakr's is. It is self-contained: it brings its own Python 3.15 and a locked virtual environment under `/opt/sunstone`, so the host's Python and its upgrades do not affect it. Each release at <https://github.com/robert-patrick-texas/sunstone/releases> has the package, `SHA256SUMS`, and its signature, `SHA256SUMS.sig`.

```sh
repo=robert-patrick-texas/sunstone
version=0.1.0                                             # the release to install
debver=$(printf '%s\n' "$version" | sed 's/-rc\./~rc./')    # the package's form: 0.2.0~rc.1
base=https://github.com/$repo/releases/download/v$version
curl -fL -O "$base/sunstone_${debver}_amd64.deb" -O "$base/SHA256SUMS" -O "$base/SHA256SUMS.sig"
curl -fLO "https://raw.githubusercontent.com/$repo/v$version/packaging/release-signers"
grep -v '^#' release-signers | awk 'NF {print $3, $4}' | ssh-keygen -lf -
ssh-keygen -Y verify -f release-signers -I sunstone-release -n sunstone-release \
    -s SHA256SUMS.sig < SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
sudo apt install ./sunstone_${debver}_amd64.deb
```

The first `ssh-keygen` must print the release key's fingerprint, `SHA256:8WUCE9gHrarTMP6hv8LpAeTHv04rWlzWYLNuxC3Q1Lk`; the second, `Good "sunstone-release" signature`; and `sha256sum`, `OK` for the package. If any of them does not, do not install. `apt` brings `ca-certificates`, `openssh-client` (whose `ssh-keygen` checks later releases), `systemd`, and `tzdata`.

| Path | What | Owned by |
|---|---|---|
| `/opt/sunstone/python/`, `/opt/sunstone/venv/` | The bundled CPython 3.15, and the locked environment holding Sunstone | package |
| `/opt/sunstone/share/web/` | The web UI the service serves at `/` | package |
| `/opt/sunstone/share/samples/` | The small, large, and layered sample networks and their on-call directories | package |
| `/opt/sunstone/share/release-signers` | The release keys self-update trusts | package |
| `/opt/sunstone/share/templates/`, `/opt/sunstone/share/doc/` | The settings template; the licence, notice, README, changelog, the documentation in `docs/`, and the web UI's bundled licences | package |
| `/usr/bin/sunstone` | A link to `/opt/sunstone/venv/bin/sunstone` | package |
| `/usr/lib/systemd/system/sunstone.service`, `/usr/lib/sysusers.d/sunstone.conf`, `/usr/lib/tmpfiles.d/sunstone.conf` | The service, its account, and its directories | package |
| `/usr/lib/systemd/system/sunstone-update.timer`, `sunstone-update.service` | The daily self-update, disabled until you enable it | package |
| `/etc/sunstone/config.toml`, `topology.yaml`, `oncall.yaml` | Your settings, network, and on-call directory, mode 0640, `root:sunstone`; created only when missing, never overwritten | you |
| `/etc/sunstone/ca.d/` | CA certificates self-update trusts besides the system's, for a proxy that inspects TLS | you |
| `/var/lib/sunstone/state/` | Maintenance, acknowledgements, pages, covers, notes, fixes, overrides, handovers, incidents, and layouts | the service |
| `/var/lib/sunstone/update/` | Self-update's cached packages, backups, record, and lock; only root may open it | root |

Nothing starts on installation. The package puts the small sample network and its on-call directory in `/etc/sunstone` when there is no topology there yet, so the service has something to show. To start it:

```sh
sudo sunstone check                       # loads everything as the service would
sudo systemctl enable --now sunstone      # http://127.0.0.1:8000 on this host
```

To show your own network, replace `topology.yaml` and `oncall.yaml`, run `sudo sunstone check`, and `sudo systemctl restart sunstone`. An on-call directory that names sites the topology lacks stops the service, and `sunstone check` says which. `/etc/sunstone/config.toml` holds the same choices as the command line: `topology`, `oncall`, `state_dir`, `host`, `port`, and under `[update]`, the `repository` releases come from, `hold_version`, `https_proxy`, `tls_strict_x509`, and `api` (see Updating). The service listens on 127.0.0.1:8000 for a reverse proxy in front, which may serve it at a site's root or under a path such as `/sunstone/`; `host = "0.0.0.0"` serves everyone who can reach the port, which, without sign-in, only suits a network you trust.

## Behind nginx

Sunstone serves plain HTTP on `127.0.0.1:8000` and has no sign-in. On a production host, nginx on the same host stands in front of it: nginx holds the certificate, asks who is there, and passes requests on to Sunstone over loopback.

The site chooses Sunstone's URL, and only nginx changes to move it:

| URL | Set up with |
|---|---|
| `https://site.example.com/sunstone/` (the default) | the snippet below as it is |
| `https://site.example.com/othername/` | the snippet below with its prefix changed (see "Another name") |
| `https://site.example.com/` | the root snippet (see "At the root of a site") |

Nothing in Sunstone's settings names its URL. The web UI asks for everything relative to its page, and the links it makes (a shared view, a page to whoever is on call, the handover, an incident) take their address from the browser. Sunstone uses no WebSockets or streams, so the proxy needs no upgrade headers or long timeouts.

The setup is three files: an upstream in `/etc/nginx/conf.d/`, the proxy settings in a snippet, and Sunstone's locations in another snippet that the site's `server { }` block includes. These steps use the default URL.

### 1. Keep Sunstone on loopback

`host = "127.0.0.1"` and `port = 8000` in `/etc/sunstone/config.toml` are the defaults: leave them. Sunstone trusts `X-Forwarded-For` and `X-Forwarded-Proto` from `127.0.0.1` only, so nginx has to be on the same host. Listening beyond loopback would let anyone who can reach the port use Sunstone without signing in.

### 2. The upstream

`/etc/nginx/conf.d/sunstone.conf`:

```nginx
# Sunstone's service on this host (docs/INSTALL.md, "Behind nginx").
upstream sunstone {
    server 127.0.0.1:8000;
    keepalive 8;
}
```

### 3. The proxy settings

`/etc/nginx/snippets/sunstone-proxy.conf`, the same at any URL:

```nginx
# Sunstone has no sign-in, so nginx asks for one. To use the site's single
# sign-on instead, replace these two lines with its auth_request settings.
auth_basic "Sunstone";
auth_basic_user_file /etc/nginx/sunstone.htpasswd;

# Under a prefix the trailing slash strips it; under "location /" it changes nothing.
proxy_pass http://sunstone/;
proxy_http_version 1.1;
proxy_set_header Connection "";
proxy_set_header Host $host;
proxy_set_header X-Forwarded-For $remote_addr;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_redirect off;
proxy_connect_timeout 5s;
proxy_read_timeout 60s;
```

`$remote_addr` replaces whatever `X-Forwarded-For` a client sent, so a client cannot choose the address Sunstone sees. There is no `add_header`: one in a location discards the server block's headers, HSTS among them.

### 4. Sunstone's locations

`/etc/nginx/snippets/sunstone.conf`. The prefix is on the three lines marked `# prefix`:

```nginx
# Sunstone at /sunstone/ on this site (docs/INSTALL.md, "Behind nginx").

# Without the trailing slash, the page's relative requests would leave the prefix.
# A relative redirect stays right behind load balancers and on odd ports.
location = /sunstone {                    # prefix
    absolute_redirect off;
    return 301 /sunstone/;                # prefix
}

# ^~ keeps the site's regular-expression locations, such as caching rules for
# .js and .css files, from claiming Sunstone's assets.
location ^~ /sunstone/ {                  # prefix
    include snippets/sunstone-proxy.conf;
}
```

Add one line inside the `server { }` block of the site that listens on 443 with its certificate:

```nginx
server {
    listen 443 ssl;
    server_name site.example.com;
    # ... the site's certificate and its own locations ...

    include snippets/sunstone.conf;
}
```

### 5. Accounts

Each person gets a line in `/etc/nginx/sunstone.htpasswd`. `openssl passwd -6` asks for the password twice and prints its SHA-512 hash:

```sh
printf 'alice:%s\n' "$(openssl passwd -6)" | sudo tee -a /etc/nginx/sunstone.htpasswd
sudo chown root:www-data /etc/nginx/sunstone.htpasswd
sudo chmod 0640 /etc/nginx/sunstone.htpasswd
```

Inside Sunstone, people still type the name that their acknowledgements, notes, and sign-offs are recorded under. Sunstone does not read the name nginx signed them in with.

### 6. Check it

```sh
sudo nginx -t && sudo systemctl reload nginx
curl -sI https://site.example.com/sunstone | grep -i -E '^(HTTP|location)'   # 301, location: /sunstone/
curl -s -u alice https://site.example.com/sunstone/api/version                 # the release serving
```

Then open `https://site.example.com/sunstone/` in a browser and sign in.

| What you see | Why |
|---|---|
| 502 Bad Gateway | Sunstone is not running: `systemctl status sunstone`, and `journalctl -u sunstone` for why. |
| 401 every time | The account is not in `sunstone.htpasswd`, or nginx cannot read the file (its group must be `www-data`). |
| A blank page, or 404s for files under `_app/` | Another location is claiming them: check that the location has `^~`. Or `proxy_pass` lost its trailing slash, so Sunstone is asked for `/sunstone/...`. |
| The page loads at `/sunstone` but shows no data | The redirect to `/sunstone/` is missing, so the page's requests go to the site's own `/api/`. |

### Another name

To put Sunstone at `https://site.example.com/othername/`, change the prefix on the three marked lines, and check them:

```sh
sudo sed -i '/# prefix$/s|/sunstone|/othername|' /etc/nginx/snippets/sunstone.conf
grep -n '# prefix' /etc/nginx/snippets/sunstone.conf
sudo nginx -t && sudo systemctl reload nginx
```

The upstream, the proxy settings, and the accounts stay as they are. Bookmarks and shared links made at the old URL stop working, since they hold the old prefix.

### At the root of a site

To put Sunstone at `https://site.example.com/`, write `/etc/nginx/snippets/sunstone.conf` as one location instead:

```nginx
# Sunstone at the root of this site (docs/INSTALL.md, "Behind nginx").
# ^~ keeps the site's regular-expression locations from claiming any path.
location ^~ / {
    include snippets/sunstone-proxy.conf;
}
```

A `server { }` block can hold only one location for `/`, so remove the site's own first, or give Sunstone a site of its own, such as `sunstone.example.com`. Sunstone then answers every path on the site, and the `^~` means the site's regular-expression locations no longer apply to any of them: without it, a rule such as one for `.js` files would claim Sunstone's assets. No redirect is needed. Check it as in step 6, without the prefix: `curl -s -u alice https://site.example.com/api/version`.

## Updating

`sunstone self-update` installs a newer signed release in place:

| Command | What it does |
|---|---|
| `sudo sunstone self-update --check` | Says whether a newer release exists, and changes nothing. It reads the settings, so it needs `sudo` or membership of the `sunstone` group, but not root. |
| `sudo sunstone self-update` | Installs the newest release if it is newer than this one, after asking. `--yes` does not ask; without a terminal and without `--yes`, nothing is installed. |
| `sudo sunstone self-update --version 0.2.0` | Installs that release, even if it is older or the same. |
| `sudo sunstone self-update --file sunstone_0.2.0_amd64.deb --sums SHA256SUMS --sig SHA256SUMS.sig` | Installs a release copied by hand to a host without GitHub access. |
| `sudo sunstone self-update --rollback` | Goes back to the version the last update came from, with the configuration and state as they were before that update; today's are saved first. |

An update:

1. Lists the 30 newest releases on GitHub, release candidates included, and takes the newest one newer than the installed version and no newer than `hold_version`, if that is set; or the one asked for, whatever the hold.
2. Downloads its package, `SHA256SUMS`, and `SHA256SUMS.sig` into `/var/lib/sunstone/update/cache/<version>/`, then checks the signature against the keys the installed package trusts, and the package against its checksum. If either check fails, nothing changes.
3. Makes sure a verified package of the installed version is at hand to roll back to, downloading it if need be.
4. Backs up `/etc/sunstone` and the state directory to `/var/lib/sunstone/update/backups/`, mode 0600, keeping five.
5. Installs the package with `apt-get`, whose `postinst` restarts the service if it was running.
6. Runs the new version's `sunstone check`, and, if the service was running, waits up to 90 s for it to answer as the new version at `/api/version`.
7. If installing or checking fails, reinstalls the previous version, restores the backup, restarts the service, and says whether it answers again.

It exits 0 when it updated or found nothing newer; 1 when a release was refused, the update was declined or failed and was rolled back, or GitHub could not be reached; and 2 for a usage error. The last result is in `/var/lib/sunstone/update/last-update.json`; the installed version, the one it replaced, and the newest other stay cached, so a rollback has a package to go back to even after a downgrade.

| Command | What happens |
|---|---|
## The daily timer

`sudo systemctl enable --now sunstone-update.timer` updates every day, at a random moment in the four hours after midnight, catching up after downtime; `journalctl -u sunstone-update` shows what each run did, and `systemctl list-timers sunstone-update.timer` when the next is. Each run is `sunstone self-update --unattended`: the same update, without asking, with two rules of its own. It installs only a release newer than this one, no further than `hold_version`. And it leaves out a release whose install failed last time, until a newer one comes, so a broken release is not installed and rolled back every day; `sudo sunstone self-update --version X` tries it by hand. A run that fails and rolls back fails the unit, so `systemctl --failed` shows it. The timer ships disabled, as the service does.

## Holding a version

`hold_version = "0.2.0"` under `[update]` keeps updates that pick the release themselves, the timer's among them, at or below 0.2.0; `--check` says what the hold keeps back. Naming a newer release with `--version` at the console still installs it.

## Self-update through a proxy

`https_proxy = "http://proxy.example.com:3128"` under `[update]` sends self-update through a proxy that supports `CONNECT`; without it, `HTTPS_PROXY` from the environment, which the timer's service does not have. Credentials in the URL are refused, since settings end up in backups and support requests. Certificates are verified against the system's CA bundle and the CA certificates in `/etc/sunstone/ca.d/`, never the bundled interpreter's own paths. A proxy that inspects TLS presents certificates its own CA issued, which self-update refuses, naming `/etc/sunstone/ca.d/`: get the CA certificate from your security team, compare its fingerprint with theirs (`openssl x509 -noout -fingerprint -sha256 -in corp-ca.pem`), copy it there as a `.pem` or `.crt` file, and run `sudo sunstone self-update --check`. It changes trust for Sunstone only, not the rest of the host. A file there that is not a PEM certificate stops self-update, naming the file, rather than being skipped. Python checks certificates against OpenSSL's strict X.509 profile, which many inspection CAs issued before clients enforced it fail ("CA cert does not include key usage extension"): if yours does and cannot be reissued, `tls_strict_x509 = false` relaxes only that profile, still checking chains, validity, and host names. `api = "https://HOST/api/v3"` takes releases from a GitHub Enterprise server instead.

| Command | What happens |
|---|---|
| `sudo apt remove sunstone` | Stops the service and the update timer, and removes `/opt/sunstone` and the integration files. Keeps `/etc/sunstone` and `/var/lib/sunstone`. |
| `sudo apt purge sunstone` | Also removes `/etc/sunstone`, which holds the topology, on-call directory, and trusted CAs, self-update's directory, and the links that enabled the service and timer. Keeps saved state in `/var/lib/sunstone/state` and says so; remove it yourself to delete it. |
