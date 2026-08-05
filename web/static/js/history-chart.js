/* History chart.
 *
 * THREE DELIBERATE CHOICES, all about not lying with the picture:
 *
 * 1. POLLED POINTS ARE STEPPED. A history row is written only when a value
 *    actually changes, so between two of them the value was CONSTANT, not
 *    sliding. A smooth or straight join would draw XP the player never had.
 *
 * 2. RECOVERED POINTS ARE NOT. Everything before the storage migration was
 *    reconstructed from the text of old Discord posts, so a point exists only
 *    where a message happened to be posted: every level below 99, but only the
 *    occasional threshold above it. Between two of those the player was
 *    climbing, often for months. Stepping them would draw a flat year followed
 *    by a cliff, which is a bigger lie than the straight line.
 *
 *    So the series is split in two and each half is drawn the way its own data
 *    warrants. They meet at the boundary point, which belongs to both.
 *
 * 3. A LINEAR x axis over epoch milliseconds, not a category axis.
 *    Chart.js time scales need a date adapter, which is a second library to
 *    vendor. A category axis would avoid that but would space unequal gaps
 *    equally, so a year of silence and twenty minutes would look identical.
 *    A linear axis with a tick formatter keeps real time spacing with no extra
 *    dependency.
 */

function fmtDate(ms) {
  const d = new Date(ms);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

function fmtDateTime(ms) {
  const d = new Date(ms);
  return d.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

function fmtNum(n) {
  return Number(n).toLocaleString();
}

function initHistoryChart(options) {
  const canvas = document.getElementById('history');
  const picker = document.getElementById('series');
  const note = document.getElementById('chart-note');
  if (!canvas || !picker) return;

  const css = getComputedStyle(document.body);
  const line = css.getPropertyValue('--accent').trim() || '#7cc4ff';
  const grid = css.getPropertyValue('--grid').trim() || 'rgba(255,255,255,.08)';
  const ink = css.getPropertyValue('--ink-dim').trim() || '#9aa4b2';

  let chart = null;

  function render(data) {
    const points = data.points.map(p => ({ x: p.t, y: p.y, r: !!p.r }));

    // Recovered points all predate the migration and polled ones all follow
    // it, so the split is a single boundary rather than an interleaving. The
    // boundary point is included in BOTH halves, otherwise the line has a
    // visible gap exactly where the two meet.
    const lastRecovered = points.reduce(
      (found, p, i) => (p.r ? i : found), -1);
    const recovered = lastRecovered >= 0
      ? points.slice(0, lastRecovered + 2) : [];
    const polled = lastRecovered >= 0
      ? points.slice(lastRecovered + 1) : points;

    if (note) {
      if (points.length < 2) {
        note.textContent = 'Only one value recorded for this series so far.';
      } else {
        const first = points[0].y, last = points[points.length - 1].y;
        const gained = last - first;
        const recoveredCount = points.filter(p => p.r).length;
        note.textContent =
          points.length + ' recorded values, ' + fmtDate(points[0].x) +
          ' to ' + fmtDate(points[points.length - 1].x) + '. ' +
          (gained > 0 ? '+' + fmtNum(gained) + ' ' + data.unit + ' over that span.'
                      : 'No net change over that span.') +
          (recoveredCount
            ? ' ' + fmtNum(recoveredCount) + ' of them recovered from old ' +
              'Discord posts, so they are sparser than the polled ones.'
            : '');
      }
    }

    const datasets = [];
    if (recovered.length > 1) {
      datasets.push({
        label: data.label + ' ' + data.unit + ' (recovered)',
        data: recovered,
        stepped: false,
        tension: 0,
        borderColor: line,
        backgroundColor: line,
        borderWidth: 2,
        // Dashed, so the picture says outright that this half is
        // reconstructed rather than measured.
        borderDash: [5, 4],
        pointRadius: recovered.length > 200 ? 0 : 2,
        pointHoverRadius: 5,
        fill: false
      });
    }
    if (polled.length) {
      datasets.push({
        label: data.label + ' ' + data.unit,
        data: polled,
        stepped: true,
        tension: 0,
        borderColor: line,
        backgroundColor: line,
        borderWidth: 2,
        pointRadius: polled.length > 200 ? 0 : 3,
        pointHoverRadius: 5,
        fill: false
      });
    }

    const config = {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'nearest', intersect: false },
        scales: {
          x: {
            type: 'linear',
            grid: { color: grid },
            ticks: {
              color: ink,
              maxTicksLimit: 8,
              callback: value => fmtDate(value)
            }
          },
          y: {
            grid: { color: grid },
            ticks: { color: ink, callback: value => fmtNum(value) }
          }
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: items => fmtDateTime(items[0].parsed.x),
              label: item => fmtNum(item.parsed.y) + ' ' + data.unit
            }
          }
        }
      }
    };

    if (chart) chart.destroy();
    chart = new Chart(canvas.getContext('2d'), config);
  }

  function load(value) {
    const [kind, name] = value.split(/:(.+)/);
    const url = options.endpoint + '?' +
      (kind === 'activity' ? 'activity=' : 'skill=') + encodeURIComponent(name);
    fetch(url, { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(render)
      .catch(() => {
        if (note) note.textContent = 'Could not load that series.';
      });
  }

  picker.addEventListener('change', () => load(picker.value));
  load(options.initial || picker.value);
}
