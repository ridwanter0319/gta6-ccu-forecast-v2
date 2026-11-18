# GTA VI Twitch CCU Forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/ridwanter0319/gta6-ccu-forecast-v2/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/ridwanter0319/gta6-ccu-forecast-v2/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for the make.fun bounty
[gta6-twitch-ccu-forecast-01](https://make.fun/bounty/gta6-twitch-ccu-forecast-01):
forecast how many people watch Grand Theft Auto VI live on Twitch in each
hour of its release day (2026-11-19 UTC), hours 2–24, as five quantiles
(0.05, 0.25, 0.5, 0.75, 0.95) per hour. Scoring is mean pinball loss on the
log scale; lower is better.

## Method

Scale-and-shape over comparable launches:

1. **Donor shapes.** Every past big launch in the case file (the
   `comparables`) contributes a release-day ratio curve: its viewers at
   hour *h* divided by its own first-hour viewers. The target category's
   pre-release history entry is not a launch and is skipped, as are donors
   whose first hour is too small to give a stable shape.
2. **Similarity weights.** A donor counts more when its first-hour viewers
   and channel count are close to this case's (log-distance kernels), when
   its unlock style matches (rolling midnight vs. one global unlock time,
   read from the unlock notes), and less when it also launched on PC, since
   the forecast targets are console-first launches.
3. **Centre.** Per hour, the weighted median of the donor log-ratios is
   blended with the weighted mean, capped, and smoothed across hours. The
   median forecast is the case's first-hour viewers times that multiplier.
   A size-gated calibration, measured by leave-one-out over the donor pool,
   nudges big launches' centres up at hour 2 and down late in the day.
4. **Quantiles.** The spread comes from the weighted 16th/84th percentiles
   of the donor log-ratios around the centre, with separate widths above
   and below, a floor that grows slowly with the hour, and a size-dependent
   multiplier: small launches get a much wider band than the raw donor
   spread, big launches a slightly narrower one. All constants were tuned
   by leave-one-out cross-validation over the comparables pool.

The program is deterministic, uses only the Python 3.13 standard library,
needs no network, and runs in well under a second per case.

## Run

```sh
MAKEFUN_INPUT_DIR=/path/to/input MAKEFUN_OUTPUT_DIR=/path/to/output python3 main.py
```

It reads every `*.in` case file in `$MAKEFUN_INPUT_DIR` (default `/input`)
and writes one `<id>.out` forecast per case to `$MAKEFUN_OUTPUT_DIR`
(default `/output`), in exactly the format the bounty specifies:
`{"hours":[{"hour":2,"q":[q05,q25,q50,q75,q95]}, ...]}` for hours 2–24.

## License

MIT — see [LICENSE](LICENSE).
