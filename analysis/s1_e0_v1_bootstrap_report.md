# V1 Bootstrap Sanity

- Trades source: `analysis/v1_trades.json`
- Resample bootstrap (with replacement), n_iter=1000, seed=42
- 95% CI = (2.5%, 97.5%) quantile of bootstrap distribution
- Decision: CI low > 0 → V1 edge; CI contains 0 → uncertain; CI high < 0 → dead
- Generated: 2026-05-24T23:22:40

## Results

| segment | metric | point | ci_low | ci_high | verdict |
|---|---|---:|---:|---:|---|
| OOS | expectancy_bp | -41.5791 | -290.1422 | 250.1306 | UNCERTAIN |
| OOS | sharpe | -0.0401 | -0.4114 | 0.1963 | UNCERTAIN |
| OOS | profit_factor | 0.8824 | 0.3126 | 1.9121 | UNCERTAIN |
| OOS | n_trades | 59.0000 | 59.0000 | 59.0000 | - |
| IS | expectancy_bp | -37.4229 | -181.5118 | 119.1329 | UNCERTAIN |
| IS | sharpe | -0.0375 | -0.2125 | 0.1093 | UNCERTAIN |
| IS | profit_factor | 0.8885 | 0.5193 | 1.4173 | UNCERTAIN |
| IS | n_trades | 169.0000 | 169.0000 | 169.0000 | - |
