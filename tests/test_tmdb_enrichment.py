from datetime import datetime, timedelta, timezone

import pytest

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.tmdb_enrichment import (
    AVAILABILITY_REFRESH_AGE,
    DETAIL_REFRESH_AGE,
    PROVIDER_ALLOWLIST,
    _refresh_record,
    discover_provider_shelves,
    enrich_tmdb_snapshots,
)


NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def _snapshot(item):
    return SourceSnapshot(
        request_id="popular_movies",
        provider_id="tmdb",
        list_id="popular_movies",
        media_type="movie",
        fetched_at=NOW.isoformat(),
        items=[item],
    )


def _enrichment(details_at=NOW, providers_at=NOW):
    return {
        "tmdb_full": {
            "id": 101,
            "imdb_id": "tt0000101",
            "budget": 123456,
            "runtime": 120,
            "genres": [{"id": 18, "name": "Drama"}],
            "credits": {"cast": [{"id": 1, "name": "Actor One"}]},
            "external_ids": {"imdb_id": "tt0000101"},
            "images": {"backdrops": [{"file_path": "/wide.jpg"}]},
        },
        "watch_providers": {
            "SE": {
                "link": "https://www.themoviedb.org/movie/101/watch?locale=SE",
                "flatrate": [{"provider_id": 8, "provider_name": "Netflix"}],
                "rent": [{"provider_id": 2, "provider_name": "Apple TV"}],
                "buy": [{"provider_id": 3, "provider_name": "Store"}],
                "free": [{"provider_id": 4, "provider_name": "Free service"}],
                "ads": [{"provider_id": 5, "provider_name": "Ad service"}],
            }
        },
        "tmdb_details_fetched_at": details_at.isoformat(),
        "tmdb_details_status": "fresh",
        "tmdb_watch_providers_fetched_at": providers_at.isoformat(),
        "tmdb_watch_providers_status": "fresh",
    }


def test_full_metadata_is_in_one_detail_document_and_rows_are_slim():
    item = {"id": 101, "title": "Example Film", "release_date": "2024-01-01"}
    item["tmdb_enrichment"] = _enrichment()
    snapshot = _snapshot(item)
    shelf = {
        "id": "netflix:movie",
        "service_key": "netflix",
        "provider_id": 8,
        "provider_name": "Netflix",
        "provider_logo": "https://image.tmdb.org/t/p/w92/netflix.png",
        "media_kind": "movie",
        "title": "Top 10 on Netflix",
        "display_mode": "top_10",
        "availability_updated_at": NOW.isoformat(),
        "items": [{
            "id": "movie:tmdb:101",
            "tmdb_id": "101",
            "media_kind": "movie",
            "title": "Example Film",
            "year": "2024",
            "images": {"poster": "https://image.tmdb.org/t/p/w500/p.jpg"},
            "popularity": 80,
            "rating": 8.1,
            "vote_count": 120,
            "rank": 1,
        }],
    }
    release = build_release(
        [{"id": "popular-movies", "name": "Popular movies", "type": "movie",
          "source_lists": ["popular_movies"]}],
        [snapshot],
        NOW,
        watch_regions=[{"iso_code": "SE", "english_name": "Sweden",
                        "availability_updated_at": NOW.isoformat()}],
        provider_shelves={"SE": [shelf]},
        item_enrichments={("movie", "101"): item["tmdb_enrichment"]},
    )
    row_item = release["rows"][0]["items"][0]
    assert row_item["id"] == "movie:tmdb:101"
    assert row_item["ids"] == {"tmdb": "101", "imdb": "tt0000101"}
    assert row_item["details_path"].endswith(".json")
    assert "tmdb_full" not in row_item
    assert "watch_providers" not in row_item
    assert "tmdb_watch_providers_response" not in row_item

    detail = release["item_details"][row_item["details_path"]]
    assert detail["tmdb_full"]["budget"] == 123456
    assert detail["tmdb_full"]["credits"]["cast"][0]["name"] == "Actor One"
    assert detail["watch_providers"]["SE"]["flatrate"][0]["provider_name"] == "Netflix"
    assert detail["watch_providers"]["SE"]["rent"][0]["provider_name"] == "Apple TV"
    assert detail["watch_providers"]["SE"]["buy"][0]["provider_name"] == "Store"
    assert detail["watch_providers"]["SE"]["free"][0]["provider_name"] == "Free service"
    assert detail["watch_providers"]["SE"]["ads"][0]["provider_name"] == "Ad service"

    published_shelf_item = release["provider_shelves"][0]["shelves"][0]["items"][0]
    assert published_shelf_item["details_path"] == row_item["details_path"]
    assert published_shelf_item["rank"] == 1
    assert release["watch_regions"][0]["provider_shelves_path"].endswith("SE.json")


