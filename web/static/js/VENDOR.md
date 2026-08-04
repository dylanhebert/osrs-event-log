# Vendored third-party JavaScript

| file | library | version | licence | source |
|---|---|---|---|---|
| `chart.umd.min.js` | Chart.js | 4.4.7 | MIT | https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js |

Committed rather than loaded from a CDN so the site has no third-party runtime
dependency and works with no outbound network access.

This is the full UMD build, roughly 200 KB on disk and roughly 68 KB over the
wire once Caddy gzips it. Chart.js can tree-shake down to about 60 KB, but only
through a bundler, and this project deliberately has no build step. Paying ~8 KB
gzipped to keep `git pull` as the entire deployment process is the trade.

No date adapter is vendored. `history-chart.js` uses a **linear** x axis over
epoch milliseconds with a tick formatter, which keeps real time spacing without
needing `chartjs-adapter-date-fns` and its `date-fns` dependency.

To upgrade:

```bash
curl -sSL -o web/static/js/chart.umd.min.js \
  https://cdn.jsdelivr.net/npm/chart.js@<version>/dist/chart.umd.min.js
```

Then reload a player page that has a chart and confirm the line is still
**stepped**: a smooth or straight-line join would draw XP values the player
never had.
