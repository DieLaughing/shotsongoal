# Shots on Goal: notes for Claude

Self-hosted NHL + PWHL hub for a person and their friends: scores, game pages with shot maps, standings, the Wire
(trades and news), alerts, calendar feeds, ticket links and US where-to-watch. Sibling app of Lights Out (racing).
Built with Claude Code; these notes are how it works. Personal deployment notes (if any) live in CLAUDE.local.md,
which is not committed.

## Shipping a feature (do this every time)
- Add an entry at the top of `sog/data/changes.yaml` (date, kind new|improved|fixed, title, text written for the
  people who use the app, link to try it). It feeds the What's new page (#/new), the dot on Settings and the home banner.
- `.venv/bin/python tools/changelog.py` rewrites CHANGELOG.md (a test fails if it's stale).
- `.venv/bin/python tools/release.py` creates/updates the day's GitHub Release (tag v<YYYY.MM.DD>) from the same
  entries; publishing a release builds the Docker image (.github/workflows/docker.yml).
- Tests: `.venv/bin/python -m pytest -q`. Fixtures in tests/fixtures are trimmed real responses from 2026-10-11.

## How it runs
- One container (Dockerfile), port 8788, all state in /data (SQLite, VAPID key, link secret). Settings come from env
  vars: see .env.example. compose.yaml runs the published image (+ optional cloudflared).
- `./deploy.sh` (maintainers) rsyncs the source to a server over SSH, builds there and restarts; settings in deploy.env.
- web/sw.js caches the shell and shows web/offline.html when the server can't be reached (Cloudflare 502/530).
- Pages only read the saved copy (sog/feed.py); pollers refresh it on schedules. Live game pages refresh only while
  viewed.

## Access
- Cloudflare Access signs people in (one-time PIN) and passes a signed JWT; sog/access.py verifies it against the
  team's certs (SOG_ACCESS_TEAM / _AUD). Anyone with an email gets that far; the app keeps its own approved list.
  The admin (SOG_ADMIN_EMAIL) is always approved.
- "Request access" pushes to ntfy (optional) with Approve/Deny = single-use signed links at /act (24 h). Invite links
  (/invite/<code>) approve whoever signs in with them, up to the link's max_uses (invite_use table; a group link
  can't re-admit someone denied or revoked; closing a used link sets max_uses to its use count). /admin lists people,
  invites, insiders and wrong-channel reports.
- Paths that must bypass Access: /act, /cal (per-person calendar token; stops working if revoked), /icons,
  /manifest.webmanifest, /apple-touch-icon.png, /apple-touch-icon-precomposed.png.
- SOG_LOCAL_EMAIL (alias SOG_DEV_EMAIL) skips Cloudflare and treats every request as that person; SOG_NO_POLL=1 stops
  the pollers. Local runs and home-network installs only.

## Features
- Bug reports (#/report, footer link on every page, Settings > Your reports): sog/bugs.py files anonymous GitHub
  issues (labels from-app + bug|enhancement; @mentions broken; page/device/version table) with SOG_GITHUB_TOKEN
  (fine-grained, Issues read/write); bug_report table keeps who sent what; /api/bugs refreshes state + the
  owner's latest comment every 10 min. 5 a day per person. No token = GitHub's prefilled new-issue link.
- "Your team" cards (top of Tonight, default slate only): /api/myteams -> sog/home.py team_summary per favourite from
  the cached team schedule + standings (latest season only: a 60-day gap splits seasons; off-season = last season's
  place, no streak/week). Cards tinted with the team colour; live/final state comes from the slate. Kept 5 min client-side.
- Spoiler-free: settings.spoilers {teams, games, seen} (game keys nhl:<id> / pwhl:<id>), rules in sog/spoilers.py,
  mirrored by spoilerHidden() in web/app.js. Started games from today/yesterday only. Hidden = no score on cards/hero,
  game page cover, Standings/team page covered when a hidden game is final, Wire items about it after puck drop
  blurred; alerts.py skips goal/final pushes (puck drop still sent). hiddenToday() loads today's + previous slate.
- Pick'em (#/picks, sog/picks.py, pick table): one pick per person per game before its start (server checks the
  slate's state/start), one lock per date (2 pts if right, 0 if wrong). Results are filled from final games in the
  slates GET /api/pickem loads (+ up to 10 older pending dates). Friends' picks only after puck drop; names =
  settings.nickname or the email's local part (friend_names(); emails never sent). Season = Jul-Jun, week = Mon-Sun.
  The table is covered while a spoiler-free game is hidden.
- Friends on games (sog/social.py): watching + reaction tables. /api/games adds g.watching, game pages add d.social
  (watching, reactions per event key g:<period>-<time>-<scorer> / p:...-<player>, mine, rivals). Rival = a friend
  whose first favourite in that league is the other team; the final alert appends "Tell X." / "X will enjoy this one."
  Watching rows go a day after the game, reactions at the July 1 season rollover (cleanup hourly from /api/games).
- Layout (2026-10-13 tidy-up): tabs Tonight / Pick'em / Wire / League (#/league = standings + your-team tiles;
  #/standings and #/teams route there). Admin is a link in Settings. Tonight: team cards replace the "Your teams"
  list; one banner slot (get-app/alerts first, else What's new). Cards use cardWatch() (app + have it); the full
  watchLine (why, tickets) is on the game page. Game page: scoring, shot map, by period, stars, then "More stats".
- Settings (web/app.js settingsView) save on every change (saveSettings: optimistic, queued PUTs of the whole settings
  object, toast). Team pickers group NHL teams by sog/teams.py DIVISIONS. Home market = one team (local is a list server-side).
- Phase 1: access, Tonight, Game, Standings, Teams, Settings, where-to-watch (service links; ESPN+ also links Hulu,
  where Disney+ bundle users watch ESPN+ games).
- Phase 2: the Wire (ESPN transactions + Story/HeadlineNews, Sportsnet RSS, Bluesky insiders editable in /admin),
  team News & moves, per-person calendar feeds at /cal/<token>/<TEAMS>.ics.
- Phase 3: web push (VAPID; alerts for favourites: puck drop, goals, finals, trades; per-person toggles), shot map +
  PP/goalie-pulled banners from play-by-play, written recap for finals, wrong-channel reports (ntfy + /admin list).
  Alerts record existing events the first time they see a league+date, so restarts never replay goals; yesterday's
  scoreboard is watched while a late game is still live.
- PWHL: sog/pwhl.py = HockeyTech client + parsers into the NHL shapes (key/client_code are the public ones thepwhl.com
  loads inline). Team keys are "PW-<code>" (BOS, MTL, SEA, VAN... exist in both leagues); team dicts carry `code` for
  display and `league`. One scorebar call (400 days back, 240 ahead) serves days, team schedules and alerts; game page
  = gamesummary + pxpverbose (shot x/y on a 600x300 rink, away attacking right: flipped so home shoots right).
  Standings: W = regulation_wins, OTW = non_reg_wins, OTL = non_reg_losses, L = losses (reg_losses/ot_losses don't add
  up). Before a season starts, standings, roster and stats use last season. Where to watch = the league's page only.
  Wire: THN women's RSS, The Ice Garden (only stories naming a PWHL nickname or "PWHL"), PWHL Bluesky list
  (insider.league column). UI: NHL | PWHL | Both pill in the header (per device, `?league=` in a URL sets it); Both =
  Tonight and Wire in separate sections, Standings/Teams get a one-league picker; PWHL mode uses Boston Fleet colours
  (#163F36 / #B3DFD7 dark). Every 6 h the app compares the league's team list (teamsbyseason) with teams.PWHL and
  pushes the admin via ntfy once per change (new nickname, rename, unknown team).
- Tickets: NHL games carry `tickets` = the feed's ticketsLink (Ticketmaster event); PWHL = the scorebar's TicketUrl,
  else the league's tickets page for upcoming games. Shown only before puck drop.
- Ideas not started: playoff bracket, trade-deadline mode, friends in other markets.

## Wire notes
- NHL.com news RSS answers 403 even to a Chrome fingerprint: not used. ESPN previews/recaps/videos are filtered out.
- ESPN uses LA/NJ/SJ/TB/UTAH and its own team ids: mapped in sog/wire.py. Free-text posts are tagged by nickname,
  city (not New York) or "(ABBR)".

## NHL API notes
- api-web.nhle.com 307-redirects and 403s Python's default client: fetch with curl_cffi impersonate="chrome".
- tvBroadcasts: market H/A/N + countryCode. A US "N" listing with no US H/A = national exclusive.
  2026-27 survey: TNT/truTV/HBO MAX 59 exclusive, ESPN+/HULU/Disney+ 47, ESPN 36, ABC 16; NHLN never exclusive.
- Where-to-watch is US-only; each person picks their services and the teams whose home market they live in (blackouts).
  Networks/rules in sog/watch.py + sog/data/networks.yaml; recheck every October.
- Game page = landing + right-rail (linescore, shots, team stats) + boxscore.

## Conventions
- No league or team logos (trademarks); team marks are coloured squares with the abbreviation.
