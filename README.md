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

Each enrichment record has a 30-day freshness interval. A record younger than
30 days is reused without a new detail request. When a refresh fails, the last
successful TMDB detail and availability payload remains published and is marked
stale; it is not deleted or blanked. The full data travels through the existing
identity merge, row and item-detail publication, and BeastED v2 catalogue
contract. API credentials are GitHub Actions secrets only.

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

The TMDB source is disabled in the initial configuration until its credentials and permitted usage are confirmed.
