# Tier 2 Images on Distroless Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run beets, Tautulli and SearXNG on our own shell-free signed images (new private `neilcar/pyapps-image`, plus `beets-base` in neilcar/distroless), move the Tetragon threat-intel CronJob onto `distroless/python`, port beets' bash entry points to Python, and delete the finished `alpine` one-off Job.

**Architecture:** `beets-base` is an apko/Wolfi runtime (Python 3.12, tini, ffmpeg, chromaprint, flac, ImageMagick). `pyapps-image` builds `tautulli`, `searxng` (on `distroless/python:3.12`) and `beets` (on `beets-base`, with `mp3val` built from source) from pinned sources, smoke-tests each read-only as its uid, compares Trivy findings with the image it replaces, and publishes signed private images. beets-auto-import's entry points become stdlib Python first, proven on today's linuxserver image, so the beets image switch is a pure image change. Each switch is one revertable lxdk8s commit.

**Tech Stack:** apko/Wolfi + the `dl` CLI (distroless repo), Docker multi-stage builds, Python 3.12 / pytest / uv, GitHub Actions (ARC + native amd64/arm64), cosign 2.4.3, Trivy, Kyverno CLI, Fleet (lxdk8s), arr-helm, n8n (`n8n/deploy.py`).

**Spec:** `docs/superpowers/specs/2026-10-31-tier2-distroless-design.md` (neilcar/distroless)

## Global Constraints

- Images `ghcr.io/neilcar/{tautulli,searxng,beets}`: **private** GHCR, amd64 + arm64 on native runners, tagged `<version>` and `<version>-<sha7>`, signed in `build.yml` on `main` with **cosign 2.4.3, `--registry-referrers-mode=legacy`**, then `cosign verify --certificate-identity https://github.com/neilcar/pyapps-image/.github/workflows/build.yml@refs/heads/main`. No `sign-image.yml`.
- Start versions (no upgrades in the switch): Tautulli **2.18.2**, SearXNG **2026.10.19-81371861f** (commit `81371861f`), beets **2.14.1** with beetcamp **0.26.0**, beets-extrafiles not included, plus the other packages listed in the spec's beets details except beets-alternatives, beets-extrafiles, python3-discogs-client.
- Runtime: no shell, read-only root, restricted pod-security set (runAsNonRoot, allowPrivilegeEscalation false, drop ALL, RuntimeDefault seccomp). uid/gid: Tautulli 1000:1000, beets 1000:1000 (supplementary group 100 `users`), SearXNG 977:977. `/tmp` writable (emptyDir). beets: `/config` writable; no httpshell, Service port 5555 removed; `beet web` stays on 8337.
- beets entry points keep the exact CLI shapes, lock file `/config/auto-import/run.lock`, run dir `/config/auto-import/runs/<RUN_ID>`, `SUMMARY {json}` / `REVIEW-EXPORT {json}` / `REVIEW-RESULT {json}` output lines and exit codes (auto: 0 ok/warn, 10 failed, 11 busy, 2 usage; downloads attach: 0, 10, 2; review: 0, 2).
- Trivy gate: base strict (no Critical/High with a released fix); app images no Critical/High in what we add, and no worse than the image they replace.
- Kyverno: test every manifest/policy change with the Kyverno CLI against all policies and PolicyExceptions; server dry-run admission before merging a switch.
- Deploys via Fleet GitOps (lxdk8s); every merge with the owner's OK after checks pass. Re-importing n8n workflows (`n8n/deploy.py`) is in scope; restarting n8n is not (ask).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; PR bodies end with the Claude Code line. Never print secrets; list GitHub variables/secrets with `--json name` only.

## Review Focus

