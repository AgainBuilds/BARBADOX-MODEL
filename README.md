# Barbadox's Model (standalone)

This is the original 5-factor model only: Poisson core (factors 1-2), formation,
absences/rotation, derby/game-state. Nothing else. No web app, no password, no bet log,
no LLM calls of any kind. It runs on GitHub's own servers on a schedule, so it never
needs a chat session or a laptop open.

## One-time setup (all doable from the GitHub app on your phone)

1. Create a new **public** repo (private repos only get free Actions minutes up to a
   monthly cap; public repos get unlimited Actions minutes, which matters since this
   runs daily). Push these files to the repo root, keeping the `.github/workflows/`
   folder structure intact.
2. Get a free API key at https://www.football-data.org/client/register.
3. In the repo: **Settings -> Secrets and variables -> Actions -> New repository
   secret**. Name it `FOOTBALL_DATA_KEY`, paste the key.
   (Optional: a free key from api-football.com as `API_FOOTBALL_KEY` also covers the
   Saudi League. Skip it and the model just runs the other 6 leagues.)
4. Go to the **Actions** tab and enable workflows if asked. That's it. It now runs
   itself every morning (06:00 UTC / 07:00 Nigeria time), or tap **Run workflow** any
   time you want it to run immediately.

## Output screen (optional)

Every `run` and `review` also writes `docs/index.html`, one plain static page listing
every logged pick, colour-coded by HIT/MISS/pending, with a hit-rate summary at the
top. No server, no JS framework, nothing it fetches from anywhere, just a file.

To view it from your phone: repo **Settings -> Pages -> Source: Deploy from a branch
-> Branch: main, folder: /docs -> Save**. GitHub gives you a URL like
`https://<your-username>.github.io/<repo-name>/`. It updates itself every time the
workflow runs. Worth knowing: GitHub Pages on a public repo is a public URL, anyone
with the link can view it (no password, matching everything else here). If that's not
fine, skip this step and just read picks.csv directly.

## Where to look

- **picks.csv** — every pick that hit 79%+, with the result filled in once the match
  is graded. This is the file that matters.
- **context.csv** — one row per upcoming fixture. Blank by default. This is where you
  optionally fill in factors 3-5 by hand (see below). Edit it directly in the GitHub
  app: tap the file, tap edit, change the row, commit to main.
- **data/** — a short-lived cache used only within a single run (so `run` and `review`
  don't both re-fetch the same data). It is not committed; every run starts fresh.

## Filling in factors 3-5 (optional)

Every new fixture gets an empty row in context.csv automatically. If you leave it
blank, the pick runs on the Poisson core alone (factors 1-2) and says so plainly.
To add the rest, edit that row and set `checked` to `1`. Columns:

| Column | Meaning |
|---|---|
| `derby` | `1` if it's a derby/rivalry, else blank |
| `field_temp_c` | logged only, never changes the number |
| `home_absences` / `away_absences` | `Name:ROLE:importance;Name:ROLE:importance` or `none`. ROLE is `FWD`, `CRE`, `DM`, `DEF`, or `GK`. importance is 1-3 (3 = first-choice/top scorer). |
| `home_rotation` / `away_rotation` | 0 (none), 1 (some), 2 (heavy) |
| `home_formation_effect` / `away_formation_effect` | -2 to +2: current shape vs. the shape that scores for them, and the matchup against the opponent |
| `home_leads_taken` / `home_leads_extended` | out of their last 5-6 matches: how many times they took the lead, how many of those they went on to extend |
| `away_trailing` / `away_responded` | out of their last 5-6 matches: how many times they went behind, how many of those they responded |
| `checked` | set to `1` once you've filled the row in |

You don't have to fill in every column. Anything left blank just stays unadjusted.

### You don't need to fill in every fixture

Before asking you to research anything, `run` checks each fixture's best-case ceiling:
if even the most favourable absences and formation effect possible couldn't push it past
the threshold, it tells you so and skips straight past it. No wasted research time on a
fixture that can never qualify. This ceiling is mathematically exact for this model, not
a rough guess, verified by brute-force search in `test_upper_bound.py`. On a normal day
across 7 leagues, this is usually most of the fixtures: only a handful are ever close
enough to the line for factors 3-5 to matter.

## Commands, if you ever run it by hand

```
python barbadox_core.py run                        # today + next 3 days, all leagues
python barbadox_core.py run --date 2026-10-10 --days 3
python barbadox_core.py run --leagues PL,PD --threshold 0.79
python barbadox_core.py review                      # grade logged picks against results
```

## What was deliberately left out

Bet logging, CLV, Brier/log-loss scoring, the web UI, password auth, cloud sync beyond
plain git, and the 8 extra "expanded" factors (rest/load, travel, referee, set pieces,
possession, motivation, manager change, weather) — none of those were part of the
documented model, and most needed an LLM research pipeline to fill in. If you want any
of them back later, add them one at a time and check with `review` whether the hit
rate actually improves before keeping it. The `corners_cards.py` idea from the old
handoff notes is not started here either, for the same reason: no edge proven yet on
goals, so no reason to add a second market.
