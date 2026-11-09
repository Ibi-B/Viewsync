import json
from pathlib import Path
from types import SimpleNamespace

import main
from fetch import fetch_source


def test_build_catalog_includes_new_rows():
    rows = [
        {
            "id": "popular-movies",
            "name": "Popular Movies",
            "type": "movie",
            "source_lists": ["popular_movies"],
            "extra": [],
            "date_field": None,
            "date_mode": "none",
        },
        {
            "id": "new-movies",
            "name": "New Movies",
            "type": "movie",
            "source_lists": ["new_movies"],
            "extra": [],
            "date_field": "release_date",
            "date_mode": "recent",
        },
        {
            "id": "upcoming-movies",
            "name": "Upcoming Movies",
            "type": "movie",
            "source_lists": ["upcoming_movies"],
            "extra": [],
            "date_field": "release_date",
            "date_mode": "future",
        },
    ]

    catalog = main.build_catalog(
        rows,
        now=SimpleNamespace(date=lambda: __import__('datetime').date(2026, 11, 9)),
    )

    ids = [row["id"] for row in catalog["metas"]]
    assert ids == ["popular-movies", "new-movies", "upcoming-movies"]


def test_fetch_source_uses_provider_config():
    request = {
        "id": "popular_movies",
        "type": "movie",
        "providers": {
            "tmdb": {
                "list_id": "popular_movies",
                "media_type": "movie",
                "max_items": 10,
            }
        },
    }

    items = fetch_source(request, "tmdb")
    assert len(items) <= 10