1. **Root vs uid 1000 callers.** On the linuxserver image `kubectl exec` runs as root and the bash scripts drop to `abc` via `s6-setuidgid`; on the new image the caller is already 1000. Files the entry points create (run dirs, backups, progress) must end up 1000:100 either way, and children must never run as root. Test: Task 2 `test_child_env_drops_to_abc_when_root` / `test_child_env_unchanged_when_not_root`, `test_make_run_dir_owned_by_abc`.
2. **Worker liveness in a shell-free pod.** A worker that died, or is a zombie, must make `attach` finish with exit 10 and the "worker exited without a result" summary, not loop forever. Test: Task 2 `test_worker_alive_false_for_zombie`, `test_attach_finishes_10_when_worker_gone`; Task 4 tini as PID 1 reaps (smoke).
3. **Dropped exec stream.** A second `attach` with the same RUN_ID re-attaches and never starts a second worker. Test: Task 2 `test_attach_twice_starts_one_worker`.
4. **Odd download paths.** Unicode, spaces, `..` and symlinks in the downloads `PATH` argument and `check-path`. Test: Task 2 `test_check_path_rejects_dotdot_and_outside`, `test_check_path_accepts_unicode_and_spaces`.
5. **Config locations under a read-only root.** SearXNG must read the mounted `/etc/searxng/settings.yml`; Tautulli must not try to self-update; the bandcamp plugin writes `response.json` to the CWD (review runs in the run dir). Test: Task 4 smoke (SearXNG engine list from the fixture settings, Tautulli `check_github false` honoured, read-only run) and Task 2 `test_review_runs_in_run_dir`.

---

## File Structure

| Repo / file | Responsibility |
|---|---|
| lxdk8s `fleet/tetragon-threatintel/cronjob.yaml` | threat-intel image swap |
| beets-auto-import `beets/entrylib.py` | shared: lock, run dir, progress, child env/uid drop, worker spawn + liveness, attach loop |
| beets-auto-import `beets/{beets_auto_import,import_downloads,review,repair_and_rerun,restart_stopped_run,resume_downloads,unroot_untagged_locked}.py` | ported entry points (the `.sh` files are deleted) |
| beets-auto-import `tests/test_entrylib.py`, `tests/test_entrypoints.py` | unit tests (pytest, temp dirs, fake beets children) |
| beets-auto-import `k8s/beets-auto-import.yaml`, `n8n/build_*.py`, `n8n/test/workflow-jobs.test.js`, `README.md` | new argv in the admission policy and Job builders |
| distroless `catalog.yaml`, `src/dltools/lines.py`, `tests/test_lines.py`, `tests/smoke/test_images.sh`, `locks/beets-base/latest/*`, `state/lines.json`, `README.md` | `beets-base` line |
| pyapps-image `versions.env`, `requirements/beets.txt`, `scripts/{fetch.py,inputs.py,watch.py,trivy-compare.py,notes-history.py,assert-private.sh,open-fleet-pr.py}` | sources, pins, CI helpers (adapted from servarr-image) |
| pyapps-image `Dockerfile.{tautulli,searxng,beets}`, `tests/smoke.sh`, `tests/fixtures/<app>/`, `tests/test_*.py` | images and tests |
| pyapps-image `.github/workflows/{build.yml,watch.yml}` | CI, release, watcher, lxdk8s PRs |
| lxdk8s `fleet/kyverno-policies/verify-images.yaml`, `fleet/tautulli/tautulli.yaml`, `fleet/searxng/{searxng.yaml,ghcr-pull.yaml}`, `fleet/arr/arr-values.yaml` | admission + switches |
| arr-helm `images.yaml`, `defaults.yaml`, `.github/scripts/update-images.py`, `test_update_images.py`, `README.md` | beets permanent + auto-follow |

---

### Task 1: Threat-intel on `distroless/python`, and delete the finished one-off Job

**Files:** lxdk8s `fleet/tetragon-threatintel/cronjob.yaml`.

- [ ] **Step 1:** Change the updater image to `ghcr.io/neilcar/distroless/python:3.12@<current digest>` (look up the digest), `command: ["/usr/bin/python3.12", "/opt/updater/update-policy.py"]`, and replace the "not gated by verifyImages" comment. Keep runAsUser 65534 and read-only root.
- [ ] **Step 2:** Kyverno CLI against all policies + exceptions (`kyverno apply fleet/kyverno-policies/ --resource <rendered cronjob> --exceptions fleet/kyverno-exceptions/`) — Expected: pass, verify-images rule matches `ghcr.io/neilcar/distroless/*`. Server dry-run `kubectl create --dry-run=server -f` — Expected: admitted.
- [ ] **Step 3:** PR, owner merges. Check: the next hourly Job completes, its log shows the policy rendered, and the TracingPolicy's `resourceVersion` changed or the log says unchanged.
- [ ] **Step 4:** `kubectl --context default -n apps delete job stash-library-move-path-rewrite` (completed 2026-10-28, spec Cleanup). Expected: job and its pod gone.

### Task 2: beets entry points in Python (beets-auto-import)

