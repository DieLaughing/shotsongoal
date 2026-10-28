# Shots on Goal: how it works

Self-hosted NHL + PWHL + college hockey hub for a person and their friends: scores, game pages with shot maps, standings, the Wire
(trades and news), alerts, calendar feeds, ticket links and US/Canada where-to-watch. Sibling app of Lights Out (racing).
These notes explain how every part works, where data comes from and the quirks of each source.

Operating rules shared with the sibling app (standards, speed budget, shared parts, ideas): docs/operating.md.
How the app moves (what animates, what must hold still, timings, rules for new UI): docs/motion.md, checked by
`.venv/bin/python tools/motioncheck.py` (PERF_CHROMIUM=/usr/bin/chromium locally; CI on every push).

## Shipping a feature (do this every time)
- Add an entry at the top of `sog/data/changes.yaml` (date, kind new|improved|fixed, title, text written for the
  people who use the app, link to try it). It feeds the What's new page (#/new), the dot on Settings and the home banner.
- `.venv/bin/python tools/changelog.py` rewrites CHANGELOG.md (a test fails if it's stale).
- `.venv/bin/python tools/release.py` creates/updates the day's GitHub Release (tag v<YYYY.MM.DD>) from the same
  entries; publishing a release builds the Docker image (.github/workflows/docker.yml).
- Tests: `.venv/bin/python -m pytest -q`. Fixtures in tests/fixtures are trimmed real responses from 2026-10-11.
- Speed budget: `.venv/bin/python tools/perfcheck.py` (needs `.venv/bin/pip install playwright` + a Chromium:
  `.venv/bin/playwright install chromium`, or PERF_CHROMIUM=/usr/bin/chromium). It runs tools/perf_server.py (the app
  with every league/news request answered from tests/fixtures), opens it in a phone-sized Chromium with 200 ms added
  per request, and checks first visit < 1.5 s, revisits < 300 ms, API p95 < 200 ms. CI runs it on every push and
  before every release image (blocks it; override: `tools/release.py --perf-override "why"`). Run it before staging.

## How it runs
- One container (Dockerfile), port 8788, all state in /data (SQLite, VAPID key, link secret). Settings come from env
  vars: see .env.example. compose.yaml runs the published image (+ optional cloudflared).
- `./deploy.sh` (maintainers) rsyncs the source to a server over SSH, builds there and restarts; settings in deploy.env.
- web/sw.js caches the shell and shows web/offline.html when the server can't be reached (Cloudflare 502/530).
- Pages only read the saved copy (sog/feed.py); pollers refresh it on schedules. Live game pages refresh only while
  viewed. Feed.cached serves an expired copy younger than STALE_OK (1 day; game pages 1 min) at once and refreshes it in
  the background (refresh_later, one task per key); pages use today_page(), never poll_today(). Only a missing copy
  makes a request wait on the leagues. API requests over 0.5 s are logged ("slow request").
- SQLite: WAL + synchronous=NORMAL. While the poller runs, automatic checkpoints are off (manual_checkpoints) and
  each poll pass runs a PASSIVE checkpoint on its own connection in a thread (Store.checkpoint), so no request waits
  on a checkpoint. Background saves in a pass share one commit (Store.batch). The Wire merge is kept until a source's
  copy changes (Feed._wire_memo); /api/wire and /api/standings send finished gzipped bytes (_finished).
- Poller = two loops (Feed.loop): _scoreboard_loop (NHL score/now + yesterday/our day + PWHL, alerts; every LIVE_POLL
  while busy, nothing else in it; passes over SLOW_PASS logged) and _background_loop (fights, live game pages, Wire,
  warm-up, careers, standings, checkpoint). The NHL caches score/now ~19 s; live pages re-ask every LIVE_REFRESH (10 s).
- Warm-up (Feed.warm, every poll pass, a few loads each: 4 idle / 1 busy): today's and yesterday's non-live game
  pages, favourite PWHL teams, then every NHL team's schedule/roster/stats, favourites first. Live games: favourites'
  and viewed games every DETAIL_POLL (20 s), the rest every WARM_LIVE_POLL (90 s). /api/game takes score/clock/state
  from the 10-second scoreboard (_freshen), so a 2-minute-old game copy (GAME_STALE_OK) still shows the live score.
- Phone side: api() keeps GET_CACHE; fast(path, rerender, quiet) waits up to FRESH_WAIT (150 ms) for fresh data and
  draws once; only a slower answer draws the phone's copy (< 30 min) and re-renders once after any running animation
  if the data differs. A write drops only the copies it changes (WRITE_DROPS; settings per changed field,
  SETTING_DROPS); an unlisted write or field drops them all. tests/test_cache_drops.py checks every route/field is
  listed. prefetch() 2.5 s after start and every 90 s while visible keeps Pick'em, Wire, standings and favourite team pages under ~90 s old. Tonight's banner slot keeps its last HTML
  (BANNER) across re-renders so the page doesn't shift while it's re-checked. Check speed changes with tools/perfcheck.py (its slow relay adds 200 ms per request).
- Page speed rules: each page makes its requests in parallel (hiddenToday() is one /api/hidden call, skipped without
  spoiler settings); showLoading() only paints "Loading…" after 350 ms.

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
  issues (labels from-app + bug|enhancement + needs-triage; @mentions broken; page/device/version table) with SOG_GITHUB_TOKEN
  (fine-grained, Issues read/write); bug_report table keeps who sent what; /api/bugs refreshes state + the
  owner's latest comment every 10 min. 5 a day per person. No token = GitHub's prefilled new-issue link.
- "Your team" cards (top of Tonight, default slate only): /api/myteams -> sog/home.py team_summary per favourite from
  the cached team schedule + standings (latest season only: a 60-day gap splits seasons; off-season = last season's
  place, no streak/week). Cards tinted with the team colour; live/final state comes from the slate. Kept 5 min client-side.
- Spoiler-free: settings.spoilers {teams, games, seen} (game keys <league>:<id>: nhl, pwhl, ncaam, ncaaw), rules in sog/spoilers.py,
  mirrored by spoilerHidden() in web/app.js; /api/hidden lists them for pages. Started games from today/yesterday
  only. Hidden = no score on cards/hero, game page cover, Standings/team page covered when a hidden game is final, Wire items about it after puck drop
  blurred; alerts.py skips goal/final pushes (puck drop still sent).
- Pick'em (#/picks, sog/picks.py, pick table): one pick per person per game before its start (server checks the
  slate's state/start), one lock per date (2 pts if right, 0 if wrong). Results are filled from final games in the
  slates GET /api/pickem loads (+ up to 10 older pending dates); underdog bonus: see Odds. Friends' picks only after puck drop; names =
  settings.nickname or the email's local part (friend_names(); emails never sent). Season = Jul-Jun, week = Mon-Sun.
  The table is covered while a spoiler-free game is hidden.
  Pools (picks.POOLS): the pros (NHL + PWHL) and college (ncaam + ncaaw) each have their own lock per date and their
  own table (/api/pickem returns `boards` {pro, college} for the pools shown; with both, a NHL & PWHL | College switch
  swaps the tables in place). Pick'em follows the league pill like Tonight: college games fold under their league
  heading (fold:picks:<pill>:<lg>), your teams first. No underdog bonus for college (no odds); a college tie settles
  every pick on it as wrong. Long school names on pick buttons show the ESPN code (pickName).
  "🎲 Pick N for me" (POST /api/pickem/random, picks.fill_random): the page sends the unpicked, unstarted games in its
  open sections (a folded college league is left out); the server keeps those on that date's slate and picks each one
  this person hasn't, weighted by odds.attach's win % (coin flip without odds). Never touches a pick or a lock.
- Odds, for fun (sog/odds.py; Settings > Display > Show odds, on by default): the DraftKings moneyline comes free in the
  NHL score feed (oddsPartners, matched by name; nhl.parse_score -> g.odds) but vanishes at puck drop, so the
  scoreboard loop saves each pre-game line to game_odds (write on change; all rows kept in memory, pages never
  query). Expected goals = ESPN scoreboard overUnder, every ODDS_POLL (30 min) in the background loop. odds.attach
  adds favourite, vig-free win %, high (7+) / low (5.5-) scoring and, once final, upset. No sportsbook links or logos.
  Pick'em upset bonus: a right underdog pick is 2 pts, the lock doubles (4); pick.dog is set with the result, only for
  games from picks.UPSET_FROM (SOG_UPSET_FROM, default 2026-10-15) so older picks keep their points. PWHL has no odds.
- Pre-game matchup (game page, state pre only): nhl.parse_preview from the landing's `matchup` + right-rail
  (last10Record, teamSeasonStats with ranks, seasonSeries, gameInfo coaches/scratches); no extra requests.
  /api/game adds division places from the saved standings (_with_places). The NHL names no starting goalies
  pre-game, so the page lists each team's goalies this season. previewBlock() in web/app.js; apart() greys the away
  side of a bar when both team colours are near-identical.
  Saved game copies carry `shape` (feed.GAME_SHAPE): bump it whenever parse_detail gains fields a page needs, or
  pre-game copies saved before the deploy keep the old fields for up to 30 minutes (a never-expiring final forever).
- Friends on games (sog/social.py): watching + reaction tables. /api/games adds g.watching, game pages add d.social
  (watching, reactions per event key g:<period>-<time>-<scorer> / p:...-<player>, mine, rivals). Rival = a friend
  whose first favourite in that league is the other team; the final alert appends "Tell X." / "X will enjoy this one."
  Watching rows go a day after the game, reactions at the July 1 season rollover (cleanup hourly from /api/games).
- Layout (2026-10-13 tidy-up): tabs Tonight / Pick'em / Wire / League (#/league = standings + your-team tiles;
  #/standings and #/teams route there). Admin is a link in Settings. Tonight: team cards replace the "Your teams"
  list; one banner slot (get-app/alerts first, else What's new). Cards use cardWatch() (app + have it); the full
  watchLine (why, tickets) is on the game page. Game page: scoring, shot map, by period, stars, then "More stats".
- Milestones: the poller saves career totals (player/<id>/landing, 3 at a time) as career:<TEAM> for favourite NHL
  teams, ~daily, only for teams that haven't started playing today. Pages only peek (feed.careers). home.near_milestones
  -> one line on the team card, a list on team pages; alerts._milestone adds "🎉 Nth career goal" to goal alerts
  (saved total + this player's goals tonight; only when the copy was saved before puck drop).
- Momentum + shot quality: web/app.js momentumCard/xgOf from d.shotmap (no extra request). xG = logistic on distance
  and angle (~22% slot, ~1.5% blue line), labelled as the app's estimate.
- Fight alerts (notify.fights, opt-in): while busy, once a minute per live NHL game a fan wants them for, the poller
  reads gamecenter/<id>/landing penalties ("Fighting"); first look per game only records.
- Speed: GZip on responses; /api/team sends the last 10 results + next 10 games; non-live game pages refresh in the
  background (_game_stale_ok); Tonight warms the team cards' game pages after it renders.
- Page transitions (web/app.js route -> renderRoute, rise/slapshot; Settings > Display picks, per device in
  localStorage `motion`, default rise): Web Animations API. The old page goes at once; when a navigation's real
  content lands in #view (MutationObserver, not the Loading placeholder) either #view's blocks fade up 14 px one after
  another (rise: 340 ms each, 35 ms apart, first 8 staggered, h1 un-blurs) or the page flies in from
  the side (slapshot: +1 right: forward tabs in NAV_ORDER, game/team pages; -1 left: back), overshoots and snaps back
  (~280 ms). Both are from / like OpenUI's trip planner demo. Whole-pixel translate only: scale/skew made text re-render and jump when the animation ended.
  Same address re-shown and quiet refreshes never animate; off with settings.animations =
  false or prefers-reduced-motion. The tab highlight is one .tab-pill moved by movePill(): Web Animations "liquid" stretch (leading edge first,
  trailing edge follows, small overshoot, 380 ms); labels/icons cross-fade colour; the toast springs out from the middle.
  Every switch (.seg, .league) gets the same pill (placeSwitches; liquid() is shared). A MutationObserver that only
  reacts to changes touching a switch places pills once per frame (rAF): a page built in steps is measured once. Switches that redraw the page on tap are matched by their option labels: pointerdown notes the spot being
  left, and the redrawn switch's new pill slides from it (within 1.5 s).
  League's Standings | Leaders (data-swaps: two addresses that look like one switch) keep the scroll and page height
  and cross-fade (200 ms, no movement) instead of the page animation, which read as a bounce there.
- Card -> game morph (navigate() wraps hash changes in document.startViewTransition): between a list and a game page
  the tapped (or first on-screen) a.body / a.hero-top and the game page's .scorebug share view-transition-name
  "matchup" (inline, cleared on vt.finished), so the card grows into the scoreboard and back. route() runs inside the
  callback with `morphing` set (no Rise), capped at MORPH_WAIT 800 ms. Without the API, motion off or the card off
  screen, plain route(). Timings in style.css (::view-transition-*). Works in Chromium and Firefox 144+ (checked). placeSwitches only writes when something changed and drops
  its own mutation records (takeRecords): any class write, even removing an absent class, wakes the observer, and a
  switch with nothing picked once froze the page in an endless loop.
- Navigation chrome: tab bar = icon (20 px) + label (web/index.html inline SVGs); scrolling down adds .compact (icons fold
  away, ~39 px bar) and .tucked on the header (slides up, keeping the safe-area strip); any scroll up / top of page /
  new page restores both. Settings = outlined button with a gear,
  league switch shows the selected league filled. Sub-pages start with backLink(fallback): history.back() when the
  page was reached inside the app (cameFromApp), else the fallback (games -> #/, teams -> #/league, others -> #/settings).
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
  (insider.league column). UI: NHL | PWHL | NCAA | All ("both") pill in the header (per device, `?league=` in a URL sets it); Both =
  Tonight and Wire in separate sections, Standings/Teams get a one-league picker; PWHL mode uses Boston Fleet colours
  (#163F36 / #B3DFD7 dark). Every 6 h the app compares the league's team list (teamsbyseason) with teams.PWHL and
  pushes the admin via ntfy once per change (new nickname, rename, unknown team).
- College (NCAA men's + women's): sog/ncaa.py = ESPN site API (site.api.espn.com .../hockey/mens-college-hockey and
  womens-college-hockey) into the NHL shapes. Team keys "CM-<ESPN id>" / "CW-<ESPN id>" (ESPN ids are per school, so a
  school's two teams share an id and a logo). sog/data/college.json (teams.COLLEGE_INFO: code, school, full name,
  conference, colour) is built by tools/college_teams.py: ESPN has no college colours (each is the logo's main colour)
  and no women's conferences (WOMENS_CONF, recheck each season); a team the standings list under a different id than
  the team list (Minnesota State women) takes the standings id, which is the one games use. Rerun it each season.
  ESPN gives scores, clock, goals per period (`periods`), records, poll ranks (curatedRank, 99 = unranked; else the
  saved `<lg>:ranks` poll) and streams (`networks`), but NO scorers, shots, players or play-by-play: the game page is
  the scoreboard + by period + each team's last five, with a "Box score on ESPN" button (g.espn). The summary's
  `news` is the sport's latest stories, not the game's: not used. Days = scoreboard?dates=YYYYMMDD (`<lg>:day:<date>`,
  prev/next from the league calendar); game page = summary (`<lg>:game:<id>`) with state/score from the saved day;
  team page (Feed.ncaa_team) = teams/<id>/schedule + "This season" worked out from it (ncaa.season_summary: home,
  away, conference = both teams in the same conference since ESPN's conferenceCompetition flag is often empty, goals a
  game, last five) + arena (core API teams/<id> venue, 30 days) + poll move (`<lg>:poll` {rank, previous}) + a Roster
  tab (teams/<id>/roster: ~half the men's D-I teams, no women's; name/number/class from years/hometown/height, no
  stats exist) + a Highlights tab (news?team=<id>: Media items tagged with their event id, this season's games only).
  Tabs only show when ESPN has something. A final's game page gets "▶ Highlights" from either team's saved list
  (Feed.ncaa_highlight peeks and refreshes in the background, never waits); standings = overall records per conference sorted by
  win % (ESPN's college points are always 0; no conference standings). Ties stand (outcome "T"; records W-L-T, an OT
  loss is an L). The scoreboard loop polls each college league every COLLEGE_LIVE 15 s while busy, else COLLEGE_IDLE
  10 min; goal alerts come from the score (ncaa.goals: one key per team per goal, no scorer). Where to watch =
  watch.college + networks.yaml `college:` (no blackouts; the listed stream you have leads; B1G+/FloHockey/NCHC.tv are
  services with `college: true`, shown in Settings only to people who follow or show college). No odds, Wire,
  leaders or players for college (Pick'em: see Pick'em, its own pool). UI: NCAA = both college leagues; All = every league. Each college league
  on Tonight is a <details> whose summary IS the league heading ("NCAA Men's Hockey · 20 games · 1 of yours", chevron at
  the end): open by default under NCAA, shut under All (so the NHL isn't buried), and what you pick is kept per pill + league (localStorage fold:<pill>:<lg>);
  game pages' "last games" skip anything 60+ days old (ESPN fills in last season) and read team-first (ncaa.our_score); Standings and
  Leaders pick one league from those shown (pageLeague). College logos are their own sheet, /img/college-logos.css
  (Division I only, ~120 KB gz), loaded only by people who show or follow college; the team picker folds each
  college league by conference.
- Tickets: NHL games carry `tickets` = the feed's ticketsLink (Ticketmaster event); PWHL = the scorebar's TicketUrl,
  else the league's tickets page for upcoming games. Shown only before puck drop.

- Players (#/player/<id> NHL, #/pplayer/<id> PWHL): bio, this season, Games (form chart + game log), Career (totals,
  season by season with other leagues hidden behind a button, awards) and Advanced (NHL only, MoneyPuck). Every name
  in scoring, three stars, box scores, team leaders, rosters and milestones links here (parsers carry `pid`).
  Leaders (#/leaders, League tab: Standings | Leaders) and Search (#/search, header icon: players from every roster
  via /api/search, filtered on the phone; teams; the top team's next and last game). Search ignores accents,
  apostrophes and periods, knows fan nicknames (TEAM_ALIASES: habs, B's, bolts…) and, when fewer than 3 players match,
  takes names with a word within 1 letter (2 for 7+ letters) of what was typed (near()). Player pages and leaders follow
  spoiler-free like the team page and standings.
- sog/images.py: photos at /img/p/<league>/<team>/<id>-<96|192>.webp, downloaded once, shrunk with Pillow (80 KB
  headshot -> 2 KB), kept in /data/img (7 days, misses remembered 1 day), a week's Cache-Control; sw.js serves /img/
  cache-first from its own cache (600 entries). NHL photos use this season's mugs URL, else the landing `headshot`.
  Logos are ONE stylesheet, /img/logos.css?v=<hash> (from /api/me `logos` when marks=logos): `.mark.lg-<ABBR>` rules
  with 56 px WebP data URLs (~77 KB gz for all 44 teams, dark versions only where they differ). NHL logos come from
  ESPN's 500/500-dark PNGs (the NHL's SVGs are up to 35 KB each); until the sheet loads, marks stay badges.
- Team page: header, next game as a full card, then Games (one line per game) | Players (roster merged with this
  season's stats, per group, best first; milestones on top) | News. The tab is remembered (localStorage teamTab).
- sog/moneypuck.py: MoneyPuck's season skaters/goalies CSVs (listed on moneypuck.com/data.htm; free for
  non-commercial use with credit, so the Advanced tab links MoneyPuck.com). Fetched every 6 h in the background; a
  player page only peeks at the saved copy (Feed.moneypuck_peek) and never waits on the 2 MB download.

## Wire notes
- NHL.com news RSS answers 403 even to a Chrome fingerprint: not used. ESPN previews/recaps/videos are filtered out.
- ESPN uses LA/NJ/SJ/TB/UTAH and its own team ids: mapped in sog/wire.py. Free-text posts are tagged by nickname,
  city (not New York) or "(ABBR)".

## NHL API notes
- api-web.nhle.com 307-redirects and 403s Python's default client: fetch with curl_cffi impersonate="chrome".
- tvBroadcasts: market H/A/N + countryCode. A US "N" listing with no US H/A = national exclusive.
  2026-27 survey: TNT/truTV/HBO MAX 59 exclusive, ESPN+/HULU/Disney+ 47, ESPN 36, ABC 16; NHLN never exclusive.
- Where-to-watch: settings.country US (default) or CA; each person picks their services (shown for their country:
  services() tags each with one) and the teams whose home market/region they live in (blackouts). Rules in
  sog/watch.py (US: watch_for; Canada: _canada, from the CA tvBroadcasts) + sog/data/networks.yaml (top = US,
  `canada:` = CA services/networks/out_of_market). Canada 2026-27: Sportsnet nationals never blacked out, SN+ =
  Monday Night Hockey (streaming only), Prime = Wednesday, TVA Sports = French national (a TVA-only game is out of
  market in English), TSN/RDS/SN regionals in-region only, everything else Sportsnet+ Premium; no CBC from 2026-27.
  Recheck both every October (issue #5 asked for Canada).
- Game page = landing + right-rail (linescore, shots, team stats) + boxscore.
- Player page = player/<id>/landing + player/<id>/game-log/now. Leaders = skater-stats-leaders/current and
  goalie-stats-leaders/current. PWHL players = HockeyTech view=player category=profile|seasonstats|gamebygame
  (gamebygame needs season_id); PWHL photos assets.leaguestat.com/pwhl/240x240/<id>.jpg.

## Conventions
- Team marks are logos by default (settings.marks, default "logos" via _user_settings) or coloured badges with the
  abbreviation; player photos are on by default (Settings > Display: marks logos|badges, photos on|off), loaded from the leagues' image servers through /img/ and
  never committed to the repo (trademarks, likenesses).

## Issues and docs

### Issue tracker

Issues live in this repo's GitHub Issues, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the default label names: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

One `GLOSSARY.md` and one `docs/adr/` at the repo root, created only when needed. See `docs/agents/domain.md`.
