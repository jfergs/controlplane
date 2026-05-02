# ControlPlane Backlog

Project-local backlog for ControlPlane. Keep implementation details here and
promote only active priorities to any external tracker.

## Top Priority

- Harden dashboard session secrets.
  - Problem: dashboard session cookies are signed with
    `CONTROLPLANE_SESSION_SECRET`, but the app and compose file currently allow
    the default `change-me` value.
  - Risk: deployments that keep the default secret can have forgeable dashboard
    sessions.
  - Acceptance criteria:
    - Require a non-empty, non-default `CONTROLPLANE_SESSION_SECRET` before
      issuing or accepting dashboard sessions.
    - Update Docker Compose defaults so insecure secrets are not silently used.
    - Keep API-only routes usable when dashboard credentials are not configured,
      but fail closed for dashboard session authentication.
    - Add tests for missing, default, and valid session secrets.
  - Validation commands:
    - `.venv/bin/pytest`
    - `ruff check .`
    - `python -m py_compile controlplane_server/app/*.py controlplane_cli/*.py tests/*.py`

- Prevent stored XSS in the dashboard.
  - Problem: endpoint data accepted by `POST /api/push-status` is rendered into
    dashboard HTML with template strings and `innerHTML`.
  - Risk: a compromised endpoint token can store HTML or JavaScript that runs
    when an authenticated dashboard user opens the page.
  - Acceptance criteria:
    - Escape all endpoint-controlled values before rendering them as HTML.
    - Prefer DOM text nodes for dynamic values where practical.
    - Keep intentional static SVG/icon markup separate from endpoint data.
    - Add tests or browser-level checks covering hostile endpoint fields such as
      host, endpoint ID, OS, Wi-Fi SSID, and warnings.
  - Validation commands:
    - `.venv/bin/pytest`
    - `ruff check .`

- Fix endpoint health route ordering.
  - Problem: `/api/endpoints/{endpoint_id}` is registered before
    `/api/endpoints/health`, so `GET /api/endpoints/health` is treated as a
    lookup for endpoint ID `health` and returns 404.
  - Acceptance criteria:
    - `GET /api/endpoints/health` returns an `EndpointHealth` response.
    - Dynamic endpoint lookups still work for normal endpoint IDs.
    - Add a regression test for the health route.
  - Validation commands:
    - `.venv/bin/pytest`

- Make dashboard credential storage persistent and configurable.
  - Problem: dashboard credentials are stored in relative
    `.controlplane_login.json`, while Docker Compose only persists `/data`.
  - Risk: container recreation can lose dashboard credentials even when endpoint
    state persists.
  - Acceptance criteria:
    - Add `CONTROLPLANE_CREDS_PATH` or equivalent.
    - Default Docker Compose credential storage to `/data/.controlplane_login.json`.
    - Preserve a sane local-development default.
    - Update README deployment notes.
    - Add tests for configured credential path behavior.
  - Validation commands:
    - `.venv/bin/pytest`
    - `ruff check .`

## Reliability And Operations

- Add coverage for dashboard session and CSRF behavior.
  - Acceptance criteria:
    - Login setup creates credentials and session cookies.
    - Login rejects invalid credentials.
    - Session-auth dashboard APIs reject missing or invalid sessions.
    - Destructive dashboard APIs reject missing or invalid CSRF tokens.

- Improve route and API regression coverage.
  - Acceptance criteria:
    - Cover `/api/push-status`, endpoint list/detail/delete, and endpoint health.
    - Cover retention cleanup using a temporary database.
    - Cover dashboard proxy routes separately from bearer-token API routes.

- Review dashboard JavaScript duplication.
  - Problem: `renderTile` is defined twice in `routes.py`, which makes future UI
    changes easy to apply to the wrong version.
  - Acceptance criteria:
    - Keep one canonical `renderTile` implementation.
    - Preserve current tile/list behavior.
    - Verify dashboard still renders local host and pushed endpoints.

- Consider moving dashboard HTML/JavaScript into templates/static assets.
  - Goal: make security review, escaping, linting, and UI iteration easier.
  - Acceptance criteria:
    - Preserve existing routes and dashboard behavior.
    - Serve static JavaScript with no bearer token embedded by default.
    - Keep tests focused on rendered page availability and API behavior.

## Documentation

- Document secure deployment requirements.
  - Acceptance criteria:
    - README makes `CONTROLPLANE_SESSION_SECRET` mandatory for dashboard use.
    - README documents credential path persistence.
    - README notes that endpoint tokens can push dashboard-visible data and
      should be treated as sensitive.

## Completed

- Baseline review completed.
  - Current state at review time:
    - Git worktree was clean.
    - `.venv/bin/pytest` passed with 6 tests.
    - `ruff check .` passed.
    - `python -m py_compile controlplane_server/app/*.py controlplane_cli/*.py tests/*.py` passed.
    - System `pytest` was not installed on PATH; the project venv was used.