**Files:** Create `beets/entrylib.py`, the seven `.py` entry points, `tests/test_entrylib.py`, `tests/test_entrypoints.py`, `pyproject.toml` (pytest only); delete the seven `.sh` files; modify `k8s/beets-auto-import.yaml`, `n8n/build_workflow.py`, `n8n/build_downloads_workflow.py`, `n8n/build_review_workflows.py`, `n8n/test/workflow-jobs.test.js`, `README.md`.

**Interfaces (Produces):**
- Every entry point: shebang `#!/usr/bin/python3`, mode 0755, stdlib only; argv identical to its `.sh` (`beets_auto_import.py attach RUN_ID`, `import_downloads.py attach RUN_ID [PATH] | start RUN_ID SOURCE... | check-path PATH`). `review.sh` becomes **`review_entry.py`** `export RUN_ID | apply RUN_ID DECISIONS`, because `review.py` already exists as the worker it calls. The other four keep their names with `.py`.
- `entrylib.BASE = Path("/config/auto-import")` (overridable by env `AUTO_IMPORT_BASE` for tests); `ABC_UID = 1000`, `USERS_GID = 100`.
- `beets_python() -> str`: `/lsiopy/bin/python3` if it exists, else `sys.executable`.
- `child_env(extra: dict[str, str]) -> dict[str, str]`: os.environ + `HOME=/config`, `BEETSDIR=/config` + extra.
- `run_child(argv: list[str], *, env: dict, stdout, cwd: Path | None = None) -> int`: when `os.geteuid() == 0`, `subprocess.run(..., user=ABC_UID, group=USERS_GID, extra_groups=[])`; otherwise as is.
- `make_run_dir(path: Path) -> None`: mkdir -p; chown 1000:100 only when root.
- `RunLock(path, *, wait: bool)`: context manager on `fcntl.flock`; `acquired: bool`.
- `progress(run: Path, msg: str) -> None`: appends `<%Y-%m-%dT%H:%M:%S%z> msg`.
- `finish(run: Path, code: int, summary_json: str) -> None`: writes `summary.json`, then `exit`.
- `spawn_worker(script: Path, run_id: str, run: Path) -> int`: `subprocess.Popen([sys.executable, script, "worker", run_id], start_new_session=True, stdin=DEVNULL, stdout/err → run/"worker.out")`; writes the pid to `run/"worker.pid"`.
- `worker_alive(run: Path) -> bool`: pid from `worker.pid`, `/proc/<pid>/stat` exists, state not `Z`, and its cmdline ends with `worker <run_id>`.
- `attach_loop(run: Path, on_dead: Callable[[], None], *, poll: float = 30, quiet_every: int = 10) -> int`: the bash loop (print new progress lines, "still running" keepalive, `on_dead` when the worker is gone and no `exit` after a 5 s grace), then prints `SUMMARY <summary.json without newlines>` and returns the int in `exit`.
- `busy_with_dedupe() -> bool`: any `/proc/*/cmdline` starting with `<python> /config/dedupe` (replaces the pgrep).

- [ ] **Step 1: Tests** in `tests/test_entrylib.py` (temp `AUTO_IMPORT_BASE`; monkeypatch `os.geteuid`, `os.chown`, `subprocess.run`):
  - `test_child_env_drops_to_abc_when_root` — geteuid 0 → `subprocess.run` called with `user=1000, group=100`; env has `HOME=/config`, `BEETSDIR=/config`.
  - `test_child_env_unchanged_when_not_root` — geteuid 1000 → no `user`/`group` kwargs.
  - `test_make_run_dir_owned_by_abc` — root → `chown(path, 1000, 100)`; non-root → no chown.
  - `test_runlock_nowait_fails_when_held` — second `RunLock(wait=False)` has `acquired is False`.
  - `test_worker_alive_false_for_zombie` — fake `/proc` root (env `PROC_ROOT`) with state `Z` → False; state `S` + matching cmdline → True; missing pid → False.
  - `test_attach_finishes_10_when_worker_gone` — run dir with progress, no worker → `on_dead` called once, return 10 after `on_dead` writes exit 10; output ends `SUMMARY {...}`.
  - `test_attach_twice_starts_one_worker` — `beets_auto_import.main(["attach","r1"])` twice with `spawn_worker` stubbed → stub called once; second prints `attached to run r1`.
