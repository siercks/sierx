// Execute the real corpus against an isolated copy, then enable raw HTML.
// A broken runner or missing dependency is not proof of Markdown protection.
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const web = fileURLToPath(new URL('../', import.meta.url));
const scratch = mkdtempSync(join(web, 'src', 'markdown-proof-'));
const test = 'hostile corpus cannot create active elements, event handlers or unsafe links';
try {
  const source = readFileSync(join(web, 'src/markdown/render.ts'), 'utf8');
  if ((source.match(/html: false/g) ?? []).length !== 1)
    throw new Error('Expected exactly one raw-HTML guard');
  writeFileSync(join(scratch, 'render.test.ts'),
    readFileSync(join(web, 'src/markdown/render.test.ts')));
  function run(renderer, expected) {
    writeFileSync(join(scratch, 'render.ts'), renderer);
    const report = join(scratch, `result-${expected}.json`);
    const result = spawnSync(process.execPath, [
      resolve(web, 'node_modules/vitest/vitest.mjs'), 'run',
      join(scratch, 'render.test.ts'), '--reporter=json', `--outputFile=${report}`,
    ], { cwd: web, encoding: 'utf8' });
    if (result.error) throw result.error;
    const records = JSON.parse(readFileSync(report, 'utf8')).testResults
      .flatMap(suite => suite.assertionResults);
    const assertion = records.find(record => record.title === test);
    if (!assertion || assertion.status !== expected ||
        (expected === 'passed' ? result.status !== 0 : result.status !== 1))
      throw new Error(`Markdown proof did not observe the expected ${expected} assertion`);
  }
  run(source, 'passed');
  run(source.replace('html: false', 'html: true'), 'failed');
  console.log('prove-markdown: real hostile corpus rejects enabled raw HTML');
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
