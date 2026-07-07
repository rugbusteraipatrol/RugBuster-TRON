# TRON Mainnet Deployment Checklist

1. Set deployment secrets:

```env
TRON_PRIVATE_KEY=
TRONGRID_API_KEY=
TRON_FULL_HOST=https://api.trongrid.io
TRON_FEE_LIMIT=1500
```

2. Install and compile:

```bash
npm install
npm run compile
```

3. Deploy:

```bash
npm run deploy:scanner:mainnet
```

4. Capture the deployed `RugBusterScanner` address.

5. Verify on Tronscan:

- Open `https://tronscan.org/#/contract/<CONTRACT_ADDRESS>/code`
- Choose Solidity `0.8.20`
- Submit `contracts/RugBusterScanner.sol`
- Constructor args: none

6. Set Railway variables:

```env
DATABASE_URL=<shared Postgres URL>
RUN_UNTIL_DATE=2099-12-31
TRONGRID_API_KEY=<key>
TRON_TELEGRAM_BOT_TOKEN=<bot token>
TRON_TELEGRAM_CHAT_ID=@RugBusterTron
```

7. Confirm logs include:

```txt
RugBuster TRON Collector V1 - CIA/V5/V6 Intel
DB table    : tron_scans
Campaign    : until 2099-12-31
```
