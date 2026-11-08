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

## GitHub Actions

The workflow generates and validates a catalogue release, then deploys it to GitHub Pages.

Scheduled runs are best-effort. BeastED must always retain and display its last successfully validated local catalogue.

## Adding TMDB

TMDB credentials are not stored in this repository. Configure them as GitHub repository secrets when available:

- `TMDB_API_KEY`
- `TMDB_ACCESS_TOKEN`

The TMDB source is disabled in the initial configuration until its credentials and permitted usage are confirmed.
