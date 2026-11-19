"""Price additional BTC volatility-training rows against keeping the verified eight."""
from fractions import Fraction
from random import Random
from statistics import median_low

from sample_delivery import btc_row_hour


def ordered(rows, *, count=None, minimum=None, consecutive=False):
    if not isinstance(rows, list) or (count is not None and len(rows) != count) or (minimum and len(rows) < minimum):
        raise ValueError("Unexpected number of BTC training rows")
    timestamps = [btc_row_hour(row) for row in rows]
    if len(set(timestamps)) != len(rows):
        raise ValueError("Duplicate BTC hour")
    times = sorted(timestamps)
    if consecutive and any(right - left != 3600 for left, right in zip(times, times[1:])):
        raise ValueError("Expected consecutive BTC hours")
    return sorted(rows, key=lambda row: row[0])


def loss(training, validation):
    # Predict from the three training hours closest in preceding-hour range.
    # Break distance ties in favor of more recent information.
    recent_first = sorted(training, key=lambda row: row[0], reverse=True)
    total = 0
    for _, preceding, observed in validation:
        nearest = sorted(recent_first, key=lambda row: abs(row[1] - preceding))[:3]
        total += abs(median_low([row[2] for row in nearest]) - observed)
    return Fraction(total, len(validation))


def profile(rows):
    return median_low([r[1] for r in rows]), median_low([r[2] - r[1] for r in rows])


def within_history(value, history):
    values = sorted(history)
    iqr = values[3 * len(values) // 4] - values[len(values) // 4]
    return values[0] - iqr <= value <= values[-1] + iqr


def prior_and_sample(benchmark, sample_rows):
    if not isinstance(benchmark, dict):
        raise ValueError("Expected buyer benchmark object")
    prior = ordered(benchmark.get("calibration"), minimum=112, consecutive=True)
    sample = ordered(sample_rows, count=8)
    if prior[-1][0] >= sample[0][0]:
        raise ValueError("Buyer calibration must precede the preview")
    if btc_row_hour(sample[-1]) - btc_row_hour(sample[0]) >= 64 * 3600:
        raise ValueError("Preview spans more than the 64-hour listing")
    return prior, sample


def price_preview(sample_rows, benchmark, price_base_units, gas_base_units, budget_base_units, reward_base_units_per_bp, *, listing_start):
    """Estimate incremental mean absolute error reduction from historical 8-to-64 backtests."""
    amounts = (price_base_units, gas_base_units, budget_base_units, reward_base_units_per_bp)
    if any(type(n) is not int or n < 0 for n in amounts):
        raise ValueError("Use nonnegative integer base units for price, gas, budget and reward")
    prior, sample = prior_and_sample(benchmark, sample_rows)
    if btc_row_hour(prior[-1]) >= listing_start:
        raise ValueError("Full listing overlaps buyer calibration")
    if not listing_start <= btc_row_hour(sample[0]) <= btc_row_hour(sample[-1]) < listing_start + 64 * 3600:
        raise ValueError("Preview falls outside the full listing")
    level, change = profile(sample)
    supported = (within_history(level, (r[1] for r in prior)) and
                 within_history(change, (r[2] - r[1] for r in prior)))

    # Each fold simulates a historical listing with a buyer's existing training
    # history and its own subsequent scoring period. The final holdout is untouched.
    rng = Random(26)
    analogues = []
    for start in range(32, len(prior) - 79, 16):
        history = prior[:start]
        listing = prior[start:start + 64]
        scoring = prior[start + 64:start + 80]
        full_loss = loss(history + listing, scoring)
        for _ in range(8):
            preview = rng.sample(listing, 8)
            old_level, old_change = profile(preview)
            distance = abs(level - old_level) + abs(change - old_change)
            gain = loss(history + preview, scoring) - full_loss
            analogues.append((distance, gain))
    nearest = sorted(analogues, key=lambda pair: pair[0])[:8]
    estimated_gain = sum(gain for _, gain in nearest) / len(nearest)
    value = max(0, int(estimated_gain * reward_base_units_per_bp)) if supported else 0
    cost = price_base_units + gas_base_units
    return {
        "decision": "buy" if value > cost and budget_base_units >= cost else "pass",
        "estimated_value_base_units": str(value),
        "price_base_units": str(price_base_units), "gas_base_units": str(gas_base_units),
        "total_cost_base_units": str(cost), "budget_base_units": str(budget_base_units),
        "reward_base_units_per_bp": str(reward_base_units_per_bp),
        "historical_draws": len(analogues), "matched_draws": len(nearest),
        "positive_matched_draws": sum(gain > 0 for _, gain in nearest),
        "historical_mean_gain_bps": float(estimated_gain),
        "preview_within_calibration_range": supported,
    }


def measured_outcome(sample_rows, full_rows, benchmark):
    """Measure actual incremental training utility after verified full delivery."""
    prior, sample = prior_and_sample(benchmark, sample_rows)
    listing = ordered(full_rows, count=64, consecutive=True)
    holdout = ordered(benchmark.get("holdout"), minimum=1, consecutive=True)
    if prior[-1][0] >= listing[0][0] or listing[-1][0] >= holdout[0][0]:
        raise ValueError("Expected calibration before listing, followed by the separate holdout")
    if any(row not in listing for row in sample):
        raise ValueError("Full listing differs from the preview")
    retained = loss(prior + sample, holdout)
    full = loss(prior + listing, holdout)
    return {"holdout_rows": len(holdout), "retained_mae_bps": float(retained),
            "full_mae_bps": float(full), "realized_gain_bps": float(retained - full)}
