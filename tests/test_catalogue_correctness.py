from src.config import load_config


def test_catalog_row_order_matches_spec():
    config = load_config("catalog-config")

    ids = [row["id"] for row in config["rows"]["rows"]]

    assert ids == [
        "popular-movies",
        "popular-series",
        "new-movies",
        "new-series",
        "upcoming-movies",
        "upcoming-series",
    ]


def test_catalog_row_types_match_source_lists():
    config = load_config("catalog-config")

    for row in config["rows"]["rows"]:
        if row["id"] in {"popular-movies", "new-movies", "upcoming-movies"}:
            assert row["type"] == "movie"

        if row["id"] in {"popular-series", "new-series", "upcoming-series"}:
            assert row["type"] == "series"


def test_catalog_source_lists_match_provider_requests():
    config = load_config("catalog-config")

    request_ids = {
        request["id"]
        for provider in config["sources"]["providers"]
        for request in provider.get("requests", [])
    }

    for row in config["rows"]["rows"]:
        for source_id in row["source_lists"]:
            assert source_id in request_ids


def test_catalog_date_modes_are_consistent():
    config = load_config("catalog-config")

    for row in config["rows"]["rows"]:
        if row["id"] in {"new-movies", "new-series"}:
            assert row["date_mode"] == "recent"

        if row["id"] in {"upcoming-movies", "upcoming-series"}:
            assert row["date_mode"] == "future"

        if row["id"] in {"popular-movies", "popular-series"}:
            assert row["date_mode"] == "none"
