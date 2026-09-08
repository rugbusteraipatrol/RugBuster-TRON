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
