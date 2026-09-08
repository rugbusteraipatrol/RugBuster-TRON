# Deploying RugBuster-TRON

Two Railway services deploy this repo off `master`. They run different
processes, and the choice is made by one ordinary environment variable read in
`start.py`.

| Service    | `RUGBUSTER_ROLE` | Process                                      |
|------------|------------------|----------------------------------------------|
| `tron`     | unset            | `chains/tron/tron_worker.py` — crawls the chain |
| `tron-api` | `api`            | `gunicorn api.tron_api:app` — serves `/api/tron/score` |

`railway.json` starts `python start.py` for both. The default is the collector,
so a service that sets nothing behaves exactly as it did before `start.py`
existed.

## Why the role lives in an env var and not in Railway config

Two Railway-native mechanisms were tried on `tron-api` first and neither held:

- **`RAILWAY_CONFIG_PATH=railway.api.json`** — set on the service and ignored. A
  genuinely fresh build with the variable active still started the collector.
  The same variable works on `bnb-api`, so this is not a general rule, which is
  exactly what made it expensive to chase.
- **A `web:` entry in the `Procfile`** — the build log confirmed
  `Found web command in Procfile`, but `railway.json`'s explicit `startCommand`
  overrides the image default at runtime, so the collector still won.

Every one of those attempts reported a **SUCCESS deployment while serving
nothing**. The only outward symptom was a 502.

Plain environment variables are read reliably, so the decision moved into
`start.py`, where it is in git, covered by `tests/test_start_role.py`, and
printed to the runtime log on every boot.

## Check the runtime log, not the deployment status

`start.py` logs which process it chose:

```
[start] RUGBUSTER_ROLE=api -> gunicorn api.tron_api:app --bind 0.0.0.0:8080
```

A service running the wrong process still reports SUCCESS, so that line — not
the deployment badge — is what confirms a deploy did what you wanted.

Note also that `railway redeploy` reuses the existing image. After changing
build-time configuration, push a commit or run `railway up` to force a rebuild.

## History

`tron-api` used to track a separate long-lived branch, `tron-api-deploy`, whose
only real difference from `master` was the start command. Nothing kept it in
sync. It drifted for two months, so every fix merged to `master` — including
live `/api/tron/score` lookups — never reached production, while `/health`
answered `ok` from July code the whole time.

If you find yourself creating a branch to change a start command, add a role to
`start.py` instead.
