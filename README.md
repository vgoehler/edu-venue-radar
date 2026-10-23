# Digital Education Venue Radar

Keeps track of conferences on digital education, AI in education, computing education and the Scholarship of Teaching and Learning. It publishes one page through GitHub Pages, grouped by conference year and continent, with every call of an edition (workshops, papers, special sessions, ...), its deadline, the organizer and the ICORE rank.

The radar lists venues and nothing else. Which venue suits which project is decided elsewhere, by whoever uses the list.

## Idea

- `registry.yaml` holds what a person has confirmed: per series the organizer, topics, ICORE acronym, URL pattern, and per edition location, dates and its calls with their deadlines. It is the only thing edited by hand.
- The **crawler** fetches each series' current page once a week, notices when it changed, lists future dates that stand next to the call keywords, and probes whether the next edition's page is online yet. It writes `data/crawl/<id>.json` and never touches the registry.
- **ICORE** ranks come from the portal (`data/icore.json`), always from the newest ranking edition it offers.
- The **page** (`docs/index.html`) shows per series the first edition that still has a call open. When all calls of an edition are over and the next edition is not entered yet, the page guesses it: same month one year later, each call's previous deadline as "typically", previous page as link. So a 2027 edition moves to 2028 by itself.

## Use

```sh
poetry install
poetry run edu-venue-radar list            # current edition and call of every series
poetry run edu-venue-radar crawl [ids...]  # fetch pages, record changes and candidate deadlines
poetry run edu-venue-radar icore           # look up ICORE ranks
poetry run edu-venue-radar build           # write docs/index.html
poetry run edu-venue-radar roll <id>       # append the next edition to registry.yaml
```

`--today 2027-03-01` pretends another day, to see how the page will roll over.

## Updating the registry

When the crawler flags a change, a candidate date or a next-edition page, open the link, check, and enter the facts in `registry.yaml`: confirmed `deadline`s under `calls`, `start`/`end`, `location`, and the edition's own `url`. To move a series to the next year by hand, `edu-venue-radar roll <id>` appends the edition with each call's previous deadline as `deadline_hint`. Field reference is at the top of `registry.yaml`.

For pages that list "date, label, date, label" (like DELFI's Termine page), set `layout: date-first`, so the crawler reads the label after each date. `deadlines_pattern` adds a separate dates page to the crawl.

## Automation

`.github/workflows/update.yml` runs every Monday: ICORE, crawl, build, commit `data/` and `docs/`. A push that changes the registry or the code rebuilds the page without crawling. GitHub Pages serves `docs/` from `main`. The countdown to each deadline is computed in the reader's browser, so it stays right between weekly builds.

## Layout

| Path | Role |
|---|---|
| `registry.yaml` | series and editions, the hand-kept truth |
| `edu_venue_radar/registry.py` | loading, current edition, guessing the next one, `roll` |
| `edu_venue_radar/dates.py` | dates in English and German spellings, deadline candidates |
| `edu_venue_radar/crawl.py` | fetching, change detection, next-edition probes |
| `edu_venue_radar/icore.py` | ICORE portal lookup |
| `edu_venue_radar/site.py` | the static page |
| `data/` | crawl state and ranks, written by the tools |
| `docs/index.html` | the published page |
