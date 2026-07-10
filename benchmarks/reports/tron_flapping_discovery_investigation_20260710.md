# TRON Verdict Flapping and Discovery Investigation

Run date: 2026-07-10. This investigation was read-only. No collector, alert, environment variable, database record, or deployment was changed.

## Findings

### 1. BLUC verdict flapping is a data-availability artifact

Token: `TNssvWyu48fuCRQkqfs9T4qX5T9PkBAxNN` (Bit Universal / BLUC).

The current cached record is `WARN 40%` with these exact conditions:

| CIA module | Status | Reason |
| --- | --- | --- |
| funding_origin | unavailable | `missing_deployer` |
| deployment_latency | unavailable | `missing_deployment_timestamp` |
| tx_entropy | ok | 1 transaction / 2 wallets |
| wash_pattern | error | TronGrid HTTP 429 on `/transactions/trc20?limit=200` |
| holder_cluster_age | error | TronGrid HTTP 429 on the same endpoint |
| contract_backdoor | ok | no backdoor signal |

The normal underlying score is **23% GOOD**, from the thin-activity signal (`1 tx / 2 wallets`). `confidence_from_modules()` calls the scan LOW when three or more modules are error/unavailable. In `process_token()`, LOW confidence appends `low confidence: insufficient TRON data`, forces GOOD to WARN, and raises the score to at least 40. That precisely explains the observed 23/GOOD <-> 40/WARN pattern.

The repeated production scan sequence confirms it: 05:05 WARN 40, 06:06 WARN 40, 07:06 GOOD 23, 08:06 GOOD 23, 09:07 GOOD 23, 10:07 WARN 40, 11:07 GOOD 23, 12:08 WARN 40. There is no newly detected on-chain risk in the WARN scans.

#### Root cause

There are two separate availability problems:

1. **Deterministic missing discovery context.** The GeckoTerminal pool feed supplies BLUC without deployer or deployment timestamp, so funding and latency modules cannot run on every scan.
2. **Avoidable rate limiting.** The collector calls the same TronGrid TRC-20 transfer endpoint independently for deployment latency, entropy, wash pattern, and holder-cluster analysis. With the configured short delay, the later calls intermittently receive HTTP 429. The current record shows this explicitly for wash and holder-cluster.

So this is not a real risk-state change, and not an unexplained RPC timeout. It is a 429 rate-limit failure combined with a confidence rule that changes the user-facing verdict.

#### Options assessed

| Option | Assessment |
| --- | --- |
| a. Do not re-alert when only data availability changed | Necessary. A confidence-only transition must not look like a new risk event. Store/publish the scan state, but suppress Telegram unless risk signals or the underlying base verdict changed. |
| b. If alerted, explain prior result and lower confidence | Useful as a fallback. Text should say the previous verdict and make clear that the new state is degraded data, not a newly discovered token risk. |
| c. Retry/backoff before degraded result | Necessary. Retry a 429 once or twice with exponential backoff and respect `Retry-After` when present. More importantly, fetch the token's transfer data once per scan and pass that result to latency/entropy/wash/cluster instead of making four near-identical requests. |

**Recommended approach: combine a + c, with b only for an explicit low-confidence status notice.** The alert verdict should remain the last high-confidence verdict when facts have not changed; a scan that cannot verify enough data should be marked `GOOD (low confidence)` or `UNVERIFIED`, not transformed into a fresh WARN. A low-confidence state should not overwrite the last reliable verdict in the alert stream.

### 2. TRON discovery exists but effective coverage is frozen

The collector has four possible sources:

| Source | Code exists | Production state | Observed result |
| --- | --- | --- | --- |
| GeckoTerminal new pools | Yes | enabled; 1,800-second refill | Current endpoint returns exactly one token: BLUC. |
| GeckoTerminal top pools | Yes | disabled (`GECKOTERMINAL_TOP_POOLS_ENABLED=false`) | Logs report `found=0`. |
| DEX `PairCreated` events | Yes | disabled globally (`CONSOLIDATED_DEX_SCAN_ENABLED=false`) | Never invoked. |
| New smart-contract deployments | Yes | disabled globally (`CONSOLIDATED_FALLBACK_SCAN_ENABLED=false`) and locally (`FALLBACK_CONTRACT_SCAN_ENABLED=false`) | Never invoked. |

The multichain worker correctly overrides the inherited Gecko URL to the TRON network. The feed itself currently returns only BLUC. With a 45-minute rescan cooldown, each 30-minute refill alternates between queueing BLUC and rejecting it as too recently seen. The token is then scanned again roughly hourly with queue length zero. This exactly matches the alert pattern.

The live TRON API reports **6 total scan records and 6 unique token addresses**. The latest record is BLUC. The raw production logs over the investigated 8-hour window show no other TRON candidate entering the queue; the count is effectively flat. The table is an upsert table, so it does not retain a history of every rescan, but the logs and flat count provide sufficient evidence that coverage is not growing.

### Conclusion

Bug 1 is confirmed: transient TronGrid rate limits, combined with two always-missing discovery fields, cause a confidence-only verdict flip. The forced score floor and alert behavior make it visible as a false risk change.

Bug 2 is also confirmed: TRON discovery code is present, but production is relying on a one-token Gecko new-pool feed while every alternate discovery path is disabled. Current coverage is only 6 unique tokens and is not increasing. This is the larger coverage issue and should be fixed before making broad TRON coverage claims.

## Proposed next change set (not implemented)

1. Deduplicate the TRC-20 transfer fetch per scan and add bounded retry/backoff for 429/5xx responses.
2. Separate `risk_verdict` from `confidence`; do not force a score or label change solely because data is incomplete.
3. Add alert deduplication based on material risk-signal changes. Suppress confidence-only re-alerts; optionally emit one clearly labelled degraded-data notice.
4. Restore at least one independent TRON discovery source beyond the single Gecko new-pool endpoint, then add discovery metrics: candidates found, accepted, rejected as seen, scanned, and unique-token count per day.
5. Before enabling broad contract fallback, confirm its cost/rate profile and filter it to TRC-20 contracts or known DEX-pair events so the worker does not spend its daily limit on arbitrary deployments.

No fix has been implemented or deployed under this report.
