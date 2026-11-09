from types import SimpleNamespace

import main


def test_build_catalog_includes_new_rows(monkeypatch):
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

    monkeypatch.setattr(
        "src.main.fetch_source",
        lambda request, provider, today=None: [
            {"id": 1, "title": "Example"}
        ],
    )

    catalog = main.build_catalog(
        rows,
        now=SimpleNamespace(date=lambda: __import__('datetime').date(2026, 11, 9)),
    )

    ids = [row["id"] for row in catalog["metas"]]
    assert ids == ["popular-movies", "new-movies", "upcoming-movies"]