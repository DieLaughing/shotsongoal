# Shots on Goal

**NHL and PWHL scores, games, news and "where can I actually watch this?" in one place.**

Shots on Goal is a small self-hosted web app for hockey fans and their friends. It shows tonight's games with live
scores, game pages with shot maps, standings and team pages, a Wire of trades and news, alerts for your teams, and,
the part that started it all, **where to watch each game from where you live** with the services you have.
NHL blackout rules are a maze. Shots on Goal tells you "You have it" or "Not in your services" for every game.

It installs on a phone like an app (no app store), and you host it yourself for you and your friends.

> **A passion project.** Shots on Goal was built by one Bruins fan in Massachusetts, and watching real games shaped
> what came next. It's tested (`pytest`) and used every game night, but it's a hobby project, not a product. Expect
> rough edges, and feel free to fix them.

## What it does

- **Tonight:** every game with live scores, power-play and goalie-pulled banners, and where to watch.
- **Game pages:** a shot map of every shot on a rink, the box score, team stats and a short recap after the final horn.
- **Where to watch (US and Canada):** each person picks their country, their services (ESPN+/Hulu, ESPN, ABC, TNT/HBO Max,
  their local team channel... or Sportsnet/Sportsnet+, TSN, RDS, TVA Sports, Prime Video) and the teams whose home market
  they live in. Blackouts are worked out for them, and service names link straight to the
  service.
- **Standings and team pages:** schedules, rosters, team news and moves.
- **The Wire:** trades and roster moves, headlines, and hockey insiders from Bluesky (editable list) in one feed.
- **PWHL:** scores, game pages with shot maps, standings, team pages, news and alerts. Switch with the
  NHL | PWHL | Both pill at the top. The PWHL side wears Boston Fleet colors.
- **Alerts** (web push) for your favorite teams: puck drop with where to watch, every goal, finals, trades.
- **Calendar feed** with every game for your teams, each person with their own private link.
- **Ticket links** before puck drop, a **What's new** page, an offline page when the server is down, a
  "wrong channel? tell us" button, and an approval list so only people you approve get in.

## Not affiliated with anyone

Shots on Goal is an unofficial fan project. It is not affiliated with or endorsed by the NHL, the PWHL, any team,
ESPN, Sportsnet, Bluesky or any broadcaster. It reads the same public feeds their own websites use, politely, and
those can change or disappear at any time. It shows no league or team logos: teams are colored squares with their
abbreviation. News items link to the original articles. Please don't run a public instance for strangers. Run it for
yourself and your friends.

## What you need

