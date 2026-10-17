# What's new in Shots on Goal

Every update to [Shots on Goal](https://github.com/DieLaughing/shotsongoal), newest first. The same list is on the app's What's new page.
This file is generated from `data/changes.yaml` by `tools/changelog.py`; edit that file, not this one.

## October 16, 2026

- **Improved: Counting which pages get used.** The app now counts how often each kind of page is opened (Tonight, game pages, Pick'em, the Wire and so on), so the next features go where people actually spend time. It's a tally per page per day and never records who opened what. Counts are kept for six months.

## October 15, 2026

- **Improved: Game previews before puck drop.** Open any upcoming NHL game for the matchup. Each team's record, division place, streak and recent results; how they compare this season (goals for and against, power play, penalty kill, faceoffs, with league ranks); who's hot over the last 5 games; each team's goalies this season; and the season series so far. It all steps aside once the game starts.
- **New: Odds, just for fun.** Every NHL game now shows who's favoured to win and their chance (from DraftKings' line, with the bookmaker's cut taken out), plus a note when the books expect a high- or low-scoring game. Open a game for the full picture, and after the final you'll see if it was an upset. Nothing links to betting, and Settings → Display → Show odds turns it off. In Pick'em, picking the underdog now pays double if they win (marked 2× before puck drop), and your lock doubles that again. The bonus starts with tonight's games.

## October 14, 2026

- **Improved: Tidier game page, and buttons under your thumb.** The top of a game page is now in clear groups. The score card is just the game (a power play or 4 on 4 shows under the clock), then where to watch it with one button per app, then you and your friends, with "I'm watching" and "Watching later" side by side. On a phone, foldable or tablet the buttons sit on your thumb's side. Left-handed? Settings → Display has a Right-handed / Left-handed switch. On a computer they're centred.
- **Fixed: Livelier game clock.** Left a game or Tonight open during play and the clock seemed stuck? On busy nights the scoreboard was waiting behind other background work. It now updates on its own steady beat, and open live pages check every 10 seconds, so the clock and score keep up with the NHL's own scoreboard (which itself moves about every 20 seconds).

## October 13, 2026

- **Improved: Clearer buttons and a Back button.** The tabs at the bottom now have icons so they look like the buttons they are (they tuck away while you scroll down, along with the top bar, so the page gets the whole screen, and come back as soon as you scroll up), Settings is a proper button with a gear, and the NHL / PWHL / Both switch shows which one is on more clearly. Game, team and other pages now have a Back button at the top that takes you to wherever you just were.
- **New: Page animations.** Moving around the app now has a little snap to it. A new page comes in like a slapshot, fast from the side, then hits the back of the net and settles, and the highlight in the tab bar slides to the tab you picked. Tabs come from their side of the bar, games slide in from the right and back out to the left. It's over in under a third of a second and only starts once the page is ready. Prefer instant? Settings → Display → Animations between pages turns it off (it's also off when your phone's Reduce Motion setting is on).
- **Fixed: Team cards side by side.** Following more than one team on a computer or tablet? Their cards now sit side by side instead of the second one hiding off the edge. On a phone you still swipe between them, with dots underneath showing there's more than one. Behind the scenes the app also does less work per page, so the Wire and League tabs load a little lighter.
- **Improved: Instant tabs.** After the app opens, it quietly loads your other tabs and your teams' pages, so switching tabs is instant even on a slow connection, and each page updates itself a moment later if anything changed. Behind the scenes, every team page and every game on tonight's slate is kept fresh whether or not anyone is looking, with your favorite teams first, so opening a game you haven't looked at yet doesn't wait either.
- **New: Milestones, momentum and fight alerts.** Your team card and team pages now show players close to a round career number ("Mittelstadt is 2 goals from 100"), and when someone gets there, the goal alert says so. Game pages have a Momentum chart (who's been getting the shots, every 5 minutes) with a shot-quality number for each team. And if you like that sort of thing, Settings → Alerts has a new Fights switch (off unless you turn it on). Pages also download less, so they open quicker on mobile data.
- **Fixed: Faster tabs again.** Switching tabs had slowed to a second or more, mostly for anyone not on the home network. Pages now show the latest saved data straight away and refresh it behind the scenes, the team cards load less, and spoiler-free checks no longer hold pages up. Most tabs should feel instant again.
- **Improved: A tidier app.** Less scrolling, same features. The tabs are now Tonight, Pick'em, Wire and League (standings plus your teams; tap any team for its page). Tonight doesn't list your teams' games twice, game cards are shorter (tickets and the blackout details live on the game page), and only one tip shows at a time. Game pages lead with the scoring and shot map, with team stats, penalties and players under "More stats". Settings is grouped into You, Alerts & spoilers, and More, with What's new right at the top.
- **New: Watch with friends.** Open a game and tap "👀 I'm watching" so friends can see you're on it. Who's watching shows on Tonight too. Once the puck drops, react to goals and penalties with 🔥 😭 🤬 🍺 🥅 and see what everyone else thought. When your team plays a friend's, the game page calls out the rivalry, and the final-score alert tells you who to gloat at (or who'll be gloating). Reactions are cleared at the end of each season.
- **New: Pick'em.** A new Pick'em tab. Tap who you think wins each game, NHL and PWHL, before puck drop. Star one game a night as your lock for 2 points if you're right (nothing if you're wrong). Friends' picks appear once a game starts, and the tables show who's leading this week and this season. Pick the name friends see in Settings → Pick'em.
- **New: Spoiler-free mode.** Watching on DVR or catching the game later? Open any game and tap "🙈 Watching later", or switch it on for a whole team in Settings → Spoiler-free. The score stays hidden on every page, goal and final alerts hold off, and the standings and Wire stories that could give it away are covered too, until you tap "I've seen it". Puck-drop alerts still come, and it switches off by itself the day after.
- **New: Your team, up top.** Tonight now opens with a card for each of your favorite teams, in their colors. It shows tonight's game (or the next one) and where to watch it, the live score once it starts, where they sit in the standings, how far they are from a playoff spot, any streak, the last 7 days and the next few games. Follow more than one team? Swipe sideways.
- **New: Report a problem.** Found something off, or have an idea? Tap "Something wrong? Report it" at the bottom of any page (or Settings → Report a problem). It goes straight onto the app's to-do list on GitHub without your name or email, along with which page you were on and what phone you're using, so there's no need to explain that part. Settings → Your reports shows whether it's been fixed, plus any reply.
- **Fixed: Opens on today's games.** In the morning, Tonight could still show last night's games, because the NHL's own feed doesn't switch to the new day until around midday. The app now switches by itself (last night's games stay up until 6 am Eastern, or until a late game finishes), and it refreshes when you come back to it after a while instead of showing the page you left.

## October 12, 2026

- **Improved: Settings save by themselves.** No more Save button to hunt for. Every change in Settings saves the moment you tap it, with a quick "Saved ✓" at the bottom. Your teams now show at the top as a short list (tap Edit to change them), the team picker is grouped by division, your home market is one dropdown, and the alert switches sit together under Alerts.
- **Improved: Offline page.** If the server Shots on Goal runs on goes down (a power or internet blip at its home), the app shows a short "Shots on Goal is offline" page instead of an error, and reloads by itself once it's back. Your phone picks this up the next time you open the app.
- **Fixed: Home screen icon.** Phones showed an "S" instead of the app's icon on the home screen. Remove the app from your home screen and add it again to get the real one (on iPhone, turn alerts back on afterwards in Settings).
- **Improved: App icon in the header.** The crossed sticks and puck now sit at the top left, the same icon as the browser tab and home screen.
- **New: What's new.** This page. A dot on Settings and a banner on Tonight show when something new has been added.
- **New: Ticket links.** Upcoming games have a Tickets link. NHL games go straight to that game on Ticketmaster; PWHL games to theirs, or the league's tickets page until it lists one.
- **New: The PWHL.** Scores, game pages with a shot map, standings, team pages, news and alerts for the PWHL. Switch leagues with the NHL | PWHL | Both pill at the top; the PWHL side wears Boston Fleet colors. Add the Fleet as a favorite in Settings.

## October 11, 2026

- **Improved: New icon.** Two crossed sticks and a puck. If you added the app to your home screen, remove it and add it again to see it.
- **New: Get the app guide.** Step-by-step help to put Shots on Goal on your home screen and turn on alerts, for iPhone, Android and computers.
- **New: Alerts.** Push notifications for your favorite teams - puck drop (with where to watch), every goal, final scores and trades. Pick which in Settings.
- **New: Shot maps, banners and recaps.** Game pages show every shot on a rink, live power-play and goalie-pulled banners, and a short written recap after the final horn.
- **New: The Wire.** Trades and roster moves, NHL headlines and insiders from Bluesky in one feed, plus news on each team's page.
- **New: Calendar feed.** Every game for your favorite teams in your phone's calendar, with where to watch in each event.
- **Improved: Tap to watch.** Where-to-watch names (ESPN+, Hulu, NESN 360...) open the service, and game pages have an Open button.
- **New: Shots on Goal opens.** Tonight's games with live scores, game pages, standings and team pages, and where to watch every game for your market and the services you have.
