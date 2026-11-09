import fetch


def test_new_movies_row_is_configured():
    import json
    from pathlib import Path

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    row = next(row for row in config["rows"] if row["id"] == "new-movies")

    assert row["source_lists"] == ["new_movies"]
    assert row["date_field"] == "release_date"
    assert row["date_mode"] == "recent"


def test_new_series_row_is_configured():
    import json
    from pathlib import Path

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    row = next(row for row in config["rows"] if row["id"] == "new-series")

    assert row["source_lists"] == ["new_series"]
    assert row["date_field"] == "first_air_date"
    assert row["date_mode"] == "recent"


def test_upcoming_movies_row_is_configured():
    import json
    from pathlib import Path

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    row = next(row for row in config["rows"] if row["id"] == "upcoming-movies")

    assert row["source_lists"] == ["upcoming_movies"]
    assert row["date_field"] == "release_date"
    assert row["date_mode"] == "future"


def test_upcoming_series_row_is_configured():
    import json
    from pathlib import Path

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    row = next(row for row in config["rows"] if row["id"] == "upcoming-series")

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

    payload = {
        "results": [
            {"id": index, "title": f"Example {index}"}
            for index in range(10)
        ]
    }

    monkeypatch.setattr(
        "src.fetch._get_json",
        lambda url, params=None, headers=None: payload,
    )

    items = fetch.fetch_source(request, "tmdb")

    assert len(items) == 10
    assert items[0]["tmdb_id"] == "0"