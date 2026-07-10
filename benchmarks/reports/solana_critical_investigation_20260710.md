# Solana Critical Disagreement Investigation

Run date: 2026-07-10. All requests in this investigation were read-only. No production scan table, score, or collector code was changed.

## Executive conclusion

Both critical disagreements are genuine RugBuster **calibration / endpoint-wiring gaps**, not evidence that RugCheck is simply wrong.

The public Solana `/score` response for both tokens identifies its source as `live_cache` (previously `live_rugcheck`), copies RugCheck's raw score and risk flags, then exposes RugCheck's `score_normalised` as `risk_score`. The benchmark's security normalization treated a `risk_score` below 45 as SAFE. That turns a response containing a RugCheck `danger` risk into SAFE/GOOD. The response contains no independent CIA module results, so the deployed score path did not provide the CIA evidence required to override that result.

This is particularly serious because `dataset_collector_v6.py` has CIA capabilities, but the public score path used in the benchmark does not expose their outputs for these live requests. A SAFE response must not be emitted merely because the upstream normalized number is low while an upstream risk item is explicitly `danger`.

## 1. CASHCAT

| Field | Finding |
| --- | --- |
| Token | `3grmULXrnQyN2A5LFStKFeSQsWvZjzNDsDVVLknFpump` (CASHCAT) |
| Benchmark RugBuster verdict | SAFE after Phase 2 benchmark normalization (`risk_score` 43) |
| Current RugBuster response | `WARN`, `risk_score=43`, `rugcheck_score=6160`, `source=live_cache` |
| Current RugCheck result | `score=6160`, `score_normalised=43`, `rugged=false` |
| RugCheck danger reason | `Single holder ownership`: **50.00%**, level `danger`, score `5000` |
| Other RugCheck reason | `High holder concentration`, level `warn`, score `1159` |
| Mint / freeze authorities | Both `null` |
| LP / market state at benchmark | Pump.fun AMM plus Meteora and Orca markets; first reported LP lock 100% |

### Raw-data evidence

The saved Phase 2 raw response records the exact RugBuster flags `high_holder_concentration` and `single_holder_ownership`, while the corresponding RugCheck response records the two reasons above. The read-only recheck on 2026-07-10 returned the same score and reason set; RugBuster reported `scanned_at=2026-07-10T11:36:15.885971+00:00`.

### CIA module breakdown

| Module | Result returned by the public `/score` request | Interpretation |
| --- | --- | --- |
| funding_origin | Not returned / not executed in this response | No evidence of a clean result; it is absent. |
| deployment_latency | Not returned / not executed in this response | No evidence of a clean result; it is absent. |
| tx_entropy | Not returned / not executed in this response | No evidence of a clean result; it is absent. |
| wash_pattern | Not returned / not executed in this response | No evidence of a clean result; it is absent. |
| holder_cluster_age | Not returned / not executed in this response | No evidence of a clean result; it is absent. |
| contract_backdoor | Not returned / not applicable as an EVM-style module | Solana authority data came only from RugCheck. |
| holder concentration | Present only as forwarded RugCheck flags | The explicit 50% danger signal was not given a safety floor. |
| liquidity / LP lock | Present only as forwarded RugCheck market data | LP lock does not negate a separate 50% holder concentration risk. |

The local collector has `run_cia_analysis` and the funding, latency, entropy, wash, and cluster submodules, but none of their values are present in this public response. Therefore this is not a module returning zero/clean; it is an endpoint that does not supply the modules for this score.

### Ground-truth check

DexScreener's current PumpSwap pair showed about **$149.8k liquidity**, approximately **$1.42m 24-hour volume**, over **3,200 holders**, and substantial active trading. This token is not currently dead or visibly rugged. That does not make a 50% single-holder concentration safe: it is a material exit/liquidity risk even while trading is active.

### Conclusion

**(a) Genuine RugBuster detection/calibration gap.** RugCheck's danger reason is concrete and still present. The disagreement is not a timing artifact and is not disproved by the token's current activity. RugBuster had the flag but its public score path allowed `risk_score=43` to be treated as SAFE.

## 2. AI

| Field | Finding |
| --- | --- |
| Token | `2Pyta7DKfXfgriFmVB3QRZspdPgbU4WGZdr42umbpump` (AI) |
| Benchmark RugBuster verdict | SAFE after Phase 2 benchmark normalization (`risk_score` 26) |
| Current RugBuster response | `GOOD`, `risk_score=26`, `rugcheck_score=1543`, `source=live_cache` |
| Current RugCheck result | `score=1545`, `score_normalised=26`, `rugged=false` |
| RugCheck danger reason | `Low Liquidity`: **$1,455.58**, level `danger`, score `1544` |
| Mint / freeze authorities | Both `null` |
| LP / market state at benchmark | Pump.fun AMM; first reported LP lock 100% |

### Raw-data evidence