def test_details_refresh_and_availability_refresh_have_independent_cadence(monkeypatch):
    old = _enrichment(
        details_at=NOW - timedelta(days=20),
        providers_at=NOW - timedelta(hours=13),
    )
    calls = []
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_details",
        lambda media, tmdb: calls.append(("details", media, tmdb)) or {"id": 101, "budget": 222},
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_watch_providers",
        lambda media, tmdb: calls.append(("providers", media, tmdb)) or {"SE": {"flatrate": []}},
    )

    refreshed, errors = _refresh_record(("movie", "101"), old, NOW)

    assert calls == [("providers", "movie", "101")]
    assert refreshed["tmdb_full"]["budget"] == 123456
    assert refreshed["watch_providers"]["SE"]["flatrate"] == []
    assert refreshed["tmdb_details_fetched_at"] == old["tmdb_details_fetched_at"]
    assert refreshed["tmdb_watch_providers_fetched_at"] == NOW.isoformat()
    assert errors == []


def test_details_refresh_does_not_force_availability_refresh(monkeypatch):
    old = _enrichment(
        details_at=NOW - timedelta(days=31),
        providers_at=NOW - timedelta(hours=1),
    )
    calls = []
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_details",
        lambda media, tmdb: calls.append("details") or {"id": 101, "budget": 222},
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_watch_providers",
        lambda media, tmdb: calls.append("providers") or {},
    )

    refreshed, errors = _refresh_record(("movie", "101"), old, NOW)

    assert calls == ["details"]
    assert refreshed["tmdb_full"]["budget"] == 222
    assert refreshed["watch_providers"] == old["watch_providers"]
    assert refreshed["tmdb_watch_providers_fetched_at"] == old["tmdb_watch_providers_fetched_at"]
    assert errors == []


def test_failed_refresh_retains_last_good_until_hard_cache_limit(monkeypatch):
    old = _enrichment(details_at=NOW - timedelta(days=31), providers_at=NOW - timedelta(hours=13))
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_details",
        lambda *_: (_ for _ in ()).throw(RuntimeError("temporary details outage")),
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_watch_providers",
        lambda *_: (_ for _ in ()).throw(RuntimeError("temporary provider outage")),
    )

    refreshed, errors = _refresh_record(("movie", "101"), old, NOW)

    assert refreshed["tmdb_full"]["budget"] == 123456
    assert refreshed["watch_providers"]["SE"]["rent"][0]["provider_name"] == "Apple TV"
    assert refreshed["tmdb_details_status"] == "stale"
    assert refreshed["tmdb_watch_providers_status"] == "stale"
    assert {error["stage"] for error in errors} == {"details_refresh", "availability_refresh"}


def test_metadata_older_than_hard_cache_limit_is_purged_but_ids_survive(monkeypatch):
    old = _enrichment(
        details_at=NOW - timedelta(days=151),
        providers_at=NOW - timedelta(days=151),
    )
    old["ids"] = {"tmdb": "101", "imdb": "tt0000101"}
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_details",
        lambda *_: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_watch_providers",
        lambda *_: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    refreshed, errors = _refresh_record(("movie", "101"), old, NOW)

    assert refreshed["tmdb_full"] == {}
    assert refreshed["watch_providers"] == {}
    assert refreshed["tmdb_details_status"] == "expired"
    assert refreshed["tmdb_watch_providers_status"] == "expired"
    assert refreshed["ids"] == {"tmdb": "101", "imdb": "tt0000101"}
    assert {error["stage"] for error in errors} == {
        "details_cache_expired",
        "availability_cache_expired",
    }


