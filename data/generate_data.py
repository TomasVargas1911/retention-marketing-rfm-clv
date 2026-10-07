"""
Generate a reproducible, SIMULATED e-commerce transaction dataset.

Why simulated? This is a portfolio/practice project. The generator mimics the
statistical behaviour of a home & lifestyle online store (repeat purchases,
churn, seasonality, channel quality differences) and intentionally injects
"messy" data (cancellations, refunds, duplicates, missing channels) so the
cleaning step in the notebook is realistic.

The notebook only needs two tables:
  - customers.csv : customer_id, acquisition_channel
  - orders.csv    : order_id, customer_id, order_date, order_value, items, status
so you can swap in a real dataset (e.g. UCI "Online Retail II") by mapping
its columns to this schema.

Run:  python data/generate_data.py
"""
import numpy as np
import pandas as pd
from pathlib import Path

SEED = 42
N_CUSTOMERS = 6000
START = pd.Timestamp("2024-01-01")
END = pd.Timestamp("2025-12-31")          # last day of observation window
OUT = Path(__file__).parent

rng = np.random.default_rng(SEED)

# --- Channel profiles -------------------------------------------------------
# share: % of new customers | rate: avg orders per month while active
# p_churn: prob. of going inactive after each order | aov: mean order value (USD)
# p_oad: prob. the customer is "one-and-done" (never places a 2nd order)
CHANNELS = {
    "Google Search":    dict(share=0.30, rate=0.20, p_churn=0.28, aov=62, p_oad=0.52),
    "Meta Ads":         dict(share=0.25, rate=0.14, p_churn=0.38, aov=55, p_oad=0.60),
    "Organic / SEO":    dict(share=0.20, rate=0.22, p_churn=0.25, aov=60, p_oad=0.50),
    "Email / Referral": dict(share=0.10, rate=0.24, p_churn=0.22, aov=58, p_oad=0.42),
    "Programmatic":     dict(share=0.15, rate=0.08, p_churn=0.55, aov=48, p_oad=0.76),
}

# Purchase seasonality (multiplier on order rate) and acquisition seasonality
PURCHASE_SEASON = {11: 1.5, 12: 1.7, 1: 0.9, 2: 0.9}
ACQ_SEASON = {11: 1.5, 12: 1.3}
MAX_F = 1.7


def season(month, table):
    return table.get(month, 1.0)


# --- Acquisition dates (growing business + Q4 peak) -------------------------
days = pd.date_range(START, END, freq="D")
month_idx = (days.year - START.year) * 12 + (days.month - START.month)
weights = np.array([(1 + 0.025 * mi) * season(m, ACQ_SEASON)
                    for mi, m in zip(month_idx, days.month)])
weights /= weights.sum()
acq_dates = rng.choice(days, size=N_CUSTOMERS, p=weights)

names = list(CHANNELS)
shares = [CHANNELS[c]["share"] for c in names]
channels = rng.choice(names, size=N_CUSTOMERS, p=shares)

# --- Simulate each customer's order history ---------------------------------
orders = []
for i in range(N_CUSTOMERS):
    cid = f"C{i + 1:05d}"
    ch = CHANNELS[channels[i]]
    t0 = pd.Timestamp(acq_dates[i])

    # customer-level heterogeneity (some buy often, some rarely)
    lam_month = rng.gamma(shape=1.2, scale=ch["rate"] / 1.2)
    lam_day = max(lam_month / 30.4, 1e-4)
    p_churn = float(np.clip(rng.beta(4, 4 * (1 - ch["p_churn"]) / ch["p_churn"]), 0.05, 0.95))
    base_aov = rng.lognormal(np.log(ch["aov"]), 0.30)

    dates = [t0]                                   # first order = acquisition
    t = t0
    one_and_done = rng.random() < ch["p_oad"]
    while not one_and_done:
        t = t + pd.Timedelta(days=rng.exponential(1 / (lam_day * MAX_F)))
        if t > END + pd.Timedelta(hours=23):
            break
        if rng.random() < season(t.month, PURCHASE_SEASON) / MAX_F:   # thinning
            dates.append(t.normalize())
            if rng.random() < p_churn:             # customer goes inactive
                break

    for d in dates:
        value = max(8.0, base_aov * rng.lognormal(0, 0.25))
        orders.append((cid, d.normalize(), round(value, 2),
                       int(np.clip(rng.poisson(value / 25) + 1, 1, 12))))

orders = pd.DataFrame(orders, columns=["customer_id", "order_date", "order_value", "items"])
orders = orders.sort_values(["order_date", "customer_id"]).reset_index(drop=True)
orders.insert(0, "order_id", [f"ORD-{i + 1:06d}" for i in range(len(orders))])

# --- Order status + deliberately messy data ---------------------------------
orders["status"] = rng.choice(["completed", "cancelled", "refunded"],
                              size=len(orders), p=[0.96, 0.025, 0.015])

dups = orders.sample(frac=0.004, random_state=SEED)       # exact duplicate rows
orders = pd.concat([orders, dups]).sort_values("order_id").reset_index(drop=True)

customers = pd.DataFrame({"customer_id": [f"C{i + 1:05d}" for i in range(N_CUSTOMERS)],
                          "acquisition_channel": channels})
missing = customers.sample(frac=0.01, random_state=SEED).index  # missing channel
customers.loc[missing, "acquisition_channel"] = np.nan

customers.to_csv(OUT / "customers.csv", index=False)
orders.to_csv(OUT / "orders.csv", index=False)

print(f"customers.csv : {len(customers):,} rows")
print(f"orders.csv    : {len(orders):,} rows "
      f"({orders.order_date.min():%Y-%m-%d} -> {orders.order_date.max():%Y-%m-%d})")
