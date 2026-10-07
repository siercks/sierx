import { readFileSync, existsSync, readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
const evidence = JSON.parse(readFileSync('licenses.json', 'utf8'));
const policy = readFileSync('../.licenses-allowlist', 'utf8');
const resolutions = new Map(
  [
    ...policy.matchAll(
      /^resolve\s+(\S+)\s+(\S+)\s+--\s+(.+)$/gm,
    ),
  ].map((m) => [m[1], m[2]]),
);
const packageAllowances = new Map(
  [...policy.matchAll(/^allow-package\s+(\S+)\s+(\S+)\s+--\s+(.+)$/gm)].map(
    (m) => [m[1], { license: m[2], reason: m[3] }],
  ),
);
const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const allowed = new Set(
  [...policy.matchAll(/^allow\s+(\S+)/gm)].map((m) => m[1]),
);
export function accepted(license, component) {
  if (!license) return false;
  return (
    allowed.has(license) || packageAllowances.get(component)?.license === license
  );
}
const entries = Object.entries(lock.packages).filter(([p]) => p !== '');
assert(entries.length > 0, 'Missing npm inventory');
const matchedPackageAllowances = new Set();
function isRegistryPinned(pkg) {
  return (
    pkg.version &&
    pkg.integrity &&
    pkg.resolved?.startsWith('https://registry.npmjs.org/')
  );
}
function isPinnedOrBundled(path, pkg) {
  if (isRegistryPinned(pkg)) return true;
  if (!pkg.version || !pkg.inBundle) return false;
  let parent = path;
  while (parent.includes('/node_modules/')) {
    parent = parent.slice(0, parent.lastIndexOf('/node_modules/'));
    if (isRegistryPinned(lock.packages[parent] ?? {})) return true;
  }
  return false;
}
function assertExactPath(root, relative, component) {
  let current = root;
  for (const segment of relative.split('/')) {
    assert(
      readdirSync(current).includes(segment),
      `License evidence path/case drift: ${component}/${relative}`,
    );
    current = `${current}/${segment}`;
  }
}
for (const [path, pkg] of entries) {
  assert(
    isPinnedOrBundled(path, pkg),
    `Unpinned package: ${path}`,
  );
  const name = path.split('node_modules/').at(-1);
  const component = `npm:${name}@${pkg.version}`;
  const override = evidence[`${name}@${pkg.version}`];
  const resolution = resolutions.get(component);
  let license = pkg.license;
  if (!license && override) {
    assert(
      override.reason && override.file && !override.file.includes('..'),
      'Invalid license evidence',
    );
    assertExactPath(path, override.file, `${name}@${pkg.version}`);
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
  if (packageAllowances.has(component)) matchedPackageAllowances.add(component);
  assert(
    accepted(license, component),
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
for (const component of packageAllowances.keys()) {
  assert(
    matchedPackageAllowances.has(component),
    `Stale package license allowance: ${component}`,
  );
}
console.log(
  `npm licenses: ${entries.length} lockfile components verified (including platform-specific optional packages)`,
);
if (process.argv.includes('--prove')) {
  assert(
    isPinnedOrBundled(
      'node_modules/@tailwindcss/oxide-wasm32-wasi/node_modules/@emnapi/core',
      lock.packages[
        'node_modules/@tailwindcss/oxide-wasm32-wasi/node_modules/@emnapi/core'
      ],
    ),
  );
  assert(
    !isPinnedOrBundled('node_modules/unpinned/node_modules/nested', {
      version: '1.0.0',
      inBundle: true,
    }),
  );
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
  assert(!accepted('Python-2.0', 'npm:argparse@2.0.1'));
  assert(!accepted('GPL-3.0', 'npm:argparse@2.0.1'));
  assert(accepted('MPL-2.0', 'npm:lightningcss@1.32.0'));
  assert(!accepted('MPL-2.0', 'npm:lightningcss@1.32.1'));
  assert(!accepted('MPL-2.0', 'npm:another-package@1.32.0'));
  assert.throws(() =>
    assertExactPath(
      'node_modules/svg-tags',
      'license',
      'svg-tags@1.0.0',
    ),
  );
  console.log('npm license negative controls: PASS');
}