def test_missing_credentials_retains_last_published_region_shelf_as_stale(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._credentials",
        lambda: (None, None),
    )
    old_time = (NOW - timedelta(hours=13)).isoformat()
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_previous_region_directory",
        lambda: {"SE": {
            "english_name": "Sweden",
            "native_name": "Sverige",
            "availability_updated_at": old_time,
            "provider_shelves_path": "releases/old/provider-shelves/SE.json",
        }},
    )
    shelf = {
        "id": "netflix:movie",
        "service_key": "netflix",
        "provider_id": 8,
        "provider_name": "Netflix",
        "media_kind": "movie",
        "title": "Top 10 on Netflix",
        "display_mode": "top_10",
        "availability_updated_at": old_time,
        "items": [{
            "id": "movie:tmdb:101",
            "tmdb_id": "101",
            "media_kind": "movie",
            "title": "Cached film",
            "rank": 1,
        }],
    }
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_cached_provider_shelves",
        lambda *_: [shelf],
    )
    regions, shelves, additional, report = discover_provider_shelves(NOW)
    assert regions[0]["iso_code"] == "SE"
    assert shelves["SE"][0]["availability_status"] == "stale"
    assert ("movie", "101") in additional
    assert report["provider_catalogue_requests"] == 0


def test_missing_credentials_do_not_republish_region_shelves_beyond_hard_age(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._credentials",
        lambda: (None, None),
    )
    old_time = (NOW - timedelta(days=151)).isoformat()
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_previous_region_directory",
        lambda: {"SE": {
            "english_name": "Sweden",
            "availability_updated_at": old_time,
            "provider_shelves_path": "releases/old/provider-shelves/SE.json",
        }},
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_cached_provider_shelves",
        lambda *_: [{
            "id": "netflix:movie",
            "service_key": "netflix",
            "provider_id": 8,
            "provider_name": "Netflix",
            "media_kind": "movie",
            "title": "Top 10 on Netflix",
            "availability_updated_at": old_time,
            "items": [{"tmdb_id": "101", "title": "Expired cached title"}],
        }],
    )
    regions, shelves, additional, report = discover_provider_shelves(NOW)
    assert regions == []
    assert shelves == {}
    assert additional == {}
    assert report["provider_shelves_expired"] == 1


