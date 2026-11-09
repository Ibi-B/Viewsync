import json
from pathlib import Path


def test_catalog_row_order_matches_spec():
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    ids = [row["id"] for row in config["rows"]]

    assert ids == [
        "popular-movies",
        "popular-series",
        "new-movies",
        "new-series",
        "upcoming-movies",
        "upcoming-series",
    ]


def test_catalog_row_types_match_source_lists():
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    for row in config["rows"]:
        if row["id"] in {"popular-movies", "new-movies", "upcoming-movies"}:
            assert row["type"] == "movie"

        if row["id"] in {"popular-series", "new-series", "upcoming-series"}:
            assert row["type"] == "series"


def test_catalog_source_lists_match_provider_requests():
    sources = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "sources.json").read_text(
            encoding="utf-8"
        )
    )

    requests = sources["providers"]["tmdb"]["requests"]

    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    for row in config["rows"]:
        for source_id in row["source_lists"]:
            assert source_id in requests


def test_catalog_date_modes_are_consistent():
    config = json.loads(
        (Path(__file__).resolve().parents[1] / "catalog-config" / "rows.json").read_text(
            encoding="utf-8"
        )
    )

    for row in config["rows"]:
        if row["id"] in {"new-movies", "new-series"}:
            assert row["date_mode"] == "recent"

        if row["id"] in {"upcoming-movies", "upcoming-series"}:
            assert row["date_mode"] == "future"

        if row["id"] in {"popular-movies", "popular-series"}:
            assert row["date_mode"] == "none"
