import { readFileSync, readdirSync } from 'node:fs';
import postcss from 'postcss';
import assert from 'node:assert/strict';
import { violations } from './style-rules.mjs';
import stylelint from 'stylelint';
import { fileURLToPath } from 'node:url';
const config = {
  plugins: [fileURLToPath(new URL('./style-rules.mjs', import.meta.url))],
  rules: { 'sierx/token-and-focus': true },
};
const result = await stylelint.lint({ files: 'src/themes/*.css', config });
assert(!result.errored, result.report);
for (const file of readdirSync('src/themes').filter((f) => f.endsWith('.css')))
  assert.deepEqual(
    violations(postcss.parse(readFileSync('src/themes/' + file, 'utf8'))),
    [],
    file,
  );
if (process.argv.includes('--prove')) {
  assert.equal(violations(postcss.parse('a {outline: none}')).length, 1);
  assert.equal(
    violations(postcss.parse('a {background:var(--status-open)}')).length,
    1,
  );
  console.log('style/focus negative controls: PASS');
}
console.log('style/focus gates: PASS');