def test_provider_discovery_uses_allowlist_and_publishes_ranked_top_ten(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._credentials",
        lambda: ("configured-key", None),
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._watch_regions",
        lambda: [{"iso_code": "SE", "english_name": "Sweden", "native_name": "Sverige"}],
    )
    monkeypatch.setattr("src.tmdb_enrichment._load_previous_region_directory", lambda: {})
    providers = [
        {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/netflix.png", "display_priority": 1},
        {"provider_id": 384, "provider_name": "Max", "logo_path": "/max.png", "display_priority": 2},
        {"provider_id": 119, "provider_name": "Disney Plus", "logo_path": "/disney.png", "display_priority": 3},
        {"provider_id": 999, "provider_name": "Unknown service", "logo_path": "/other.png"},
    ]
    monkeypatch.setattr(
        "src.tmdb_enrichment._provider_catalogue",
        lambda region, media: providers if media == "movie" else [],
    )
    discover_calls = []

    def discover(media, region, provider_id):
        discover_calls.append((media, region, provider_id))
        count = 10 if provider_id == 8 else (4 if provider_id == 384 else 7)
        return [
            {
                "id": provider_id * 100 + rank,
                "title": f"Title {rank}",
                "release_date": "2025-01-01",
                "popularity": 100 - rank,
                "vote_average": 8.1,
                "vote_count": 20,
                "poster_path": f"/poster-{rank}.jpg",
            }
            for rank in range(1, count + 1)
        ]

    monkeypatch.setattr("src.tmdb_enrichment._discover_provider", discover)
    regions, shelves_by_region, discovered, report = discover_provider_shelves(NOW)

    shelves = shelves_by_region["SE"]
    assert [shelf["service_key"] for shelf in shelves] == ["netflix", "disney-plus"]
    netflix = shelves[0]
    assert netflix["title"] == "Top 10 on Netflix"
    assert netflix["display_mode"] == "top_10"
    assert netflix["provider_logo"].endswith("/netflix.png")
    assert [item["rank"] for item in netflix["items"]] == list(range(1, 11))
    assert shelves[1]["title"] == "Popular on Disney+"
    assert len(shelves[1]["items"]) == 7
    assert len(discovered) == 17
    assert all(service in PROVIDER_ALLOWLIST for service in
               {shelf["service_key"] for shelf in shelves})
    assert report["provider_shelves_omitted_under_minimum"] == 1
    assert report["provider_discovery_errors"] == []


def test_recent_published_provider_shelves_are_reused(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._credentials",
        lambda: ("configured-key", None),
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._watch_regions",
        lambda: [{"iso_code": "SE", "english_name": "Sweden", "native_name": "Sverige"}],
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_previous_region_directory",
        lambda: {"SE": {
            "availability_updated_at": (NOW - timedelta(hours=2)).isoformat(),
            "provider_shelves_path": "releases/previous/provider-shelves/SE.json",
        }},
    )
    cached_shelf = {
        "id": "netflix:movie",
        "service_key": "netflix",
        "provider_id": 8,
        "provider_name": "Netflix",
        "provider_logo": "https://image.tmdb.org/t/p/w92/logo.png",
        "media_kind": "movie",
        "title": "Top 10 on Netflix",
        "display_mode": "top_10",
        "availability_updated_at": (NOW - timedelta(hours=2)).isoformat(),
        "items": [{
            "id": "movie:tmdb:101",
            "tmdb_id": "101",
            "media_kind": "movie",
            "title": "Cached film",
            "rank": 1,
        }],
    }
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_cached_provider_shelves",
        lambda *_: [cached_shelf],
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._provider_catalogue",
        lambda *_: (_ for _ in ()).throw(AssertionError("provider list should be reused")),
    )
    regions, shelves, additional, report = discover_provider_shelves(NOW)
    assert shelves["SE"][0]["title"] == "Top 10 on Netflix"
    assert ("movie", "101") in additional
    assert report["provider_shelf_regions_reused"] == 1
    assert report["provider_catalogue_requests"] == 0


def test_failed_region_provider_refresh_retains_visible_stale_shelf(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._credentials",
        lambda: ("configured-key", None),
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._watch_regions",
        lambda: [{"iso_code": "SE", "english_name": "Sweden", "native_name": "Sverige"}],
    )
    old_time = (NOW - timedelta(hours=13)).isoformat()
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_previous_region_directory",
        lambda: {"SE": {
            "availability_updated_at": old_time,
            "provider_shelves_path": "releases/old/provider-shelves/SE.json",
        }},
    )
    old_shelf = {
        "id": "netflix:movie",
        "service_key": "netflix",
        "provider_id": 8,
        "provider_name": "Netflix",
        "provider_logo": "https://image.tmdb.org/t/p/w92/netflix.png",
        "media_kind": "movie",
        "title": "Top 10 on Netflix",
        "display_mode": "top_10",
        "availability_status": "fresh",
        "availability_updated_at": old_time,
        "items": [{
            "id": "movie:tmdb:101",
            "tmdb_id": "101",
            "media_kind": "movie",
            "title": "Cached film",
            "rank": 1,
        }],
    }
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_cached_provider_shelves",
        lambda *_: [old_shelf],
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._provider_catalogue",
        lambda region, media: (
            (_ for _ in ()).throw(RuntimeError("temporary provider list outage"))
            if media == "movie" else []
        ),
    )

    regions, shelves_by_region, additional, report = discover_provider_shelves(NOW)

    retained = shelves_by_region["SE"][0]
    assert retained["title"] == "Top 10 on Netflix"
    assert retained["availability_status"] == "stale"
    assert retained["availability_updated_at"] == old_time
    assert ("movie", "101") in additional
    assert regions[0]["availability_updated_at"] == old_time
    assert report["provider_discovery_errors"][0]["stage"] == "provider_catalogue"


