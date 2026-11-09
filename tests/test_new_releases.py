import json
from pathlib import Path

from datetime import date

from src.fetch import date_window


def test_new_movies_row_is_configured():
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
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    row = next(row for row in config["rows"] if row["id"] == "upcoming-series")

    assert row["source_lists"] == ["upcoming_series"]
    assert row["date_field"] == "first_air_date"
    assert row["date_mode"] == "future"


def test_date_windows_use_the_provider_media_date_field():
    today = date(2026, 11, 9)
    expected_fields = {"movie": "release_date", "series": "first_air_date"}

    for media_type, date_field in expected_fields.items():
        recent_field, recent_start, recent_end, recent_order = date_window(
            "recent", today, media_type
        )
        future_field, future_start, future_end, future_order = date_window(
            "future", today, media_type
        )

        assert recent_field == date_field
        assert recent_start == date(2026, 10, 10)
        assert recent_end == today
        assert future_field == date_field
        assert future_start == today
        assert future_end == date(2027, 5, 8)
        assert recent_order.endswith(".desc")
        assert future_order.endswith(".asc")


def test_date_window_rejects_unknown_media_type():
    try:
        date_window("recent", date(2026, 11, 9), "episode")
    except ValueError as error:
        assert "Unsupported media type" in str(error)
    else:
        raise AssertionError("unsupported media type must be rejected")
