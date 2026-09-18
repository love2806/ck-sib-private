# CK/SIB — deploy-safe package

Private repository for the CK ABCDE/SIB stock intelligence and Evaluation Lab.

## Included
- Versioned SIB feature snapshot and Evaluation Lab v2/v3/v4 scripts.
- Dashboard source and `ck_scanner` package.
- No production SQLite, market data, logs, API keys, tokens, or runtime artifacts.

## Local run
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export CK_DB_PATH=/var/lib/ck-sib/ck_signals.sqlite
python app/web/web_dashboard.py
```

The database and market data must be provisioned separately at runtime.

## iNET
The iNET API reference documents gateway/domain/hosting/cloud APIs and a standard wrapped response. This repository intentionally does not hard-code an iNET API key or assume a deployment endpoint. Configure credentials and the exact iNET service endpoint as hosting-side secrets after confirming the selected iNET product.
