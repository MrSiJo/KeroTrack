# GHCR image publishing + release-please

**Status:** Draft
**Date:** 2026-05-09
**Reference implementation:** [`C:/code/plugtrack`](file:///C:/code/plugtrack) — `.github/workflows/{build-images,release-please}.yml`, `release-please-config.json`, `compose.yaml`, `compose-dev.yaml`

## Context

KeroTrack v2 has two Dockerfiles (`backend/Dockerfile`, `frontend/Dockerfile`) and a single `compose.yaml` that builds both locally on every deploy. The deploy ritual in `CLAUDE.md` is `commit → push → docker compose up on the deploy host → curl /api/health`, which means every deploy currently requires a source checkout on the host and a full local build.

The sibling project **PlugTrack** publishes pre-built multi-arch images to GitHub Container Registry (GHCR) and uses `release-please` to drive Conventional-Commits-based semver releases. Its production `compose.yaml` pulls from GHCR; a separate `compose-dev.yaml` keeps the local-build path for source checkouts. KeroTrack should adopt the same shape so deploys become `docker compose pull && docker compose up -d` with no source on the host.

The frontend's nginx (`frontend/nginx-frontend.conf`) already reverse-proxies `/api/` to `backend:9176` on the docker bridge network, and the SvelteKit client (`frontend/src/lib/api.ts`) already uses relative URLs — so the published frontend image is self-contained as long as the backend service stays named `backend` in any compose file that consumes it.

## Decision

KeroTrack v2 adopts the PlugTrack publishing pattern with two simplifications:
1. **amd64 only** (no QEMU/arm64 build — the deploy target is x86_64; multi-arch can be added later by extending `platforms:` in the build-push step).
2. **Personal-deploy bind mounts via `compose.override.yaml`**, not in the public `compose.yaml`. The repo's `compose.yaml` uses Docker-managed named volumes; the deploy host's local override re-binds those names to `/dockerdata/kerotrack/{data,logs}`.

### Image identity

Two images, both under the GHCR namespace of the repository owner:

- `ghcr.io/mrsijo/kerotrack-api` — built from `./backend`
- `ghcr.io/mrsijo/kerotrack-ui` — built from `./frontend`

Names match the `container_name` values already in `compose.yaml` and mirror PlugTrack's `plugtrack-api` / `plugtrack-ui` shape.

After the first successful workflow run, both packages must be set to **public** under <https://github.com/MrSiJo?tab=packages>; the workflow file carries this reminder in its header comment.

## Components

### `.github/workflows/build-images.yml`

Single workflow, 2-image matrix.

**Triggers:**
- `push` to `main` — paths-ignore for `**/*.md`, `LICENSE`, `.gitignore`, `.pre-commit-config.yaml`, `.release-please-manifest.json`, `release-please-config.json`
- `push` of tag `v*.*.*` — produces semver image tags
- `pull_request` against `main` (paths: `backend/**`, `frontend/**`, `.github/workflows/build-images.yml`) — builds without pushing, verifies Dockerfiles still compile
- `workflow_dispatch` — manual trigger; tagging follows the ref it runs against

**Permissions:** `contents: read`, `packages: write`

**Concurrency:** group `build-${{ github.ref }}`, cancel in progress (so a second push to the same branch supersedes the first run).

**Job matrix:**

```yaml
matrix:
  image:
    - { name: kerotrack-api, context: ./backend,  dockerfile: ./backend/Dockerfile }
    - { name: kerotrack-ui,  context: ./frontend, dockerfile: ./frontend/Dockerfile }
```

**Steps per matrix entry:**
1. `actions/checkout@v6`
2. `docker/setup-buildx-action@v4` (no QEMU — amd64 only)
3. `docker/login-action@v4` against `ghcr.io`, only when `github.event_name != 'pull_request'`, using `secrets.GITHUB_TOKEN`
4. `docker/metadata-action@v6` to compute tags:
   - `type=ref,event=branch`
   - `type=ref,event=pr`
   - `type=semver,pattern={{version}}`
   - `type=semver,pattern={{major}}.{{minor}}`
   - `type=semver,pattern={{major}}`
   - `type=sha,prefix=sha-,format=short`
   - `type=raw,value=latest,enable=${{ github.ref == format('refs/heads/{0}', github.event.repository.default_branch) }}`
5. `docker/build-push-action@v7`:
   - `platforms: linux/amd64`
   - `push: ${{ github.event_name != 'pull_request' }}`
   - tags + labels from metadata step
   - `cache-from: type=gha,scope=${{ matrix.image.name }}`, `cache-to: type=gha,scope=${{ matrix.image.name }},mode=max`
   - `provenance: false`

### `.github/workflows/release-please.yml`

Single job running `googleapis/release-please-action@v5` on push to `main` and on `workflow_dispatch`.

**Permissions:** `contents: write`, `pull-requests: write`

**Concurrency:** group `release-${{ github.ref }}`, do **not** cancel in progress (releases must complete cleanly).

**Behaviour:** opens (and keeps updated) a `chore(main): release X.Y.Z` PR. Merging that PR creates the git tag `vX.Y.Z`, publishes a GitHub Release with auto-generated notes, and updates `CHANGELOG.md` + `.release-please-manifest.json`. The new tag triggers `build-images.yml`, which publishes versioned images.

### `release-please-config.json`

```json
{
  "$schema": "https://raw.githubusercontent.com/googleapis/release-please/main/schemas/config.json",
  "include-v-in-tag": true,
  "bump-minor-pre-major": false,
  "bump-patch-for-minor-pre-major": false,
  "draft": false,
  "prerelease": false,
  "packages": {
    ".": {
      "release-type": "simple",
      "component": "",
      "include-component-in-tag": false,
      "changelog-path": "CHANGELOG.md",
      "extra-files": []
    }
  }
}
```

### `.release-please-manifest.json`

```json
{
  ".": "0.0.0"
}
```

Manifest baseline `0.0.0`. release-please's first run will scan commits since repo inception and propose the **first release as `v0.1.0`** (assuming at least one `feat:` since the start — your history qualifies). After that, normal Conventional Commits semantics apply: `feat:` → minor, `fix:` → patch, `feat!:`/`BREAKING CHANGE:` → major.

### `CHANGELOG.md`

Not pre-created. release-please generates and maintains `CHANGELOG.md` itself on the first release PR.

### `backend/Dockerfile`

No changes. Already has a working `HEALTHCHECK` and follows reasonable patterns.

### `frontend/Dockerfile`

Two changes:
1. **Drop the unused `VITE_API_URL` build arg.** The production SvelteKit bundle uses relative `/api/...` URLs; `VITE_API_URL` is read only inside `vite.config.ts` for the dev server proxy, so the build arg has no effect on the published image.
2. **Add a `HEALTHCHECK`** matching PlugTrack:
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
       CMD wget --quiet --tries=1 --spider http://localhost/ || exit 1
   ```

### `compose.yaml` (new — production, registry-pull)

```yaml
# KeroTrack v2 production compose — pulls pre-built images from the
# GitHub Container Registry instead of building locally.
#
# Usage:
#   1. Create `.env` next to this file with at least:
#        APP_SECRET_KEY=<a-strong-random-secret-of-32+-chars>
#      Generate one:
#        python -c "import secrets; print(secrets.token_urlsafe(48))"
#
#   2. (Optional) Pin a specific image tag — defaults to `latest`:
#        export KEROTRACK_TAG=v0.1.0
#      or set `KEROTRACK_TAG=v0.1.0` in `.env`.
#
#   3. docker compose pull
#      docker compose up -d
#
# Data lives in the Docker-managed named volumes `kerotrack-data` and
# `kerotrack-logs`. To bind to host paths instead, drop a
# `compose.override.yaml` next to this file — see
# `compose.override.yaml.example` for two patterns.
#
# For local source-tree development (build images locally instead of
# pulling), use `compose-dev.yaml`:
#   docker compose -f compose-dev.yaml up --build

services:
  backend:
    image: ghcr.io/mrsijo/kerotrack-api:${KEROTRACK_TAG:-latest}
    container_name: kerotrack-api
    pull_policy: always
    restart: unless-stopped
    env_file:
      - .env
    ports:
      - "${BACKEND_PORT:-9176}:9176"
    volumes:
      - kerotrack-data:/app/data
      - kerotrack-logs:/app/logs
    networks:
      - kerotrack-net
    healthcheck:
      test:
        - CMD
        - curl
        - -fsS
        - http://localhost:9176/api/health
      interval: 30s
      timeout: 5s
      start_period: 20s
      retries: 3

  frontend:
    image: ghcr.io/mrsijo/kerotrack-ui:${KEROTRACK_TAG:-latest}
    container_name: kerotrack-ui
    pull_policy: always
    restart: unless-stopped
    ports:
      - "${FRONTEND_PORT:-9177}:80"
    depends_on:
      backend:
        condition: service_healthy
    networks:
      - kerotrack-net
    healthcheck:
      test:
        - CMD
        - wget
        - --quiet
        - --tries=1
        - --spider
        - http://localhost/
      interval: 30s
      timeout: 5s
      start_period: 10s
      retries: 3

volumes:
  kerotrack-data:
  kerotrack-logs:

networks:
  kerotrack-net:
    driver: bridge
```

The backend service stays named `backend` because the published frontend image bakes `proxy_pass http://backend:9176/api/` into its nginx config — renaming the service would break the published image.

### `compose-dev.yaml` (renamed from current `compose.yaml`)

Functionally identical to today's `compose.yaml` (build blocks, current bind mounts at `/dockerdata/kerotrack/...` left in for the existing personal deploy workflow). Two minor changes during the rename:

1. Drop the `args: { VITE_API_URL: ... }` block from the frontend service — the build arg is being removed from `frontend/Dockerfile`, so passing it in compose has no effect.
2. Header comment added pointing newcomers at `compose.yaml` for the registry-pull path.

### `compose.override.yaml.example`

```yaml
# Local override for the deploy host. Copy to `compose.override.yaml`
# (which is gitignored) and adapt to your host paths. `docker compose`
# automatically merges this on top of `compose.yaml`.
#
# Two patterns:
#
# (A) Re-bind the named volumes to host paths (data persists at host
#     paths, but volume names stay stable):
volumes:
  kerotrack-data:
    driver_opts:
      type: none
      device: /dockerdata/kerotrack/data
      o: bind
  kerotrack-logs:
    driver_opts:
      type: none
      device: /dockerdata/kerotrack/logs
      o: bind

# (B) Or replace the volume mounts directly on the service. Uncomment
#     this block AND remove the `volumes:` block above:
# services:
#   backend:
#     volumes:
#       - /dockerdata/kerotrack/data:/app/data
#       - /dockerdata/kerotrack/logs:/app/logs
```

### `.gitignore` additions

```
compose.override.yaml
```

(The `compose.yaml.bak-pre-migration` file already in the working tree is left alone — out of scope; user can remove it manually when convinced the new setup is stable.)

## Data flow

```
git push main
  ├─→ build-images.yml (push trigger)
  │     ├─ build kerotrack-api → push :latest, :sha-<short>
  │     └─ build kerotrack-ui  → push :latest, :sha-<short>
  └─→ release-please.yml
        └─ open/update Release PR

merge Release PR
  └─→ release-please-action creates tag v0.1.0
        └─→ build-images.yml (tag trigger)
              ├─ kerotrack-api → :v0.1.0, :0.1, :0, :latest, :sha-<short>
              └─ kerotrack-ui  → :v0.1.0, :0.1, :0, :latest, :sha-<short>

deploy host:
  docker compose pull
  docker compose up -d
  curl http://<host>:9176/api/health
```

## Error handling

- **First run before packages are made public:** the deploy host will need `docker login ghcr.io` with a PAT (or the user makes the packages public per the workflow header comment) before `docker compose pull` succeeds. This is a one-off setup step on the deploy host, not a workflow issue.
- **Failing PR build:** PR is gated; the failing build surfaces in PR checks and blocks merge.
- **Failing release-please:** the action errors loudly; release PR isn't created or updated. Recoverable by fixing config / commit history.
- **Missing `APP_SECRET_KEY` on deploy host:** `bootstrap.py::Bootstrap._validate_secret_key` (security contract) refuses startup with a clear error. Existing behaviour, no new failure mode.

## Testing

- **First push to main:** verify both workflows run; verify GHCR shows `kerotrack-api` and `kerotrack-ui` packages with `:latest` and `:sha-<short>` tags.
- **PR test:** open a no-op PR; verify build-images runs **without pushing** (no new tags appear in GHCR).
- **Tag test:** after merging the first release PR, verify the `v0.1.0` tag triggers another build-images run that produces `:v0.1.0`, `:0.1`, `:0`, `:latest`.
- **Deploy host smoke:** stop existing stack, drop in new `compose.yaml` + `compose.override.yaml` + existing `.env`, run `docker compose pull && docker compose up -d`, then `curl http://<docker-host>:9176/api/health` returns `{"status": "ok", ...}`.
- **End-to-end UI:** hit the frontend at `http://<docker-host>:9177`, log in, confirm the dashboard loads readings (proves the frontend's nginx → backend proxy works in the published image).

## Rollout sequence

1. Implement everything above as a single commit on `main`.
2. Push. First `build-images.yml` run produces `:latest` and `:sha-<short>` for both packages. First `release-please.yml` run opens the `0.1.0` Release PR.
3. Set both GHCR packages to public under <https://github.com/MrSiJo?tab=packages> (one-off; the workflow file's header comment is the reminder).
4. On the deploy host:
   - Stop the current stack (`docker compose down` from the existing source checkout).
   - Drop in the new `compose.yaml`, create `compose.override.yaml` from `compose.override.yaml.example`, keep existing `.env`.
   - `docker compose pull && docker compose up -d`.
   - `curl http://<docker-host>:9176/api/health` to verify.
5. Optionally merge the release-please Release PR to cut `v0.1.0` and watch the tag trigger a second build-images run.

## Out of scope

- **Multi-arch (arm64).** Easy add later by extending `platforms:` to `linux/amd64,linux/arm64` and re-adding `docker/setup-qemu-action@v4`.
- **Auto-deploy.** No SSH-deploy step, no Watchtower. The CLAUDE.md deploy ritual still applies — manual `docker compose pull && docker compose up -d` on the deploy host.
- **Vulnerability scanning** (Trivy, Snyk) — easy add-on later.
- **Image signing** (cosign / sigstore) — not in PlugTrack either.
- **Repository rename.** GitHub repo stays `KeroTrack`; image names use the v2 service convention.
- **Removing `compose.yaml.bak-pre-migration`.** Local backup; user removes when convinced.

## Alternatives considered

- **Single compose.yaml with a build-or-pull toggle via profiles.** Considered but rejected — confusing for new users (you'd need both `image:` and `build:` keys, plus profile docs). PlugTrack's split is clearer.
- **Bind mounts in the published `compose.yaml` parameterised by `${KEROTRACK_DATA_DIR:-./data}`.** Considered. Rejected because YAML can't toggle "named volume vs bind mount" via a single env var without ugly conditional structures, and because it leaks the user's preferred host-path style into the public file. The `compose.override.yaml` pattern is a cleaner separation.
- **Multi-arch from day one.** Rejected per the user's amd64-only deploy target. Re-enable with two-line change to `build-images.yml` if ever needed.
- **GHCR PAT instead of `GITHUB_TOKEN`.** Rejected — `GITHUB_TOKEN` with `packages: write` works for same-owner GHCR pushes, no PAT needed.
