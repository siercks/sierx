// Fixture-only readiness for slow emulation. Never retries a write or bypasses
// recovery verification: every successful read still comes from the real server.
const recoveryMessage = 'Service unavailable pending operator recovery verification.';
const maxRetries = 5;

async function recoveryResponse(response) {
  if (response.status() !== 503 || response.request().method() !== 'GET') return false;
  const headers = response.headers();
  if (!(headers['content-type'] ?? '').startsWith('text/plain')) return false;
  if (Number(headers['content-length']) > 4096) return false;
  try {
    const body = await response.text();
    return body.length <= 4096 && body.trim() === recoveryMessage;
  } catch { return false; }
}

function unavailable(status, recovery = false) {
  const error = new Error(recovery ? 'Bounded fixture recovery reads remained unavailable' : 'Fixture read returned HTTP ' + status);
  error.code = recovery ? 'SIERX_RECOVERY_UNAVAILABLE' : 'SIERX_READ_HTTP_STATUS';
  error.httpStatus = status;
  return error;
}

export function createRecoveryNavigator(page, { emulated, origin, navigationTimeout = emulated ? 600000 : 30000 }) {
  if (typeof emulated !== 'boolean') throw new Error('Explicit fixture timing mode required');
  if (!Number.isInteger(navigationTimeout) || navigationTimeout <= 0) throw new Error('Bounded navigation timeout required');
  let retries = 0;
  async function read(action) {
    const deadline = Date.now() + 600000;
    for (;;) {
      const remaining = deadline - Date.now();
      if (remaining <= 0) throw unavailable(503, true);
      let rejected = false;
      const pending = new Set();
      const observe = (response) => {
        if (response.status() !== 503 || response.request().method() !== 'GET' || new URL(response.url()).origin !== origin) return;
        const check = recoveryResponse(response).then((value) => { rejected ||= value; });
        pending.add(check);
        void check.finally(() => pending.delete(check));
      };
      if (emulated) page.context().on('response', observe);
      try {
        const response = await action(Math.min(navigationTimeout, remaining));
        await Promise.all([...pending]);
        const status = response?.status() ?? 0;
        if (status === 200 && !rejected) return response;
        if (!emulated || !rejected || ![200, 503].includes(status)) throw unavailable(status);
        if (retries === maxRetries || Date.now() >= deadline) throw unavailable(503, true);
        retries++;
      } finally {
        if (emulated) page.context().off('response', observe);
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  function target(url) {
    const value = new URL(url);
    if (value.origin !== origin || value.username || value.password) throw new Error('Fixture recovery reads require their exact origin');
    return value.href;
  }
  return {
    goto: (url) => read((timeout) => page.goto(target(url), { timeout })),
    reload: () => { target(page.url()); return read((timeout) => page.reload({ timeout })); },
    get retries() { return retries; },
  };
}