The saved Phase 2 payload has the same direct conflict: RugBuster's `risk_flags` includes `low_liquidity`, yet the returned label is `GOOD` and risk score is 26. The read-only recheck on 2026-07-10 returned the same state; RugBuster reported `scanned_at=2026-07-10T11:36:30.066363+00:00`.

### CIA module breakdown

| Module | Result returned by the public `/score` request | Interpretation |
| --- | --- | --- |
| funding_origin | Not returned / not executed in this response | Absent, not clean. |
| deployment_latency | Not returned / not executed in this response | Absent, not clean. |
| tx_entropy | Not returned / not executed in this response | Absent, not clean. |
| wash_pattern | Not returned / not executed in this response | Absent, not clean. |
| holder_cluster_age | Not returned / not executed in this response | Absent, not clean. |
| contract_backdoor | Not returned / not applicable as an EVM-style module | Authority data came only from RugCheck. |
| low liquidity | Present as forwarded RugCheck flag | The explicit danger item did not constrain the returned SAFE/GOOD score. |

### Ground-truth check

DexScreener's current PumpSwap pair showed about **$2.9k liquidity**, **$17.6k 24-hour volume**, only **76 holders**, and a **-94.98% 24-hour price move**. The token is still technically trading, but the low-liquidity danger signal is plainly material and the price collapse supports a degraded/rug-like outcome.

### Conclusion

**(a) Genuine RugBuster detection/calibration gap, with later market deterioration reinforcing it.** The token already had only roughly $1.46k stable liquidity when it was scanned, so this cannot be dismissed as a post-scan timing change. The later -94.98% move makes the SAFE result even less defensible.

## Direct comparison and proposed fix (not implemented)

The right next change is an endpoint/scoring fix, not a new burn, collector, or database-write path:

1. Keep the current public request read-only, but make its provenance explicit: return `UNVERIFIED` when independent CIA data is unavailable instead of treating an upstream normalized number as a RugBuster SAFE decision.
2. Wire the existing Solana CIA result into the response when a collector record is available. Each module must report `pass`, `flag`, or `unavailable`; absent data must never silently behave as clean data.
3. Add a security floor before a SAFE verdict: any active source risk at `danger` must yield at least CAUTION pending independent corroboration. For the present cases, `Single holder ownership >= 50%` and liquidity around $1.5k should each be at least CAUTION; the low-liquidity case should be DANGER under the current policy.
4. Do not simply copy RugCheck's classification as RugBuster's own verdict. Preserve it as an external signal and expose independent CIA evidence separately.

No scoring adjustment has been implemented in this investigation.

## Secondary: RAY control

| Field | Finding |
| --- | --- |
| Token | `4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R` (Raydium / RAY) |
| RugBuster | `WARN`, risk 61, source `live_cache` |
| RugCheck | DANGER; total score 15,537; `score_normalised=56` |
| Reasons | Top 10 holders high ownership (danger); 24.97% and 22.22% single-holder ownership (warn); missing and mutable metadata (warn) |
| Current market check | About **512,497 holders** and **$9.24m liquidity** in the read-only RugCheck response; DexScreener had already identified a deep-liquidity RAY pair for the control set. RugCheck also marks it Jupiter verified and strict. |

This is best classified as a **RugCheck heuristic/context false positive for a canonical established token**, driven largely by large Raydium-controlled/treasury/market accounts and metadata hygiene rather than a current rug pattern. RugBuster's CAUTION is more defensible than a DANGER, but the control-group target remains failed because a canonical, deep-liquidity token should not be presented as risky without an attribution-aware explanation. This should be handled after the two critical cases by recognizing verified protocol/AMM/treasury accounts in concentration calculations, not by hardcoding a RAY exception.

## Secondary: fetch failures

| Token | Result | Diagnosis | Recoverable? |
| --- | --- | --- | --- |
| USDT `Es9v...7bZ2` | RugBuster `UNKNOWN`; RugCheck HTTP 400 `not found` | Repeated on 2026-07-10. This is a source-coverage or incorrect-control-address issue, not a rate limit. | Check the canonical mint and replace/fix the control entry; retry alone will not help. |
| BONK `DezX...hE4H` | RugBuster `UNKNOWN`; RugCheck HTTP 400 `not found` | Repeated on 2026-07-10 for the configured mint. This is a RugCheck coverage limitation for this request, not a rate limit. | Use another independent source for this control or explicitly mark it unavailable. |
| INU `56UG...pump` | Phase 2 RugBuster `UNKNOWN`; RugCheck SAFE | Recoverable cache/live availability miss, not a RugCheck failure. A read-only retry now returns RugBuster `GOOD`, risk 1, `source=live_rugcheck`. | Yes; retry/backoff resolves the RugBuster-side live/cache miss. |

## Evidence retained

The full Phase 2 source payloads, including the original RugCheck responses and holder lists, remain locally in `benchmarks/reports/agreement_raw_20260710_113632.json` (intentionally ignored because raw holder payloads are large). This report cites the complete risk-bearing fields rather than reproducing thousands of holder rows.
