# RugBuster TRON

AI-powered TRC-20 security scanner and public risk registry for TRON mainnet.

This repo ports the RugBuster Avalanche, BNB, and Base collector architecture to TRON/TVM. It also includes a consolidated Railway worker that runs Avalanche, BNB, Base, and TRON in one Python process to reduce always-on service costs.

## Coverage

| Chain | Collector | Status | Table | Notes |
|---|---|---|---|---|
| Avalanche C-Chain | `avax_collector_v6.py` | Live on Railway | `avax_scans` | EVM |
| BNB Smart Chain | `bnb_collector_v1.py` | Live on Railway | `bnb_scans` | EVM |
| Base | `base_collector_v1.py` | Live on Railway | `base_scans` | EVM |
| TRON mainnet | `tron_collector_v1.py` | Live on Railway | `tron_scans` | TVM/TRC-20/TronGrid |

## Consolidated Worker

`chains/multichain_worker.py` imports the four chain collectors and gives each chain a short turn in one long-lived process. Each chain keeps its own queue, daily state, output JSONL file, Telegram settings, and Postgres table.

Railway start command:

```bash
python chains/multichain_worker.py
```

Expected cost impact:

- Separate AVAX, BNB, Base, and TRON workers: roughly 4 always-on services.
- Consolidated worker: 1 always-on service.
- If 3 collectors cost about EUR 12/month before DB costs, the implied service cost is about EUR 4/month each.
- Expected collector runtime cost after consolidation: about EUR 4/month.
- Expected savings versus 4 separate collectors: about EUR 12/month before DB costs.

Migration safety rule: verify the consolidated worker first, then stop or remove the separate `avax`, `bnb`, `base`, and `tron` Railway services only after explicit operator confirmation.

## TRON Data Feeds

- TronGrid/full-node APIs for latest blocks, contract deployments, constant contract calls, bytecode, balances, and account transactions.
- TRC-20 metadata via `triggerconstantcontract` calls for `name()`, `symbol()`, `decimals()`, and `totalSupply()`.
- GeckoTerminal TRON `new_pools` and `pools` feeds for SunSwap/JustMoney-style DEX discovery.
- Optional direct factory event scanning through `TRON_DEX_FACTORY_ADDRESSES`, using `PairCreated` events.

## Detection Modules

The TRON collector preserves the chain-agnostic CIA/V5/V6 behavioral modules:

- Funding origin freshness
- Deployment-to-first-transfer latency
- Transaction amount entropy
- Wash transfer pattern detection
- Holder cluster age
- Cross-chain wallet pattern hash
- Lifecycle prediction
- Token name stylometry
- TVM bytecode backdoor signatures

## Railway

`railway.json` starts the consolidated worker:

```bash
python chains/multichain_worker.py
```

Required production variables:

```env
DATABASE_URL=
TRONGRID_API=https://api.trongrid.io
TRON_FULL_NODE=https://api.trongrid.io
TRONGRID_API_KEY=

TRON_TELEGRAM_BOT_TOKEN=
TRON_TELEGRAM_CHAT_ID=@RugBusterTron

MAX_TOKENS_PER_DAY=120
MIN_SCAN_DELAY_MINUTES=2
MAX_SCAN_DELAY_MINUTES=3
RUN_UNTIL_DATE=2099-12-31
CONSOLIDATED_CHAIN_TURN_SLEEP_SECONDS=5
CONSOLIDATED_DEX_SCAN_ENABLED=false
CONSOLIDATED_FALLBACK_SCAN_ENABLED=false
```

## TRON API

The TRON API is designed for a separate Railway web service so the consolidated scan worker can keep running without interruption.

### Stats

```bash
curl https://tron-api-production.up.railway.app/api/tron/stats
```

Response:

```json
{
  "ok": true,
  "chain": "tron",
  "scan_count": 5,
  "latest": {
    "address": "TR...",
    "verdict": "GOOD",
    "token_name": "Example",
    "token_symbol": "EX",
    "created_at": "2026-07-07T..."
  }
}
```

`scan_count` is read live from `tron_scans`; do not treat the example number as a static target.

### Scan

```bash
curl -X POST https://tron-api-production.up.railway.app/api/tron/scan \
  -H "Content-Type: application/json" \
  -d '{"address":"TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t","use_cached":true}'
```

Response shape:

```json
{
  "ok": true,
  "chain": "tron",
  "address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
  "verdict": "GOOD",
  "reason": "No major CIA Engine risk flags detected",
  "risk_score": 39,
  "token_name": "Tether USD",
  "token_symbol": "USDT",
  "cia_flags": {
    "funding_origin": {},
    "deployment_latency": {},
    "tx_entropy": {},
    "wash_pattern": {},
    "holder_cluster_age": {},
    "name_stylometry": {},
    "contract_backdoor": {}
  },
  "source": "postgres_cache"
}
```

Use `use_cached:false` to request a live scan if the token is not already present in `tron_scans`.

`RUN_UNTIL_DATE=2099-12-31` is also the collector default to prevent expiry-based worker outages.

## Contract

`contracts/RugBusterScanner.sol` is a TVM-compatible Solidity scanner registry. It avoids external imports so TronBox/TronIDE can compile it cleanly.

Compile and deploy:

```bash
npm install
npm run compile
npm run deploy:scanner:mainnet
```

Required deployment variables:

```env
TRON_PRIVATE_KEY=
TRONGRID_API_KEY=
TRON_FULL_HOST=https://api.trongrid.io
TRON_FEE_LIMIT=1500
```

After deployment, verify on Tronscan using the flattened Solidity source or TronIDE verification flow.

## Local Checks

```bash
pip install -r requirements.txt
python -m py_compile chains/tron/tron_collector_v1.py
python chains/tron/tron_collector_v1.py TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
npm install
npm run compile
```

## Current Status

- Contract address: pending mainnet deployment
- Tronscan verification: pending mainnet deployment
- Telegram channel: [t.me/RugBusterTron](https://t.me/RugBusterTron)
- Railway worker: live on Railway service `tron`; consolidated worker implementation added for AVAX, BNB, Base, and TRON.
- Scan count: `1+` confirmed write to `tron_scans`
- Telegram posting: configured for `@RugBusterTron`; Telegram returned `400 Bad Request`, so the bot likely still needs channel admin/posting permission.
