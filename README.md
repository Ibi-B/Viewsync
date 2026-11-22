# Viewsync

Viewsync is a catalogue cache and consensus-ranking service for BeastED.

It fetches public catalogue data from configured sources, normalises media identities, combines ranked lists using Reciprocal Rank Fusion (RRF), and publishes versioned static JSON for BeastED to cache locally.

## Design principles

- Catalogue discovery is separate from playback resolution.
- A source outage must not erase a healthy Home row.
- The last valid snapshot from each source is retained and reused according to its freshness policy.
- Rankings distinguish provider agreement from a single provider's placement.
- Publications are immutable, versioned releases.
- The app consumes a configurable catalogue base URL.
- TMDB title detail and regional watch-provider metadata are ingested by this
  backend and published as part of the same unified catalogue release.
- Published TMDB metadata is retained in full. Thirty days is the enrichment
  refresh interval, not a deletion or catalogue-trimming rule.
- BeastED derives its Movies and Series subscription shelves from the published
  regional availability and never calls TMDB directly.

## Ranking model

For each media item, Viewsync calculates:

```text
score = sum(provider_weight / (k + rank))
```

Where:

- `rank` is the item's one-based position in a contributing list.
- `k` is the RRF damping constant, default `60`.
- `provider_weight` is divided across all lists supplied by that provider.
- A missing item contributes zero for that list.

The final ordering is:

1. Consensus score, descending.
2. Distinct contributing providers, descending.
3. Best rank, ascending.
4. Stable media ID, ascending.

## Repository layout

```text
catalog-config/   Source, row and ranking configuration
src/              Generator implementation
state/            Runtime source snapshots and last-good release state
dist/             Generated static catalogue releases
tests/            Unit and integration tests
```

## Local generation

```bash
python -m pip install -r requirements.txt
python -m pytest
python -m src.main --output dist
```

## TMDB detail and availability enrichment

The generator enriches each distinct TMDB movie/series ID within the existing
TMDB source snapshots. It stores the full TMDB detail response (including the
configured appended credits, external IDs, images, keywords, recommendations,
release data/ratings, content ratings, and videos where supported) together
with the complete regional `watch/providers` response. All provider categories
are preserved; BeastED currently displays subscription (`flatrate`) results
while retaining rental, purchase, free, and ad-supported availability in the
published item for future features.

TMDB title details and provider availability have independent refresh schedules:
details are refreshed every 30 days; watch-provider availability is refreshed
every 12 hours. Provider-specific Discover shelves are generated for the six
allowlisted services in configured TMDB-supported regions. Viewsync publishes
the ordered Top 10 or Popular list (omitting lists with fewer than five titles),
including service logo, rank and a freshness status.

A refresh failure retains a last-good payload as stale only while it
remains inside the 150-day hard cache-age ceiling. At or beyond that ceiling,
the descriptive TMDB metadata and provider-availability payload are purged
from the next release; stable identifiers (including the canonical TMDB ID
and any known IMDb alias) are retained. A title whose first enrichment attempt
fails remains present in the slim catalogue and provider shelf, is marked
`unavailable`, and is retried on the next generation. A missing or expired
metadata payload therefore does not by itself block publication of an otherwise
valid catalogue release.

The complete TMDB detail and all regional availability categories are stored
once in each item's own detail JSON document. Global rows and provider shelves
contain only summary fields and a shared `details_path`. Each published JSON
document is capped at 4 MiB, below BeastED's 5 MiB client limit; the publisher
fails rather than truncating any field. The generator records actual file count,
total bytes, and largest document size in `generation-report.json`.

The complete detail travels through the existing identity merge, per-item
detail publication, and BeastED v2 catalogue contract. The durable
`viewsync-state` branch contains bounded source-list snapshots only; rich TMDB
payloads are read from the current public detail documents and are not copied
into append-only Git history. API credentials are GitHub Actions secrets only.

Viewsync's static catalogue and durable source snapshots are not stored in
Cloudflare R2. Radsync's separate R2 retention policy therefore applies only to
Radsync's historical archive and diagnostic objects; it must never expire the
Viewsync published catalogue or its current/previous-good provider state.

## GitHub Actions

The workflow generates and validates a catalogue release, then deploys it to GitHub Pages.

Scheduled runs are best-effort. BeastED must always retain and display its last successfully validated local catalogue.

## Adding TMDB

TMDB credentials are not stored in this repository. Configure them as GitHub repository secrets when available:

- `TMDB_API_KEY`
- `TMDB_ACCESS_TOKEN`

The TMDB provider is enabled in `catalog-config/sources.json`. GitHub Actions must have at least one of the `TMDB_API_KEY` or `TMDB_ACCESS_TOKEN` repository secrets configured for source ingestion and detail enrichment. Secrets are never written to snapshots or public releases.
