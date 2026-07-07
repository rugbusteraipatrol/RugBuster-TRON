require("dotenv").config();

module.exports = {
  networks: {
    mainnet: {
      privateKey: process.env.TRON_PRIVATE_KEY,
      consume_user_resource_percent: 30,
      fee_limit: Number(process.env.TRON_FEE_LIMIT || 1500) * 1_000_000,
      fullHost: process.env.TRON_FULL_HOST || "https://api.trongrid.io",
      headers: process.env.TRONGRID_API_KEY
        ? { "TRON-PRO-API-KEY": process.env.TRONGRID_API_KEY }
        : {}
    },
    shasta: {
      privateKey: process.env.TRON_PRIVATE_KEY,
      consume_user_resource_percent: 30,
      fee_limit: Number(process.env.TRON_FEE_LIMIT || 1500) * 1_000_000,
      fullHost: process.env.TRON_SHASTA_FULL_HOST || "https://api.shasta.trongrid.io",
      headers: process.env.TRONGRID_API_KEY
        ? { "TRON-PRO-API-KEY": process.env.TRONGRID_API_KEY }
        : {}
    }
  },
  compilers: {
    solc: {
      version: "0.8.20"
    }
  }
};