| | |
| --- | --- |
| **A computer that's always on** | Anything that runs Docker: a Raspberry Pi 4 or 5, a mini PC, a NAS, an old laptop, a small cloud server. Images are built for 64-bit ARM (Raspberry Pi OS 64-bit) and regular 64-bit PCs (x86-64). |
| **How much power** | Very little. On a Raspberry Pi 5 with 8 GB, Shots on Goal uses about **120 MB of RAM**, well under 1% CPU even during games, and its data is a few MB. A 2 GB Pi is plenty, and it happily shares the box with other things. |
| **Docker** | [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin (`docker compose`). On a Pi: `curl -fsSL https://get.docker.com \| sh`. |
| **To use it away from home** *(optional)* | A domain name (around $10/year) using Cloudflare for DNS, and a free Cloudflare account. Cloudflare Tunnel gets visitors to your box **without opening ports on your router**, and Cloudflare Access handles sign-in. |
| **Approval pushes** *(optional)* | The free [ntfy](https://ntfy.sh) app on your phone, so "Approve / Deny" arrives as a notification. |

## Quick start: on your home network (5 minutes)

Good for trying it out, or if only people on your Wi-Fi will use it. There's no sign-in, so **never expose this mode
to the internet.**

```sh
mkdir shotsongoal && cd shotsongoal
curl -O https://raw.githubusercontent.com/DieLaughing/shotsongoal/main/compose.yaml
curl -o .env https://raw.githubusercontent.com/DieLaughing/shotsongoal/main/.env.example
```

Edit `.env`: set `SOG_ADMIN_EMAIL` **and** `SOG_LOCAL_EMAIL` to your email, `SOG_BASE_URL` to
`http://<that computer's IP>:8788`, and `TZ` to your time zone. To reach it from other devices on your network, change
the port line in `compose.yaml` from `"127.0.0.1:8788:8788"` to `"8788:8788"`. Then:

```sh
docker compose up -d
```

Open `http://<that computer's IP>:8788` and pick your teams and services in **Settings**. Phone alerts need HTTPS, so
for those use the Cloudflare setup below.

## Full setup: on the internet with Cloudflare (about 30 minutes)

This is how the original runs: people sign in with their email (a one-time code, no passwords), you approve who gets
in, and nothing on your home network is opened up. Below, replace `hockey.example.com` with your own address.

**1. Put your domain on Cloudflare.** Create a free account at [cloudflare.com](https://dash.cloudflare.com/), add
your domain, and switch your registrar's nameservers to the two Cloudflare gives you. Wait until it says "Active".

**2. Turn on Zero Trust.** In the dashboard open **Zero Trust**. Pick a team name (it becomes
`<team>.cloudflareaccess.com`) and choose the **Free** plan (up to 50 users). Cloudflare may ask for a card even on
the free plan.

**3. Create a tunnel.** *Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared.* Name it, then copy the long
token from the install command (the part after `--token`). Put it in `.env` as `TUNNEL_TOKEN=`. You don't need to run
their install command, because the `cloudflared` service in `compose.yaml` does that job.
Then add a **Public hostname** to the tunnel:
- Subdomain + domain: `hockey.example.com`
- Service: `HTTP`, URL `shotsongoal:8788` (the app's name inside Docker Compose)

**4. Lock it behind Cloudflare Access.** *Zero Trust → Access → Applications → Add an application → Self-hosted.*
- Application domain: `hockey.example.com` (no path). Session duration: up to 1 month, so people rarely re-sign in.
- Policy: **Allow**, Include **Everyone**, login method **One-time PIN**. "Everyone" can *sign in*, but Shots on Goal
  keeps its own approval list, so only people you approve get past its "Request access" screen. (Or list your
  friends' emails here instead and approve them in the app too.)
- Save, then open the application's overview and copy the **Application Audience (AUD) Tag**.

In `.env` set:
```sh
SOG_BASE_URL=https://hockey.example.com
SOG_ADMIN_EMAIL=you@example.com          # the email you'll sign in with
SOG_ACCESS_TEAM=<team>.cloudflareaccess.com
SOG_ACCESS_AUD=<the AUD tag>
SOG_LOCAL_EMAIL=                          # must stay empty on the internet
```

**5. Let a few paths skip sign-in.** Some things can't sign in: calendar apps, phones fetching home-screen icons, and
the Approve/Deny buttons in the ntfy app. Add a **second** self-hosted application (call it `shotsongoal-public-paths`)
with a **Bypass** policy (Include: Everyone) and these destinations:

| Path | Why it's safe |
| --- | --- |
| `hockey.example.com/cal` | Calendar feeds: each person's link has its own secret token and stops working if you remove them |
| `hockey.example.com/act` | ntfy Approve/Deny buttons: single-use signed links that expire in 24 h |
| `hockey.example.com/icons` | App icons |
| `hockey.example.com/manifest.webmanifest` | The "install as app" description |
| `hockey.example.com/apple-touch-icon.png` | iPhone home-screen icon |
| `hockey.example.com/apple-touch-icon-precomposed.png` | Older iPhone icon lookup |

**6. Start it.**
```sh
docker compose --profile tunnel up -d
```
Visit `https://hockey.example.com`, sign in with your admin email, and you're in. Friends sign in with theirs, tap
**Request access**, and you approve them from the **Admin** tab, or straight from your phone (step 7). Admin can also
make **invite links** that let someone in without the request step.

**7. (Optional) Approve from your phone with ntfy.** Install the ntfy app and subscribe to a topic. On the public
server ntfy.sh, pick a **long random topic name**, since anyone who knows it can read the requests. Then set
`NTFY_URL=https://ntfy.sh` and `SOG_NTFY_TOPIC=<your topic>` in `.env`. If you self-host ntfy with access control,
also set `NTFY_TOKEN`. Run `docker compose up -d` again to apply. The same topic also gets "wrong channel" reports and
a heads-up when the PWHL adds or renames a team.

### Already have a reverse proxy?

Shots on Goal signs people in with Cloudflare Access only (it checks Cloudflare's signed token). Without Cloudflare,
use home-network mode behind your own VPN (Tailscale, WireGuard). Support for other sign-in providers would be a
welcome contribution.

## On your phone

Open the site in **Safari** (iPhone) or **Chrome** (Android) and go to **Settings → Get the app**. It walks you
through adding it to the home screen and turning on alerts. On iPhone, alerts only work from the home-screen app.

## Settings

Everything is in `.env`. `.env.example` explains each line.

| Setting | What it does |
| --- | --- |
| `SOG_BASE_URL` | Your site's address, used in calendar and approval links |
| `SOG_ADMIN_EMAIL` | The admin: always let in, sees the Admin tab |
| `SOG_ACCESS_TEAM`, `SOG_ACCESS_AUD` | Cloudflare Access team domain and the app's AUD tag |
| `SOG_LOCAL_EMAIL` | Home-network mode: no sign-in, everyone is this person |
| `NTFY_URL`, `NTFY_TOKEN`, `SOG_NTFY_TOPIC` | Approval pushes and reports (optional) |
| `SOG_GITHUB_TOKEN`, `SOG_GITHUB_REPO` | In-app bug reports filed as GitHub issues (optional; see `.env.example`) |
| `TUNNEL_TOKEN` | Cloudflare Tunnel token (with `--profile tunnel`) |
| `TZ` | Server time zone (logs) |
| `SOG_DEFAULT_LOCAL` | Home-market team(s) new people start with, e.g. `BOS` for a New England group |

Favorite teams, services, home market and alerts are chosen by each person in the app. For example, someone in
Massachusetts marks the Bruins as their home-market team, so Bruins games show NESN instead of ESPN+.

## Make it yours

The name, colors and icon are easy to change:

- **Name:** "Shots on Goal" appears in `web/index.html` (title and `apple-mobile-web-app-title`),
  `web/manifest.webmanifest` (`name`, `short_name`), `web/offline.html`, `web/sw.js` (notification title),
  `web/app.js` (a few sentences), `sog/access.py` and `sog/app.py` (push and ntfy messages), `sog/ics.py` (calendar
  name) and `tools/changelog.py`. To find them all: `grep -rn "Shots on Goal" web sog tools`.
- **Colors:** the CSS variables at the top of `web/style.css` (`--accent` and friends, light and dark; the PWHL colors
  are in the "PWHL mode" block), plus `theme_color`/`background_color` in the manifest.
- **Icon:** replace `web/icons/icon.svg`, then make the PNGs from it, for example
  `rsvg-convert -w 512 icon.svg > icon-512.png` (also 192 and 180). Bump the `?v=` number on the icon links in
  `web/index.html` and the manifest so phones fetch the new one.
- **Source link:** if you run a modified copy for other people, point
  `<meta name="source">` in `web/index.html` at your fork (see License).
- **Where-to-watch** is for the US. `sog/watch.py` and `sog/data/networks.yaml` hold the rules.
- **Insiders** on the Wire are edited in the app's Admin tab.

After changing code, build your own image: in `compose.yaml` replace the `image:` line with `build: .` and run
`docker compose up -d --build`.

## Updating and backups

```sh
docker compose pull && docker compose up -d     # new version (published with each GitHub Release)
```
Everything that matters is in the `data/` folder next to `compose.yaml`: the database, your approved list and
everyone's settings, and the push-notification key. Back that folder up. If you lose the push key, everyone has to
turn alerts on again.

## Running from source (development)

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest httpx
SOG_LOCAL_EMAIL=me@example.com SOG_ADMIN_EMAIL=me@example.com .venv/bin/uvicorn sog.app:app --port 8788
.venv/bin/python -m pytest -q
```
Data goes to `./data`. `SOG_NO_POLL=1` stops the background pollers. There's no build step: the web app is plain
HTML/CSS/JS in `web/`.

| Path | What |
| --- | --- |
| `sog/nhl.py` | NHL web API client and parsers |
| `sog/pwhl.py` | PWHL (HockeyTech) client and parsers into the same shapes |
| `sog/feed.py` | The saved copy and the pollers. Pages never call the leagues directly |
| `sog/watch.py` + `sog/data/networks.yaml` | US where-to-watch rules and networks |
| `sog/wire.py` | The Wire: ESPN moves + news, RSS, Bluesky insiders; team tagging |
| `sog/alerts.py` | Push alerts |
| `sog/access.py` | Cloudflare sign-in check, signed links, ntfy pushes |
| `web/` | The installable web app |

## Contributing

Contributions are welcome: fixes when a feed changes, other countries' where-to-watch, a playoff bracket, other
sign-in providers. See [CONTRIBUTING.md](CONTRIBUTING.md). In short: **fork**, make your change on a branch, run the
tests, and open a pull request.

## License

[GNU AGPL v3.0 or later](LICENSE). In plain words: use it, change it, share it. If you run a **modified** version that
other people use over the internet, you have to offer them your source code (the "Source code" link on the What's new
page does that; point it at your fork). That way, improvements find their way back to everyone. Running it unmodified
for you and your friends needs nothing extra.
