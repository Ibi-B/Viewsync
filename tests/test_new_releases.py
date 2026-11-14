from src.config import load_config
from src.fetch import fetch_source


def _load_rows():
    return load_config("catalog-config")["rows"]["rows"]


def test_new_movies_row_is_configured():
    config = _load_rows()

    row = next(row for row in config if row["id"] == "new-movies")

    assert row["source_lists"] == ["new_movies"]
    assert row["date_field"] == "release_date"
    assert row["date_mode"] == "recent"


def test_new_series_row_is_configured():
    config = _load_rows()

    row = next(row for row in config if row["id"] == "new-series")

    assert row["source_lists"] == ["new_series"]
    assert row["date_field"] == "first_air_date"
    assert row["date_mode"] == "recent"


def test_upcoming_movies_row_is_configured():
    config = _load_rows()

    row = next(row for row in config if row["id"] == "upcoming-movies")

    assert row["source_lists"] == ["upcoming_movies"]
    assert row["date_field"] == "release_date"
    assert row["date_mode"] == "future"


def test_upcoming_series_row_is_configured():
    config = _load_rows()

    row = next(row for row in config if row["id"] == "upcoming-series")

    assert row["source_lists"] == ["upcoming_series"]
    assert row["date_field"] == "first_air_date"
    assert row["date_mode"] == "future"


def test_fetch_source_supports_date_windows(monkeypatch):
    request = {
        "id": "new_movies",
        "type": "movie",
        "providers": {
            "tmdb": {
                "list_id": "new_movies",
                "media_type": "movie",
                "max_items": 10,
                "date_mode": "recent",
            }
        },
    }

    monkeypatch.setenv("TMDB_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "src.fetch._get_json",
        lambda url, params=None: {"results": []},
    )

    items = fetch_source(request, "tmdb")

    assert isinstance(items, list)
