# Deploying RugBuster-TRON

This repo runs **two different Railway services** off the same `master` branch.
They differ only in start command, which is why there are two config files.

| Service    | Config file         | Start command                                 | What it does                        |
|------------|---------------------|-----------------------------------------------|-------------------------------------|
| TRON collector | `railway.json`  | `python chains/tron/tron_worker.py`           | Crawls the chain, writes scans      |
| `tron-api` | `railway.api.json`  | `gunicorn api.tron_api:app --bind 0.0.0.0:$PORT` | Serves `/api/tron/score` on demand |

Railway reads `railway.json` by default. The API service overrides that with a
service variable:

```
RAILWAY_CONFIG_PATH=railway.api.json
```

Both services must track **`master`**.

## Why this file exists

`tron-api` used to track a separate long-lived branch, `tron-api-deploy`, whose
only real difference from `master` was the start command in `railway.json`.
Nothing kept that branch in sync. It drifted for two months, so every fix merged
to `master` — including live `/api/tron/score` lookups — never reached
production, while the service reported healthy the whole time. `/health` was
answering from July code.

A deploy branch that exists purely to hold one line of config is a branch nobody
remembers to update. Splitting the config into two files instead lets both
services track `master`, so there is no second branch left to fall behind.

If you find yourself creating a branch to change a start command, add a config
file and set `RAILWAY_CONFIG_PATH` instead.

## The Procfile decides which process starts

`railway.api.json` alone was not enough. The collector kept starting even after
a genuinely fresh build with `RAILWAY_CONFIG_PATH` set, and the deployment
reported SUCCESS every time.

The difference from the working `bnb-api` service is the `Procfile`. BNB's has a
`web:` entry pointing at gunicorn; TRON's had only `worker:`, so the builder
started the worker. The `Procfile` here now carries both:

```
web: gunicorn api.tron_api:app --bind 0.0.0.0:$PORT
worker: python chains/tron/tron_worker.py
```

`railway.json` still pins the collector service's start command explicitly,
which is what keeps the collector service running the collector.

Note that `railway redeploy` reuses the existing image, so it replays the old
start command. After changing build-time configuration, push a commit or run
`railway up` to force a real rebuild.

**Check the runtime log, not the deployment status.** A service starting the
wrong process still reports SUCCESS, and the only outward symptom is a 502.