- [ ] **Step 2: Tests** in `tests/test_entrypoints.py`:
  - `test_usage_errors_exit_2` — bad RUN_ID (`a/b`), unknown cmd, review id not matching `^beets-review-\d{8}-\d{6}-[a-z0-9]{4}$` → exit 2.
  - `test_auto_worker_busy_exits_11` — lock held → summary `{"status":"busy",...}`, exit file `11`.
  - `test_auto_worker_runs_steps_in_order` — stub `run_child` records argv: `report stats`, `report backup`, `dedupe_import.py import -C -M -A -W -q --noincremental /bandcamp` with env `PREFER_ROOT=/bandcamp SETTLE_MINUTES=30 DEDUPE_LOG=<run>/bandcamp.log`, `dedupe_import.py import -A -q --noincremental /music/music` with `NO_EMBEDART=1`, `dedupe_pass2.py`, `cleanup_downloads.py`, `report summarize`; `steps` file lines `bandcamp 0` …; keeps newest 3 backups; prunes run dirs older than 30 days.
  - `test_check_path_rejects_dotdot_and_outside` / `test_check_path_accepts_unicode_and_spaces` — same roots and rules as `import_downloads.sh` (`/downloads/usenet/complete/music`, `/mnt/public/downloads/rtorrent/lidarr`; resolved realpath must be strictly inside; roots overridable for tests).
  - `test_downloads_batching_claims_queued_runs` — two queued runs; the worker that gets the lock claims both, each gets its own summary (port of the bash claim logic, `beets-import-downloads-*` ids).
  - `test_review_runs_in_run_dir` — `review_entry.main(["export", id])` runs `review.py export` with `cwd=<run>` and waits for the lock (`wait=True`).
  - `test_shebang_and_mode` — every entry point starts `#!/usr/bin/python3` and is 0755.
- [ ] **Step 3:** `uv run pytest` — Expected: FAIL (modules missing).
- [ ] **Step 4: Implement** `entrylib.py` and the seven entry points as straight ports of the `.sh` behaviour (read each `.sh` line by line; every env var, file name and step stays). Delete the `.sh` files.
- [ ] **Step 5:** `uv run pytest` — Expected: all PASS.
- [ ] **Step 6:** Update the admission policy lists to `/config/auto-import/beets_auto_import.py`, `/config/auto-import/import_downloads.py`, `/config/auto-import/review_entry.py` (same shapes and path/decision regexes), the three n8n builders' `args`, and the JS test expectations. Run `cd n8n && npm test` — Expected: PASS. Kyverno/VAP check: `kubectl create --dry-run=server` a Job of each kind with the new args — Expected: admitted; with the old `.sh` args — Expected: denied.
- [ ] **Step 7:** Commit, PR, owner merges. Install on the **current linuxserver pod** (it has `kubectl cp`/tar): copy the `.py` files to `/config/auto-import/` (owner 1000:100, 0755), apply the VAP (`kubectl apply -f k8s/beets-auto-import.yaml`), then `python3 n8n/deploy.py` (no n8n restart). Remove the old `.sh` copies from `/config/auto-import/` only after Step 8.
- [ ] **Step 8: Proof (spec "Proven means"):** three clean nightly auto runs; one downloads import with a path argument (next SABnzbd music job); one review export + Apply from the page; one re-attach: start a downloads run by hand, kill the `kubectl exec`, re-run `attach` with the same id — Expected: "attached to run", one worker, same summary. Record each in the ledger. Task 9 waits for this; Tasks 3–8 may run meanwhile.

### Task 3: `beets-base` in neilcar/distroless

**Files:** `catalog.yaml`, `src/dltools/lines.py`, `tests/test_lines.py`, `tests/smoke/test_images.sh`, `README.md`; generated `locks/beets-base/latest/{runtime,dev}.{apko.yaml,lock.json}`, `state/lines.json` (via `dl` sync, as for sabnzbd-base).

