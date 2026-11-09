# Catalogue URL contract

Fetch `<catalogue-base>/v1/manifest.json` as the stable entry point.

The stable and release-specific manifests contain identical JSON. `path_base: v1-root` means all `path`, `manifest_path`, and `details_path` values resolve against `<catalogue-base>/v1/`, including when reading a release-specific manifest. Never resolve them against the release directory. Paths use forward slashes and preserve the project prefix, such as `/Viewsync/`.

Read each row using its manifest `path`. Read each item detail using `details_path`. Write release files first and the stable manifest last. The manifest is updated using a temporary file replacement.

For Home cards, each item's `metadata` may include `rating` (the preferred valid score on a 0–10 scale), `rating_source` (`imdb` or `tmdb`), and `ratings` (provider-specific values and scales). These fields are optional: display a score only when supplied and valid; never infer or invent a rating. The primary rating prefers IMDb when present, then TMDB. TMDB's `vote_average` and IMDb/Cinemeta's `imdbRating` are normalized into this shape.

The stable entry point is `<catalogue-base>/v1/manifest.json`; resolve its row paths against `<catalogue-base>/v1/`. For the GitHub Pages project site, verify the live page URL and project prefix from the deployment result before configuring BeastED. Run generation/deployment only after required GitHub Pages settings and credentials have been configured. A successful commit alone does not publish these files.
