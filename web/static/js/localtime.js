/* Show event times in the reader's own timezone.
 *
 * The server renders UTC, because it has no idea where the reader is and a
 * silently wrong local time is worse than a labelled correct one. The browser
 * does know, so it rewrites what the server sent.
 *
 * PROGRESSIVE ENHANCEMENT, DELIBERATELY. The page is already correct before
 * this runs: every <time> carries a readable UTC string as its text and the
 * machine-readable instant in its datetime attribute. If this file fails to
 * load, or scripting is off, the times are still right and still labelled --
 * they are just not local. Nothing here is load-bearing.
 *
 * Same reasoning as the navigation menu, which is a checkbox rather than a
 * script for the same reason.
 */

(function () {
  'use strict';

  // Long enough ago that the date matters more than the clock. Inside a day,
  // seeing "19:16" for something that happened this evening reads better than
  // a full date; beyond it, the date is the whole point.
  var ONE_DAY = 24 * 60 * 60 * 1000;

  function formatter(opts) {
    try {
      return new Intl.DateTimeFormat(undefined, opts);
    } catch (e) {
      return null;
    }
  }

  var withDate = formatter({
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
  });
  var timeOnly = formatter({
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
  });

  function localise(el) {
    // Running twice would append the UTC string to the title a second time.
    if (el.className.indexOf('is-local') !== -1) return;

    var iso = el.getAttribute('datetime');
    if (!iso) return;
    var when = new Date(iso);
    if (isNaN(when.getTime())) return;

    // Absolute difference, so a timestamp a few seconds into the future from
    // ordinary clock skew is treated as "now" rather than as a distant date.
    var fmt = Math.abs(Date.now() - when.getTime()) < ONE_DAY && timeOnly
      ? timeOnly : withDate;
    if (!fmt) return;

    // The UTC value the server rendered moves to the hover, alongside the
    // relative form already there, so the canonical instant is never lost.
    var previous = el.getAttribute('title');
    var utc = el.textContent.trim();
    el.title = previous ? previous + ' · ' + utc : utc;
    el.textContent = fmt.format(when);
    el.className = el.className ? el.className + ' is-local' : 'is-local';
  }

  function run(root) {
    var nodes = (root || document).querySelectorAll('time[datetime]');
    for (var i = 0; i < nodes.length; i++) localise(nodes[i]);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { run(); });
  } else {
    run();
  }
})();
