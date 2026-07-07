# RugBuster TRON

AI-powered TRC-20 security scanner and public risk registry for TRON mainnet.

This repo ports the RugBuster Avalanche, BNB, and Base collector architecture to TRON/TVM. The worker uses TronGrid/public full-node HTTP APIs instead of EVM JSON-RPC, scans TRC-20 tokens instead of ERC-20 tokens, and writes normalized scan records to the shared Postgres database in `tron_scans`.

## Coverage

| Chain | Collector | Status | Table | Notes |
|---|---|---|---|---|
| Avalanche C-Chain | `avax_collector_v6.py` | Live on Railway | `avax_scans` | EVM |
| BNB Smart Chain | `bnb_collector_v1.py` | Live on Railway | `bnb_scans` | EVM |
| Base | `base_collector_v1.py` | Live on Railway | `base_scans` | EVM |
| TRON mainnet | `tron_collector_v1.py` | Live on Railway | `tron_scans` | TVM/TRC-20/TronGrid |

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

`railway.json` starts the worker:

```bash
python chains/tron/tron_collector_v1.py
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
```

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
- Railway worker: live on Railway service `tron`
- Scan count: `1+` confirmed write to `tron_scans`
- Telegram posting: configured for `@RugBusterTron`; Telegram returned `400 Bad Request`, so the bot likely still needs channel admin/posting permission.
