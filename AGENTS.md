# Repository Agent Instructions

### taplctl Testing After Changes

- After implementing or modifying `taplctl` behavior in this repository, test it by invoking the current checkout directly. Do not rely on a globally installed `taplctl`.
- Prefer `tapl/.venv/bin/taplctl` from the repository root for CLI behavior checks.
- Always pass an isolated database path, for example `--db /private/tmp/tapl-test.db`, so tests do not touch the repo-local or user TAPL state.
- When config-dependent behavior matters, pass an isolated config file with `--config /private/tmp/tapl-test.toml`.
- For Python test runs, prefer the repository environment, for example `tapl/.venv/bin/python -m pytest tapl/tests/test_tapl.py`. If `uv` is needed, keep its cache isolated with `UV_CACHE_DIR=/private/tmp/uv-cache`.