def test_enrichment_applies_to_global_and_provider_discovery_items(monkeypatch):
    monkeypatch.setattr(
        "src.tmdb_enrichment._load_previous_item",
        lambda key, index, base: None,
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_details",
        lambda media, tmdb: {"id": int(tmdb), "external_ids": {"imdb_id": f"tt{tmdb}"}},
    )
    monkeypatch.setattr(
        "src.tmdb_enrichment._fetch_watch_providers",
        lambda media, tmdb: {"SE": {"flatrate": []}},
    )
    global_item = {"id": 101, "title": "Global"}
    discovery_item = {"id": 202, "title": "Provider discovery"}
    snapshots = [_snapshot(global_item)]
    additional = {("movie", "202"): discovery_item}

    enrichment, report = enrich_tmdb_snapshots(
        snapshots,
        additional_items=additional,
        previous_detail_index={},
        now=NOW,
    )

    assert ("movie", "101") in enrichment
    assert ("movie", "202") in enrichment
    assert global_item["tmdb_enrichment"]["tmdb_full"]["id"] == 101
    assert discovery_item["tmdb_enrichment"]["tmdb_full"]["id"] == 202
    assert global_item["id"] == 101
    assert report["unique_tmdb_titles"] == 2


def test_shelf_discovery_refresh_constants_are_distinct():
    assert DETAIL_REFRESH_AGE == timedelta(days=30)
    assert AVAILABILITY_REFRESH_AGE == timedelta(hours=12)



def test_provider_discovery_only_item_keeps_tmdb_canonical_id_and_imdb_alias():
    from src.manifest import build_release

    global_item = {"id": 101, "title": "Global title", "tmdb_enrichment": _enrichment()}
    discovered_item = {
        "id": 202,
        "tmdb_id": "202",
        "media_type": "movie",
        "media_kind": "movie",
        "title": "Provider-only title",
        "year": "2025",
        "tmdb_enrichment": {
            "tmdb_full": {
                "id": 202,
                "external_ids": {"imdb_id": "tt0000202"},
                "overview": "Full discovered metadata",
            },
            "watch_providers": {
                "SE": {
                    "flatrate": [{"provider_id": 8, "provider_name": "Netflix"}],
                    "rent": [],
                },
            },
            "tmdb_details_fetched_at": NOW.isoformat(),
            "tmdb_details_status": "fresh",
            "tmdb_watch_providers_fetched_at": NOW.isoformat(),
            "tmdb_watch_providers_status": "fresh",
        },
    }
    shelf = {
        "id": "netflix:movie",
        "service_key": "netflix",
        "provider_id": 8,
        "provider_name": "Netflix",
        "provider_logo": "https://image.tmdb.org/t/p/w92/netflix.png",
        "media_kind": "movie",
        "title": "Popular on Netflix",
        "display_mode": "popular",
        "availability_updated_at": NOW.isoformat(),
        "items": [{
            "id": "movie:tmdb:202",
            "tmdb_id": "202",
            "media_kind": "movie",
            "title": "Provider-only title",
            "rank": 1,
        }],
    }

    release = build_release(
        [{"id": "popular-movies", "name": "Popular", "type": "movie",
          "source_lists": ["popular_movies"]}],
        [_snapshot(global_item)],
        NOW,
        watch_regions=[{"iso_code": "SE", "english_name": "Sweden"}],
        provider_shelves={"SE": [shelf]},
        item_enrichments={("movie", "202"): discovered_item["tmdb_enrichment"]},
    )

    shelf_item = release["provider_shelves"][0]["shelves"][0]["items"][0]
    detail = release["item_details"][shelf_item["details_path"]]
    assert shelf_item["id"] == "movie:tmdb:202"
    assert shelf_item["ids"] == {"tmdb": "202", "imdb": "tt0000202"}
    assert detail["id"] == "movie:tmdb:202"
    assert detail["ids"] == {"tmdb": "202", "imdb": "tt0000202"}
