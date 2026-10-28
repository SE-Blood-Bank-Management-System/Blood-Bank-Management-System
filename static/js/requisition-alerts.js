/* Staff alert only: background GET polling never changes a request or reloads a form. */
(() => {
  'use strict';
  const alert = document.getElementById('stat-request-alert');
  if (!alert) return;
  const message = alert.querySelector('[data-stat-message]');
  const interval = 5000;
  let timer;
  let running = false;
  let lastSignature = '';

  async function refresh() {
    clearTimeout(timer);
    if (running || document.hidden) return;
    running = true;
    try {
      const response = await fetch(alert.dataset.endpoint, {
        credentials: 'same-origin', cache: 'no-store', headers: {Accept: 'application/json'}
      });
      if (response.status === 401 || response.status === 403) {
        // Session/role changed. Do not reveal old clinical alerts or keep polling.
        alert.hidden = true;
        return;
      }
      if (!response.ok) throw new Error('Alert service unavailable');
      const data = await response.json();
      if (!Number.isInteger(data.count) || data.count < 0) throw new Error('Invalid alert response');
      const signature = `${data.count}:${data.latest_id}:${data.latest_updated_at}`;
      if (signature !== lastSignature) {
        message.textContent = `${data.count} pending Emergency / STAT request${data.count === 1 ? '' : 's'} require review.`;
        lastSignature = signature;
      }
      alert.hidden = data.count === 0;
    } catch (error) {
      message.textContent = 'Live STAT updates are unavailable. Open the review queue to check for urgent requests.';
      lastSignature = '';
      alert.hidden = false;
    } finally {
      running = false;
    }
    timer = setTimeout(refresh, interval);
  }

  document.addEventListener('visibilitychange', () => {
    clearTimeout(timer);
    if (!document.hidden) refresh();
  });
  window.addEventListener('pagehide', () => clearTimeout(timer));
  refresh();
})();
