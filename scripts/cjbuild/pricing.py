"""Landed cost and JPY retail pricing. All numbers are explicit in the profile; nothing is guessed."""

import math

from .config import BuildError


def landed_usd(variant_usd, freight_usd, profile):
    p = profile["pricing"]
    return round(float(variant_usd) + float(freight_usd) + float(p.get("handling_fee_usd", 0)), 4)


def retail_jpy(landed, profile):
    """Retail price in JPY: landed USD -> JPY at the profile FX rate, times (1 + markup), rounded to the ending rule."""
    p = profile["pricing"]
    fx = float(p["fx_usd_jpy"])
    raw = landed * fx * (1.0 + float(p["markup"]))
    step = int(p.get("round_step", 100))
    ending = int(p.get("ending", 90))
    if step <= 0:
        raise BuildError("PRICING_INVALID", "round_step must be positive")
    price = math.ceil(raw / step) * step - (step - ending) % step
    if price < raw:  # ending rule pushed below raw; move to the next step
        price += step
    floor = int(p.get("min_price_jpy", 0))
    return int(max(price, floor))


def margin(price_jpy, landed, profile):
    fx = float(profile["pricing"]["fx_usd_jpy"])
    revenue_usd = price_jpy / fx
    return round((revenue_usd - landed) / revenue_usd, 4) if revenue_usd else 0.0


def price_variant(variant_usd, freight_usd, profile):
    landed = landed_usd(variant_usd, freight_usd, profile)
    price = retail_jpy(landed, profile)
    return {"landed_usd": landed, "landed_jpy": int(round(landed * float(profile["pricing"]["fx_usd_jpy"]))),
            "price_jpy": price, "margin": margin(price, landed, profile)}
