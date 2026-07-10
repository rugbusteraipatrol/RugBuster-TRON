# RugBuster Agreement Benchmark

Generated: `2026-07-10T07:23:33.353021+00:00`  
Mode: read-only HTTP GET only. No RugBuster scan endpoint or production database write was called.

## Critical Disagreements

- None in evaluated rows.

## Mapping

- RugBuster: GOOD/SAFE -> SAFE; WARN/ELEVATED -> CAUTION; DANGER -> DANGER.
- GoPlus: honeypot, blacklist, hidden owner, cannot sell, balance-changing owner, transfer pause, or >=50% tax -> DANGER; unverified source/proxy/mintability/modifiable tax/cooldown or >=10% tax -> CAUTION; otherwise SAFE.
- RugCheck (operational band, documented for this benchmark): score <100 -> SAFE; 100-4,999 -> CAUTION; >=5,000 or a serious risk item -> DANGER.
- FETCH_FAILED means no verdict was inferred and the row is excluded from agreement statistics.

## Results

| Address | Chain | Bucket | RugBuster | GoPlus | RugCheck | Agree? |
|---|---|---|---|---|---|---|
| `0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c` | bnb | control | SAFE | SAFE | FETCH_FAILED | AGREE |
| `0x55d398326f99059fF775485246999027B3197955` | bnb | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d` | bnb | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c` | bnb | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x2170Ed0880ac9A755fd29B2688956BD959F933F8` | bnb | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82` | bnb | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x0efb5FD2402A0967B92551d6AF54De148504A115` | bnb | control | SAFE | SAFE | FETCH_FAILED | AGREE |
| `0x4200000000000000000000000000000000000006` | base | control | SAFE | SAFE | FETCH_FAILED | AGREE |
| `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | base | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` | base | control | CAUTION | CAUTION | FETCH_FAILED | AGREE |
| `0x940181a94A35A4569E4529A3CDfB74e38FD98631` | base | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x2Ae3F1Ec7F1F5012CFEab0185bfc7aa3cf0DEc22` | base | control | SAFE | CAUTION | FETCH_FAILED | DISAGREE |
| `0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb` | base | control | CAUTION | DANGER | FETCH_FAILED | DISAGREE |
| `So11111111111111111111111111111111111111112` | solana | control | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | solana | control | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `Es9vMFrzaCERmJfrF4H2FYDgG9hZZfZGYy7nY9j7bZ2` | solana | control | FETCH_FAILED | FETCH_FAILED | FETCH_FAILED | FETCH_FAILED |
| `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN` | solana | control | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `DezXAZ8z7PnrnRJjz3wXBoRgixCa6K2B5D2YBGz7hE4H` | solana | control | FETCH_FAILED | FETCH_FAILED | FETCH_FAILED | FETCH_FAILED |
| `DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | solana | control | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R` | solana | control | FETCH_FAILED | FETCH_FAILED | DANGER | FETCH_FAILED |
| `56UGBBY7uQAZFGcjGJXqxpMfJsB2pwtsyZrbtqRcpump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `EGK2NLMyBy4ijKKT2LWxaR5j3iVdYL6BF8hvSM2Cp5Qe` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | DANGER | FETCH_FAILED |
| `wenmEAuTuYnBko3VczbqAqytH1YUPvxvJFfw9eoJjad` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `AW1ErSHQn29nDcZ6t3ME7DfEN8PW9rGViSr5DKRppump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `BAfzsm6NvYcfWAsAmEZ4FXL7HjwQ4oNgubRcLUprLhbk` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `7AJ9sdZW6Sodb8ajnEkESeWtQVVHyZ4Gg85H3c1Ypump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `3grmULXrnQyN2A5LFStKFeSQsWvZjzNDsDVVLknFpump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | DANGER | FETCH_FAILED |
| `EVHtwfyWoHmUM5RHi3td31sNKCc8f83XKT44ZDqnpump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `7vr8rXp7MBQWT9WSYgkamL8z1mXtw6q8AkKMnA6Wpump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | SAFE | FETCH_FAILED |
| `8qf6C164VeDEHjmDwmvL7tb6mMtpWK8oAfXta4uzpump` | solana | fresh_unknown | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `76djbEspuQ75GnySUZXae93xpi4x3rrE31ALdC6Lpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `HHtWA8e6q2eaMGukQQMmZJzY4taJpQeQPVxZ7fMUpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `3uKnE29Z6MCUuXJMSJv6evHmhdd6ZbBfGC67rgoZpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | DANGER | FETCH_FAILED |
| `2Pyta7DKfXfgriFmVB3QRZspdPgbU4WGZdr42umbpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | DANGER | FETCH_FAILED |
| `FBB5ftZ6jCGi7CmoQG3voQsW5CXRn515gnWmcQAQpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |
| `61onDDxyNNwNLRyyuDgNm4fikAAHQHDAdfRt8EVBpump` | solana | likely_bad | FETCH_FAILED | FETCH_FAILED | CAUTION | FETCH_FAILED |

## Summary

### BNB
- Collected: 7; evaluated: 7; fetch failures/not-applicable: 0.
- Bucket coverage: controls=7, fresh=0, likely_bad=0.
- Agreement: 2/7 (28.6%).
- control: 2/7 agreement.
- fresh_unknown: 0/0 agreement.
- likely_bad: 0/0 agreement.

### BASE
- Collected: 6; evaluated: 6; fetch failures/not-applicable: 0.
- Bucket coverage: controls=6, fresh=0, likely_bad=0.
- Agreement: 2/6 (33.3%).
- control: 2/6 agreement.
- fresh_unknown: 0/0 agreement.
- likely_bad: 0/0 agreement.

### SOLANA
- Collected: 23; evaluated: 0; fetch failures/not-applicable: 23.
- Bucket coverage: controls=7, fresh=10, likely_bad=6.
- Agreement: 0/0 (0.0%).
- control: 0/0 agreement.
- fresh_unknown: 0/0 agreement.
- likely_bad: 0/0 agreement.

## Review Queue

- Critical SAFE-vs-DANGER disagreements: 0.
- Reverse DANGER-vs-SAFE disagreements: 0.
- Legit controls marked RugBuster DANGER: 0.
- Legit controls not marked RugBuster SAFE: 2 (review before external use).
- Control warnings: `base:0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf=CAUTION`, `base:0x50c5725949A6F0c72E6C4a641F24049A917DB0Cb=CAUTION`
