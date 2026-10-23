# edu-venue-radar

Digital Education Venue Radar: a public, neutral list of conferences with their calls and deadlines. It holds venues only, no evaluations, project fit or notes about who uses it. Projects that use the radar refer to series by `id` from their own side; this repo does not point back to them.

`registry.yaml` is the truth. Crawler findings are hints; enter a deadline only after checking it on the official page. Run `poetry run pytest` and `poetry run ruff check .` before committing.
