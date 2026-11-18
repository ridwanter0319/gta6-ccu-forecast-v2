#!/usr/bin/env python3
"""Forecast a launch day's Twitch viewers, hour by hour, from past launches.

Scale-and-shape: every past big launch in the case file becomes a donor.
A donor's release-day curve is divided by its own first-hour viewers, which
turns it into a pure shape (a multiplier for each later hour). Donors that
resemble this launch -- similar first-hour audience, similar channel count,
a similar way of unlocking -- count for more. The weighted middle of the
donor shapes, scaled by this case's first-hour viewers, is the median
forecast; the weighted spread of the shapes around that middle, widened a
little and smoothed, gives the other four quantiles.

Python 3.13, standard library only, no network, deterministic.
"""

import glob
import json
import math
import os
from datetime import datetime, timezone
from statistics import NormalDist

# --- calibration constants (tuned by leave-one-out over the donor pool) ---
SIZE_SCALE = 1.15        # log-distance scale for first-hour viewers
CHAN_SCALE = 1.60        # log-distance scale for first-hour channels
CHAN_WEIGHT = 0.55       # exponent applied to the channel similarity
CLASS_SAME = 1.00        # donor unlock class matches the target's
CLASS_OTHER = 0.50       # donor unlock class clearly differs
CLASS_UNKNOWN = 0.65     # either side unclassified
PC_FACTOR = 0.60         # donor also launched on PC (targets are console-first)
MIN_DONOR_V1 = 300.0     # donors with a tinier first hour are too noisy
MEAN_BLEND = 0.50        # weight of weighted mean vs weighted median centre
ALPHA_SMALL = 1.80       # spread multiplier for a small first hour (~1e3)
ALPHA_BIG = 0.85         # spread multiplier for a big first hour (~3e5)
SHIFT_EARLY = 0.10       # big-launch centre boost at hour 2, decaying fast
SHIFT_LATE = 0.16        # big-launch centre trim that ramps in over the day
SHRINK_BIG = 0.93        # big-launch centre shrink toward a flat day
SIGMA_FLOOR = 0.10       # smallest half-spread (in log units) at hour 2
SIGMA_GROW = 0.02        # extra floor growth per sqrt(hour - 1)
SIGMA_CAP = 1.80         # largest half-spread allowed
RATIO_LO = 0.06          # multiplier caps, applied to the centre curve
RATIO_HI = 14.0
SMOOTH_PASSES = 2        # moving-average passes over the centre curve

_NORM = NormalDist()
_LEVELS_DEFAULT = [0.05, 0.25, 0.5, 0.75, 0.95]


def _parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def _unlock_class(text):
    """Classify an unlock description: 'rolling', 'global', or None."""
    t = (text or "").lower()
    rolling = ("rolling" in t) or ("midnight local" in t) or ("midnight in each" in t)
    glob = ("simultaneous" in t) or ("single global" in t) or ("global unlock" in t)
    if rolling and not glob:
        return "rolling"
    if glob and not rolling:
        return "global"
    if rolling and glob:
        return "mixed"
    return None


def _has_pc(platforms):
    t = (platforms or "").lower()
    return ("pc" in t) or ("steam" in t) or ("stadia" in t)


def _donor_curve(comp, day0):
    """Map hour (1..24 of the donor's release day) -> (viewers, channels)."""
    out = {}
    for point in comp.get("hourly") or []:
        try:
            off = int(round((_parse_ts(point["from"]) - day0) / 3600.0))
        except Exception:
            continue
        if 0 <= off < 24 and off + 1 not in out:
            out[off + 1] = point
    return out



