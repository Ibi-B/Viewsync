from datetime import datetime, timezone

from src.fetch import SourceSnapshot
from src.manifest import build_release
from src.tmdb_enrichment import enrich_tmdb_snapshots


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


def test_tmdb_detail_and_all_region_provider_payloads_are_published(monkeypatch):
    def fake_request(path, params=None):
        if path == "configuration/countries":
            return [
                {"iso_3166_1": "SE", "english_name": "Sweden", "native_name": "Sverige"},
                {"iso_3166_1": "US", "english_name": "United States", "native_name": "United States"},
            ]
        if path == "movie/101":
            return {
                "id": 101,
                "imdb_id": "tt0000101",
                "budget": 123456,
                "runtime": 120,
                "genres": [{"id": 18, "name": "Drama"}],
                "credits": {"cast": [{"id": 1, "name": "Actor One"}]},
                "external_ids": {"imdb_id": "tt0000101"},
                "images": {"backdrops": [{"file_path": "/wide.jpg"}]},
            }
        if path == "movie/101/watch/providers":
            return {"id": 101, "results": {
                "SE": {"link": "https://www.themoviedb.org/movie/101/watch?locale=SE",
                       "flatrate": [{"provider_id": 8, "provider_name": "Netflix"}],
                       "rent": [{"provider_id": 2, "provider_name": "Apple TV"}]},
                "US": {"flatrate": [{"provider_id": 9, "provider_name": "Other"}]},
            }}
        raise AssertionError(path)

    monkeypatch.setattr("src.tmdb_enrichment._request_json", fake_request)
    monkeypatch.setattr("src.tmdb_enrichment._credentials", lambda: ("configured-key", None))
    item = {"id": 101, "title": "Example Film", "release_date": "2024-01-01"}
    snapshots = [_snapshot(item)]

    regions, report = enrich_tmdb_snapshots(snapshots, NOW)

    assert [row["iso_code"] for row in regions] == ["SE", "US"]
    assert report["detail_titles_refreshed"] == 1
    assert item["tmdb_enrichment"]["details"]["budget"] == 123456
    assert item["tmdb_enrichment"]["watch_providers"]["SE"]["flatrate"][0]["provider_id"] == 8
    assert item["tmdb_enrichment"]["watch_providers"]["SE"]["rent"][0]["provider_name"] == "Apple TV"

    release = build_release(
        [{"id": "popular-movies", "name": "Popular movies", "type": "movie",
          "source_lists": ["popular_movies"]}],
        snapshots,
        NOW,
        watch_regions=regions,
    )
    published = release["rows"][0]["items"][0]
    assert published["tmdb_full"]["budget"] == 123456
    assert published["tmdb_full"]["credits"]["cast"][0]["name"] == "Actor One"
    assert published["ids"]["imdb"] == "tt0000101"
    assert published["id"] == "movie:imdb:tt0000101"
    assert published["watch_providers"]["SE"]["flatrate"][0]["provider_name"] == "Netflix"
    assert release["watch_regions"][0]["english_name"] == "Sweden"
    assert published["metadata"]["runtime_minutes"] == 120


def test_recent_tmdb_enrichment_cache_is_reused_without_requests(monkeypatch):
    monkeypatch.setattr("src.tmdb_enrichment._credentials", lambda: (None, None))
    monkeypatch.setattr(
        "src.tmdb_enrichment._request_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("request should not run")),
    )
    cached = {
        "fetched_at": NOW.isoformat(),
        "status": "fresh",
        "details": {"id": 202, "budget": 999},
        "watch_providers": {"SE": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]}},
    }
    item = {"id": 202, "title": "Cached", "tmdb_enrichment": cached}
    regions, report = enrich_tmdb_snapshots([_snapshot(item)], NOW)
    assert item["tmdb_enrichment"] == cached
    assert report["cached_titles_reused"] == 1
    assert regions == []


def test_failed_refresh_keeps_previous_tmdb_metadata_instead_of_erasing_it(monkeypatch):
    monkeypatch.setattr("src.tmdb_enrichment._credentials", lambda: ("configured-key", None))
    monkeypatch.setattr(
        "src.tmdb_enrichment._request_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("temporary upstream failure")),
    )
    cached = {
        "fetched_at": "2026-10-01T00:00:00+00:00",
        "status": "fresh",
        "details": {"id": 303, "budget": 456},
        "watch_providers": {"SE": {"flatrate": [{"provider_id": 8, "provider_name": "Netflix"}]}},
    }
    item = {"id": 303, "title": "Retained", "tmdb_enrichment": cached}
    enrich_tmdb_snapshots([_snapshot(item)], NOW)
    assert item["tmdb_enrichment"]["details"]["budget"] == 456
    assert item["tmdb_enrichment"]["watch_providers"]["SE"]["flatrate"][0]["provider_name"] == "Netflix"
    assert item["tmdb_enrichment"]["status"] == "stale"
