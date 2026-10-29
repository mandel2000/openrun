# Contributing to OpenRun

Thanks for helping! Bug reports, training-science corrections, translations and code are all welcome. You can also support the project on [Ko-fi](https://ko-fi.com/manueldelgado54792).

## Before you start

- **Bugs and ideas**: open an [issue](https://github.com/mandel2000/openrun/issues) first, using the templates. For anything bigger than a small fix, agree on the approach in the issue before writing code.
- **Training rules** must cite a source (paper, book or recognised coaching method) in the code's docstring and in [docs/science.md](docs/science.md). "It works for me" is not enough: these rules shape other people's training.
- **Security problems**: never in a public issue. See [SECURITY.md](SECURITY.md).
- Be kind: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Development setup

Requirements: Python ≥ 3.12, Node ≥ 20.

```bash
git clone https://github.com/<you>/openrun.git && cd openrun
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
cd frontend && npm ci && cd ..
```

Run it with hot reload:

```bash
cd backend && OPENRUN_DB=/tmp/openrun-dev.db .venv/bin/uvicorn app.main:app --reload   # API on :8000
cd frontend && npm run dev                                                              # UI on :5173, proxies /api
```

Use a throwaway database (`OPENRUN_DB`) and `OPENRUN_SCHEDULER=0` if you don't want the daily routine to touch a real Garmin account.

Checks (CI runs the same on every pull request):

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/python -m pytest -q
cd frontend && npm run lint && npm run i18n:check && npm run build
```

## Workflow

OpenRun uses **GitHub Flow**: `main` is always releasable and deployable; all work happens in short-lived branches merged through pull requests.

1. Branch from an up-to-date `main`, named after the change type:
   `feat/readiness-score`, `fix/duplicate-tool`, `docs/mcp-guide`, `chore/lint`, `refactor/…`, `test/…`.
2. Keep each pull request to **one** change. Rebase on `main` instead of merging it into your branch.
3. Add or update tests for behaviour changes; update the docs (English, and Spanish when you can) for anything user-visible.
4. Open the pull request with the template filled in. CI must pass.
5. Pull requests are **squash-merged**: the PR title becomes the commit on `main`, so it must follow the commit convention below. The branch is deleted after merging.

### Commit messages

[Conventional Commits](https://www.conventionalcommits.org):

```
<type>(<optional scope>): <summary in the imperative, ≤ 72 chars>

<body: what and why, wrapped at ~72 columns>
```

Types: `feat` (user-visible feature), `fix` (bug fix), `docs`, `refactor` (no behaviour change), `perf`, `test`, `build` (Docker, dependencies), `ci`, `chore`. Common scopes: `coach`, `mcp`, `plan`, `readiness`, `races`, `garmin`, `import`, `ui`, `auth`. Breaking changes add `!` (`feat(api)!: …`) and a `BREAKING CHANGE:` footer.

Examples from the history:

```
feat(races): race-day strategy with per-km pacing on the course profile
fix(coach): get_readiness was declared twice
chore(lint): ruff for the backend, lint both sides in CI
```

### Code style

- Python: `ruff` (config in `backend/pyproject.toml`), type hints, docstrings that explain *why* (and cite sources for training rules). Business logic goes in `services.py` / `training/`, not in endpoints.
- TypeScript/React: `eslint` (config in `frontend/eslint.config.js`), function components, design tokens from `index.css` (no hard-coded colours), layouts that work at phone width.
- Match the comment density and naming of the surrounding code.
- Every user-facing string is written in English and wrapped for translation (see below).

### Translations

Text is written in English in the code and looked up per language, gettext style. The English sentence is the key, so code stays readable and a missing translation falls back to English.

- **Frontend**: `t('Add run')`, with placeholders `t('{n} days to go', { n })`. Translations live in `frontend/src/locales/es.ts`. `npm run i18n:check` (also in CI) lists strings without a translation and unused entries.
- **Backend** (workout titles, notifications, errors, analysis): `_("Easy run {km} km", km=…)` from `app/i18n.py`; module-level constants are marked with `N_()` and translated when used. Translations live in `backend/app/locales/es.py`; a test fails if one is missing or its placeholders differ.
- The language comes from the user's setting (*Settings › Appearance and language*), else the browser, else `OPENRUN_LANG`. Text stored in the database (a workout title) keeps the language it was created in.
- The AI coach's prompts are in English and ask the model to answer in the user's language.
- **New language**: add its code to `LANGS` in `frontend/src/i18n.ts` and `app/i18n.py`, then create `locales/<code>.ts` and `locales/<code>.py` by copying the Spanish files. Native speakers who know running vocabulary make the best translations.

## Releases

Maintainers release from `main`:

1. Move the `Unreleased` items in [CHANGELOG.md](CHANGELOG.md) under a new version and date ([Semantic Versioning](https://semver.org): new features → minor, fixes → patch, breaking changes → major; `0.x` while the API settles).
2. Bump `version` in `backend/pyproject.toml` and `frontend/package.json`; commit as `chore(release): vX.Y.Z` through a pull request.
3. Tag the merge commit `vX.Y.Z` and push the tag. The release workflow publishes `ghcr.io/mandel2000/openrun:X.Y.Z` (amd64/arm64) and the GitHub release with that changelog section.

## License

By contributing you agree that your contribution is licensed under the [AGPL-3.0](LICENSE), like the rest of the project.
