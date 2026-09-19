import { readFileSync, existsSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
const evidence = JSON.parse(readFileSync('licenses.json', 'utf8'));
const resolutions = new Map(
  [
    ...readFileSync('../.licenses-allowlist', 'utf8').matchAll(
      /^resolve\s+(\S+)\s+(\S+)\s+--\s+(.+)$/gm,
    ),
  ].map((m) => [m[1], m[2]]),
);
const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const policy = readFileSync('../.licenses-allowlist', 'utf8');
const allowed = new Set(
  [...policy.matchAll(/^allow\s+(\S+)/gm)].map((m) => m[1]),
);
export function accepted(license) {
  if (!license) return false;
  return allowed.has(license);
}
const entries = Object.entries(lock.packages).filter(([p]) => p !== '');
assert(entries.length > 0, 'Missing npm inventory');
for (const [path, pkg] of entries) {
  assert(
    pkg.version &&
      pkg.integrity &&
      pkg.resolved?.startsWith('https://registry.npmjs.org/'),
    `Unpinned package: ${path}`,
  );
  const name = path.split('node_modules/').at(-1);
  const override = evidence[`${name}@${pkg.version}`];
  const resolution = resolutions.get(`npm:${name}@${pkg.version}`);
  let license = pkg.license;
  if (!license && override) {
    assert(
      override.reason && override.file && !override.file.includes('..'),
      'Invalid license evidence',
    );
    const actual = createHash('sha256')
      .update(readFileSync(`${path}/${override.file}`))
      .digest('hex');
    assert.equal(actual, override.sha256, `License evidence drift: ${name}`);
    license = override.license;
  }
  if (resolution) {
    assert(
      license?.includes(' OR ') &&
        license.replace(/[()]/g, '').split(' OR ').includes(resolution),
      `Resolution is not an offered license: ${name}`,
    );
    license = resolution;
  }
  assert(
    accepted(license),
    `${path}: license ${license ?? 'UNKNOWN'} is not approved`,
  );
  if (!pkg.optional) {
    assert(
      existsSync(`${path}/package.json`),
      `Missing installed package ${path}`,
    );
    assert.equal(
      JSON.parse(readFileSync(`${path}/package.json`)).version,
      pkg.version,
      `Version drift ${path}`,
    );
  }
}
console.log(
  `npm licenses: ${entries.length} lockfile components verified (including platform-specific optional packages)`,
);
if (process.argv.includes('--prove')) {
  for (const license of [
    undefined,
    'AGPL-3.0',
    'MPL-2.0',
    'SSPL-1.0',
    'BSL-1.1',
    'UNKNOWN',
    'MIT OR GPL-3.0',
    'MIT AND MPL-2.0',
  ])
    assert(!accepted(license));
  console.log('npm license negative controls: PASS');
}