**Interfaces:** Produces `ghcr.io/neilcar/distroless/beets-base:latest` and `:latest-dev` (+ digests). Runtime: `python-3.12`, `tini`, `ffmpeg`, `chromaprint` (`/usr/bin/fpcalc`), `flac` (`flac`, `metaflac`), `imagemagick` (`/usr/bin/convert` or `magick` + a `convert` path entry), `ca-certificates-bundle`, `tzdata`, `libstdc++`, `libgcc`; user `beets` 1000, group `users` 100 + `beets` 1000, home `/config`; paths `/tmp` 01777, `/config` 0755 1000:1000; `/usr/bin/python3` present (symlink path entry to `python3.12` if the package lacks it); `encodings/rot_13.py` 0644 (shebang audit, as sabnzbd-base). Dev adds `busybox`, `bash`, `gcc`, `make`, `glibc-dev`, `py3.12-pip`, `uv`, and the build deps Pillow/mp3val need. `run_as: "1000"`, versioned by `python-3.12`.

- [ ] **Step 1: Test** `test_beets_base_line` in `tests/test_lines.py` (mirrors the sabnzbd-base test: `beets_base_lines(indexes) == [Line("beets-base", "latest", "python-3.12", <fixture version>)]`, `[]` on empty) and `test_discover_includes_beets_base_last`.
- [ ] **Step 2:** `uv run pytest tests/test_lines.py` — Expected: FAIL.
- [ ] **Step 3: Implement** the line and catalog entry; `dl` sync to generate locks (lock-check fails on an unknown package name — fix names against the Wolfi index).
- [ ] **Step 4:** `uv run pytest` PASS. Smoke block (CI): uid 1000, groups include 100; `fpcalc -version`, `ffmpeg -version`, `metaflac --version`, `convert -version`, `tini --version` run; `/usr/bin/python3 -c 'import ssl, sqlite3'` OK; no `/bin/sh`.
- [ ] **Step 5:** PR "beets-base: distroless base for beets", CI green (build, Trivy strict, smoke, both arches), owner merges; record digests.

### Task 4: pyapps-image — repo, Tautulli and SearXNG images, tests

**Files:** Create private repo `neilcar/pyapps-image`: `versions.env`, `scripts/fetch.py`, `scripts/inputs.py`, `Dockerfile.tautulli`, `Dockerfile.searxng`, `tests/smoke.sh`, `tests/fixtures/{tautulli,searxng}/`, `tests/test_fetch.py`, `tests/test_inputs.py`, `README.md`, `.gitignore`. Adapt from servarr-image (same names and behaviour unless noted).