def _weighted_quantile(pairs, frac):
    """pairs: list of (value, weight). Weighted quantile, linear interp."""
    if not pairs:
        return 0.0
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return pairs[len(pairs) // 2][0]
    target = frac * total
    acc = 0.0
    prev_v, prev_acc = pairs[0][0], 0.0
    for v, w in pairs:
        acc += w
        if acc >= target:
            if acc == prev_acc:
                return v
            f = (target - prev_acc) / (acc - prev_acc)
            return prev_v + f * (v - prev_v)
        prev_v, prev_acc = v, acc
    return pairs[-1][0]


def _smooth(values, passes):
    out = list(values)
    for _ in range(passes):
        nxt = list(out)
        for i in range(len(out)):
            acc, wsum = 0.0, 0.0
            for j, w in ((i - 1, 0.25), (i, 0.5), (i + 1, 0.25)):
                if 0 <= j < len(out):
                    acc += w * out[j]
                    wsum += w
            nxt[i] = acc / wsum
        out = nxt
    return out


def forecast_case(case):
    levels = case.get("levels") or _LEVELS_DEFAULT
    known = (case.get("known") or [{}])[0]
    p1 = float(known.get("viewers") or 0.0)
    if p1 < 1.0:
        p1 = 1.0
    c1 = known.get("channels")
    c1 = float(c1) if c1 else None
    log_p1 = math.log(p1)

    target_class = _unlock_class(case.get("notes") or "")
    if target_class is None:
        target_class = "rolling"  # every case in this contest rolls at midnight

    # Collect donors: (weight, {hour: log ratio})
    donors = []
    for comp in case.get("comparables") or []:
        unlock = comp.get("unlock") or ""
        if unlock.startswith("Not a launch"):
            continue  # the target category's own pre-release history
        try:
            day0 = _parse_ts(comp["day_start"])
        except Exception:
            continue
        curve = _donor_curve(comp, day0)
        first = curve.get(1)
        if not first:
            continue
        v1 = float(first.get("viewers") or 0.0)
        if v1 < MIN_DONOR_V1:
            continue
        log_ratios = {}
        for h in range(2, 25):
            point = curve.get(h)
            if point and float(point.get("viewers") or 0.0) > 0:
                log_ratios[h] = math.log(float(point["viewers"]) / v1)
        if len(log_ratios) < 12:
            continue
        # similarity weight
        w = math.exp(-abs(math.log(v1) - log_p1) / SIZE_SCALE)
        dc = first.get("channels")
        if c1 and dc:
            w *= math.exp(-abs(math.log(float(dc)) - math.log(c1)) / CHAN_SCALE) ** CHAN_WEIGHT
        dclass = _unlock_class(unlock)
        if dclass is None or target_class is None:
            w *= CLASS_UNKNOWN
        elif dclass == target_class or dclass == "mixed" or target_class == "mixed":
            w *= CLASS_SAME
        else:
            w *= CLASS_OTHER
        if _has_pc(comp.get("platforms")):
            w *= PC_FACTOR
        if w > 0:
            donors.append((w, log_ratios))

    hours_out = []
    if not donors:
        # No usable donors: fall back to the flat house shape.
        for row in case.get("forecast") or []:
            h = int(row["hour"])
            s = 0.15 * math.sqrt(h - 1)
            q = [p1 * math.exp(_NORM.inv_cdf(t) * s) for t in levels]
            hours_out.append({"hour": h, "q": _clean(q, p1)})
        return {"hours": hours_out}

    forecast_hours = sorted(int(r["hour"]) for r in (case.get("forecast") or [])) \
        or list(range(2, 25))

    centres, sig_dn, sig_up = [], [], []
    for h in forecast_hours:
        pairs = [(lr[h], w) for w, lr in donors if h in lr]
        med = _weighted_quantile(pairs, 0.5)
        tot_w = sum(w for _, w in pairs)
        mean = sum(v * w for v, w in pairs) / tot_w if tot_w else med
        centre = (1.0 - MEAN_BLEND) * med + MEAN_BLEND * mean
        centre = max(math.log(RATIO_LO), min(math.log(RATIO_HI), centre))
        q16 = _weighted_quantile(pairs, 0.15865525393145707)
        q84 = _weighted_quantile(pairs, 0.8413447460685429)
        floor = SIGMA_FLOOR + SIGMA_GROW * math.sqrt(h - 1)
        dn = min(SIGMA_CAP, max(floor, centre - q16))
        up = min(SIGMA_CAP, max(floor, q84 - centre))
        centres.append(centre)
        sig_dn.append(dn)
        sig_up.append(up)

    centres = _smooth(centres, SMOOTH_PASSES)
    sig_dn = _smooth(sig_dn, 1)
    sig_up = _smooth(sig_up, 1)

    # Calibration measured by leave-one-out on big launches: the pooled
    # shape slightly undershoots hour 2 and overshoots the late hours.
    # The correction fades in with first-hour size and is zero for small
    # launches, whose shapes are dominated by unlock timing instead.
    gate = max(0.0, min(1.0, (math.log10(p1) - 4.0) / 1.5))
    if gate > 0.0:
        shrink = 1.0 - gate * (1.0 - SHRINK_BIG)
        for i, h in enumerate(forecast_hours):
            centres[i] = centres[i] * shrink + gate * (
                SHIFT_EARLY * math.exp(-(h - 2) / 1.5)
                - SHIFT_LATE * (1.0 - math.exp(-max(0, h - 3) / 7.0)))

    # Small launches can explode or fizzle, so their honest band is wider
    # than the donor spread alone suggests; a big launch's band is not.
    log10_p1 = math.log10(p1)
    frac = max(0.0, min(1.0, (log10_p1 - 3.5) / 2.0))
    alpha = ALPHA_SMALL + (ALPHA_BIG - ALPHA_SMALL) * frac

    for i, h in enumerate(forecast_hours):
        q = []
        for t in levels:
            z = _NORM.inv_cdf(t)
            sig = sig_up[i] if z > 0 else sig_dn[i]
            q.append(p1 * math.exp(centres[i] + z * sig * alpha))
        hours_out.append({"hour": h, "q": _clean(q, p1)})
    return {"hours": hours_out}


def _clean(q, p1):
    out = []
    prev = 0.0
    for v in q:
        v = float(v)
        if not math.isfinite(v) or v <= 0:
            v = p1
        v = min(1e9, max(1e-6, v))
        v = max(v, prev)
        out.append(round(v, 2))
        prev = out[-1]
    return out


def main():
    in_dir = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    for path in sorted(glob.glob(os.path.join(in_dir, "*.in"))):
        with open(path, "r", encoding="utf-8") as fh:
            case = json.load(fh)
        result = forecast_case(case)
        out_path = os.path.join(out_dir, str(case["id"]) + ".out")
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, separators=(",", ":"))


if __name__ == "__main__":
    main()
