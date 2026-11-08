# Catalogue URL contract

Fetch `<catalogue-base>/v1/manifest.json` as the stable entry point.

The stable and release-specific manifests contain identical JSON. `path_base: v1-root` means all `path`, `manifest_path`, and `details_path` values resolve against `<catalogue-base>/v1/`, including when reading a release-specific manifest. Never resolve them against the release directory. Paths use forward slashes and preserve the project prefix, such as `/Viewsync/`.

Read each row using its manifest `path`. Read each item detail using `details_path`. Write release files first and the stable manifest last. The manifest is updated using a temporary file replacement.

Run the generation/deployment workflow after this change. A successful commit alone does not publish these files.