**Interfaces:**
- `versions.env`: `TAUTULLI_VERSION=2.18.2`, `TAUTULLI_URL`, `TAUTULLI_SHA256` (GitHub source tarball of tag `v2.18.2`); `SEARXNG_VERSION=2026.10.19-81371861f`, `SEARXNG_COMMIT=<full sha of 81371861f>`, `SEARXNG_URL`, `SEARXNG_SHA256` (codeload tarball of that commit); `BEETS_VERSION=2.14.1`, `MP3VAL_VERSION`, `MP3VAL_URL`, `MP3VAL_SHA256`; base digests `PYTHON_RUNTIME`, `PYTHON_DEV`, `BEETS_BASE`, `BEETS_BASE_DEV`.
- `scripts/fetch.py APP DEST` (sha-verified download + extract; exit 1 on mismatch); `scripts/inputs.py APP` prints the publish key (that app's versions.env lines + its Dockerfile + requirements file + fetch.py), as servarr-image.
- Tautulli image: `/app/tautulli`, `USER 1000:1000`, `ENTRYPOINT ["/usr/bin/python3.12", "/app/tautulli/Tautulli.py", "--datadir", "/config", "--nolaunch", "--port", "8181"]`, `EXPOSE 8181`; pip deps (if any beyond its bundled `lib/`) installed in the dev stage with `--require-hashes`.
- SearXNG image: `/usr/local/searxng`, served the way its upstream image serves it at that commit (builder's call per spec), `USER 977:977`, settings from `SEARXNG_SETTINGS_PATH=/etc/searxng/settings.yml`, `EXPOSE 8080`, static assets/translations built in the dev stage.

- [ ] **Step 1: Tests** `tests/test_fetch.py` (`test_fetch_rejects_wrong_hash`, `test_fetch_extracts`), `tests/test_inputs.py` (`test_key_changes_with_app_lines_only`: changing a SEARXNG line doesn't change the tautulli key), `test_versions_env_complete` (all keys present, hex SHA-256, https URLs, digests `sha256:`).
- [ ] **Step 2:** `uv run pytest` — Expected: FAIL.
- [ ] **Step 3: Implement** scripts, versions.env, both Dockerfiles, fixtures (Tautulli `config.ini` with `http_port 8181`, `check_github 0`, `auto_update 0`, `git_path ""`; SearXNG `settings.yml` = lxdk8s ConfigMap content, `SEARXNG_SECRET` test value).
- [ ] **Step 4:** `uv run pytest` PASS. `tests/smoke.sh APP IMAGE` (runs in Task 6 CI), every run `--read-only --tmpfs /tmp --user <uid>`, no `/bin/sh` in the image (`docker run --entrypoint /bin/sh` fails):
  - tautulli: `-v <fixture copy>:/config`; `GET /status` → 200 within 60 s; `GET /api/v2?cmd=status` OK; `tautulli.db` created; log has no `Traceback` and no git/update attempt (`grep -i "checking for updates\|git"` empty); restart on the same `/config` → 200 again.
  - searxng: `-v fixture settings.yml:/etc/searxng/settings.yml:ro`; `/healthz` 200 within 60 s; `GET /config` lists engines `bing`, `yahoo`, `yandex` enabled (proves the mounted settings are read); no `Traceback`.
- [ ] **Step 5:** Commit; create the private repo and push `main`.

### Task 5: pyapps-image — beets image

**Files:** `Dockerfile.beets`, `requirements/beets.txt` (hash-pinned), `tests/fixtures/beets/` (config.yaml with the spec's plugin list, a two-album library of tiny generated FLAC/MP3 files, empty `musiclibrary.blb` created at test start), `tests/test_requirements.py`; extend `tests/smoke.sh`.

**Interfaces:** `FROM beets-base-dev` build stages: mp3val from `MP3VAL_URL` (sha-checked) → `/usr/bin/mp3val`; `pip install --require-hashes --target /opt/beets -r requirements/beets.txt`. Final `FROM beets-base@<digest>`, `PYTHONPATH=/opt/beets`, `/usr/bin/beet` (a Python entry script `#!/usr/bin/python3` calling `beets.ui:main`), `ENV BEETSDIR=/config HOME=/config`, `USER 1000:1000`, `ENTRYPOINT ["/usr/bin/tini", "--"]`, `CMD ["/usr/bin/beet", "-c", "/config/config.yaml", "web"]`, `EXPOSE 8337`. The image also carries a copy of beets-auto-import's `beets/` and `tests/` at a pinned commit (`BEETS_AUTO_IMPORT_REF` in versions.env) under `/opt/beets-auto-import-tests`, used only by CI (spec guard).

- [ ] **Step 1: Test** `tests/test_requirements.py`: `test_beets_pins` — `beets==2.14.1`, `beetcamp==0.26.0` present with `--hash=sha256:`; `beets-alternatives`, `beets-extrafiles`, `python3-discogs-client` absent; every line hashed.
- [ ] **Step 2:** `uv run pytest tests/test_requirements.py` — Expected: FAIL.
- [ ] **Step 3: Implement** requirements (compiled with `uv pip compile --generate-hashes` for py3.12, both arches' wheels), Dockerfile, fixtures.
- [ ] **Step 4:** `uv run pytest` PASS. Smoke (CI), `--read-only --tmpfs /tmp --user 1000:1000 --group-add 100 -v <fixture>:/config`:
  - `beet version` lists every plugin from the fixture config with no "could not load plugin";
  - `beet import -A -q /config/fixtures/albums` imports 2 albums; `beet ls -a` shows 2; `fpcalc`, `ffmpeg -version`, `convert -version`, `mp3val -h`, `metaflac --list` run;
  - default CMD: `GET :8337/album/` → 200 JSON with 2 albums; PID 1 is tini (`/proc/1/cmdline`);
  - spec guard: `python3 -m pytest /opt/beets-auto-import-tests/tests` inside the image → PASS;
  - zombie check: start `beets_auto_import.py attach t1` via `docker exec` against a fixture with a stubbed `dedupe_import.py` that exits at once; after the worker exits, `/proc` has no `Z` entries.
- [ ] **Step 5:** Commit, push.

### Task 6: pyapps-image CI — build, test, Trivy compare, publish, sign; Kyverno entry

**Files:** pyapps-image `.github/workflows/build.yml`, `scripts/trivy-compare.py`, `scripts/notes-history.py`, `scripts/assert-private.sh`, their tests (copy from servarr-image with app names changed); lxdk8s `fleet/kyverno-policies/verify-images.yaml`.

**Interfaces:** matrix `app × arch`; same PUSH/LOCAL gating, per-app publish keyed on `inputs.py`, digests saved, release per `<app>-<version>` with notes-history. Trivy compare baselines: `lscr.io/linuxserver/tautulli:v2.18.2-ls250@<digest>`, `ghcr.io/searxng/searxng:2026.10.19-81371861f@<digest>`, `lscr.io/linuxserver/beets:2.14.1-ls358@<digest>` (digests from the running pods). Kyverno entry: `imageReferences` `ghcr.io/neilcar/{tautulli,searxng,beets}:*` and `@*`, keyless subject `https://github.com/neilcar/pyapps-image/.github/workflows/build.yml@refs/heads/main`, `githubWorkflowRepository: neilcar/pyapps-image`, `imageRegistryCredentials: {secrets: [ghcr-pull]}`, placed before the `ghcr.io/neilcar/*` catch-all.

- [ ] **Step 1:** Copy the servarr-image tests (`test_trivy_compare.py`, `test_notes_history.py`, `test_assert_private.py`, `tests/test_build_workflow.py`) and adapt app names; `uv run pytest` — Expected: FAIL until the scripts/workflow exist.
- [ ] **Step 2: Implement** the scripts and `build.yml`; `uv run pytest` — Expected: PASS.
- [ ] **Step 3:** Branch run (`workflow_dispatch`) — Expected: six build/smoke/Trivy jobs green, publish skipped; Trivy tables show each app vs baseline, no worse.
- [ ] **Step 4:** PR, owner merges; `main` publishes three images, signed and verified. Owner grants `neilcar/arr-helm` Read on `beets` (package → Manage Actions access).
- [ ] **Step 5:** lxdk8s PR with the Kyverno entry; Kyverno CLI against all policies + exceptions with a Pod per image — Expected: verify passes; owner merges. Server dry-run a Pod for each published digest in its namespace — Expected: admitted (searxng after Task 8 adds `ghcr-pull`).

### Task 7: Watcher and lxdk8s PRs for Tautulli and SearXNG

**Files:** pyapps-image `scripts/watch.py`, `follow.env` (`FOLLOW_TAUTULLI=0`, `FOLLOW_SEARXNG=0`, `FOLLOW_BEETS=0`), `.github/workflows/watch.yml`, `scripts/open-fleet-pr.py`, `tests/test_watch.py`, `tests/test_open_fleet_pr.py`; repo variable `HOMELAB_APP_CLIENT_ID` + secret `HOMELAB_APP_PRIVATE_KEY` (owner adds; the `neilcar-homelab` App must be installed on pyapps-image and lxdk8s).

**Interfaces:** `watch.py` like servarr-image's (`vet`, per-app failure collection, superseded-PR closing): Tautulli from GitHub releases (stable only), SearXNG from the newest commit on `master` that has a published upstream container tag (`YYYY.MM.DD-<sha9>`), beets from PyPI (`beets` and `beetcamp`, recompiling hashed requirements). Major-version bumps refused ("adopted by hand"). `open-fleet-pr.py APP DIGEST VERSION` (run by `build.yml` after a publish of tautulli or searxng only when that run published) rewrites the image line in `fleet/tautulli/tautulli.yaml` or `fleet/searxng/searxng.yaml` and opens an lxdk8s PR with an App token; never merges.

- [ ] **Step 1: Tests:** `test_skips_apps_not_followed`, `test_tautulli_ignores_prereleases`, `test_searxng_requires_container_tag`, `test_beets_recompiles_hashes`, `test_major_bump_refused`; `test_open_fleet_pr_rewrites_only_image_line` (fixture manifests; one line changes), `test_open_fleet_pr_skips_beets`.
- [ ] **Steps 2–4:** fail, implement, pass (`uv run pytest`).
- [ ] **Step 5:** PR, owner merges. Followed apps are switched on in Tasks 8–9 (`FOLLOW_<APP>=1` after each app's clean day).

### Task 8: Switch Tautulli, then SearXNG

**Files:** lxdk8s `fleet/tautulli/tautulli.yaml`; `fleet/searxng/searxng.yaml`, new `fleet/searxng/ghcr-pull.yaml` (InfisicalSecret from `/ghcr-pull`, same shape as `fleet/kev-alerts/secret.yaml`).

- [ ] **Step 1 (Tautulli):** Back up `/config/tautulli.db` + `config.ini` to `/config/backup-pre-distroless-YYYYMMDD/` (linuxserver image has a shell). One commit: image → `ghcr.io/neilcar/tautulli:2.18.2@<digest>`, command/args removed (image ENTRYPOINT), `imagePullSecrets: [ghcr-pull]`, `HOME=/tmp` kept, set `check_github`/`auto_update` off in the live `config.ini` first if on. Kyverno CLI + server dry-run; PR; owner merges.
- [ ] **Step 2: Checks:** pod Ready; UI loads; Plex websocket connected (Tautulli log "Connected to Plex"); History shows a play from the last day; no `Traceback` for 30 min. Revert path: revert the commit (minutes).
- [ ] **Step 3 (SearXNG):** One commit: add `ghcr-pull.yaml`, image → `ghcr.io/neilcar/searxng:2026.10.19-81371861f@<digest>`, `imagePullSecrets`, keep uid 977 and everything else. Kyverno CLI + dry-run; PR; owner merges.
- [ ] **Step 4: Checks:** `/healthz` 200; `GET /search?q=test&format=json` returns results from at least two engines; ollama-orchestrator / n8n lookups that use SearXNG still succeed on their next run.
- [ ] **Step 5:** After a clean day each: `FOLLOW_TAUTULLI=1`, `FOLLOW_SEARXNG=1` PR in pyapps-image; owner merges.

### Task 9: Switch beets (only after Task 2 Step 8 proof)

**Files:** lxdk8s `fleet/arr/arr-values.yaml`; then arr-helm `images.yaml`, `defaults.yaml`, `.github/scripts/update-images.py`, `.github/scripts/test_update_images.py`, `README.md`, `Chart.yaml`; pyapps-image `follow.env`.

- [ ] **Step 1:** Back up `musiclibrary.blb`, `state.pickle`, `config.yaml` to `/config/backup-pre-distroless-YYYYMMDD/` (on the linuxserver pod). Confirm no run holds `run.lock`.
- [ ] **Step 2:** One lxdk8s commit in `beets:`: image override → `ghcr.io/neilcar/beets:2.14.1@<digest>`; drop `env.DOCKER_MODS`, `httpshell.enabled`; `readOnlyRootFilesystem: true`; securityContext as the Servarr apps (runAsUser/Group 1000, runAsNonRoot, allowPrivilegeEscalation false, drop ALL), `supplementalGroups: [100]`, `fsGroup` unset (NFS); `/tmp` emptyDir; update the values comment. `helm template` diff: only the beets Deployment/Service change (port 5555 gone). Kyverno CLI + server dry-run; PR; owner merges.
- [ ] **Step 3: Checks:** pod Ready; arr-report's next run green (reads :8337); `kubectl exec deploy/beets -c beets -- beet ls -a added:-1d..` works; the next nightly auto run, one downloads import and one review Apply complete with exit 0; an import log shows fpcalc/convert used without "not found"; no new errors for a day. Rollback: revert the commit; the linuxserver image runs the same `.py` entry points.
- [ ] **Step 4: Permanent** (after the clean day): arr-helm PR — `images.yaml` `beets` → `ghcr.io/neilcar/beets` same tag/digest; `defaults.yaml` beets security context as in Step 2; `REGISTRY_TAGS["ghcr.io/neilcar/beets"] = re.compile(r"^\d+\.\d+\.\d+$")` with test `test_beets_follows_three_part_versions` (2.14.1 → 2.15.0 picked, `latest` ignored) failing first; remove `beets-httpshell` from `images.yaml`; chart patch bump; owner merges; in the lxdk8s "arr chart" PR drop the beets override (render diff empty for beets). pyapps-image `FOLLOW_BEETS=1`.

### Task 10: Wrap-up

- [ ] READMEs: pyapps-image (images, rollback, follow switches), beets-auto-import (new entry points, install via `kubectl cp` while on linuxserver / the non-root busybox debug container + tar pipe on the shell-free pod), arr-helm (beets), distroless Results row for `beets-base`.
- [ ] Remove the old `.sh` copies and one-off `.sh` helpers from beets `/config` (owner agreed they stop working); remove the dated backups after a clean week (owner's OK).
- [ ] Memory notes (beets on pyapps-image, entry points, Tautulli/SearXNG follow) and the daily log.
