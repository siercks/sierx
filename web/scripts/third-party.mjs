import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const manifest = JSON.parse(readFileSync('package.json', 'utf8'));
const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const overrides = JSON.parse(readFileSync('licenses.json', 'utf8'));
function packages(section) {
  const direct = Object.keys(manifest[section] ?? {}).sort();
  const visited = new Set();
  function resolve(from, name) {
    let base = from;
    while (true) {
      const candidate = base ? `${base}/node_modules/${name}` : `node_modules/${name}`;
      if (lock.packages[candidate]) return candidate;
      const nested = base.lastIndexOf('/node_modules/');
      if (nested >= 0) base = base.slice(0, nested);
      else if (base.startsWith('node_modules/')) base = '';
      else return null;
    }
  }
  function visit(path) {
    if (visited.has(path)) return;
    const record = lock.packages[path];
    if (!record?.version) throw new Error(`Missing locked package metadata for ${path}`);
    visited.add(path);
    for (const name of Object.keys({ ...record.dependencies, ...record.optionalDependencies, ...record.peerDependencies })) {
      const dependency = resolve(path, name);
      if (dependency) visit(dependency);
    }
  }
  for (const name of direct) {
    const path = resolve('', name);
    if (!path) throw new Error(`Missing locked package metadata for ${name}`);
    visit(path);
  }
  return [...visited].sort().map((path) => {
    const record = lock.packages[path];
    const name = path.split('node_modules/').at(-1);
    const override = overrides[`${name}@${record.version}`];
    const license = record.license ?? override?.license ?? 'Unknown';
    if (license === 'Unknown') throw new Error(`Missing license metadata for ${name}@${record.version}`);
    return { name, version: record.version, license, direct: direct.includes(name), purpose: section === 'dependencies' ? 'Bundled application runtime dependency' : 'Build and validation dependency' };
  });
}
const fonts = JSON.parse(readFileSync('design/fonts/fonts.json', 'utf8'));
const inventory = {
  generated_from: ['package.json', 'package-lock.json', 'licenses.json', 'design/fonts/fonts.json'],
  runtime: packages('dependencies'),
  build_tools: packages('devDependencies'),
  fonts: {
    bundled: (fonts.built ?? []).map(({ family, license, files }) => ({ family, license, delivery: 'Built locally and served from this instance', files: files.map((file) => file.file) })),
    third_party: (fonts.families ?? []).map(({ family, license, files }) => ({ family, license, delivery: 'Bundled locally', files: files.map((file) => file.file) })),
    device_fallbacks: 'System fonts selected by the visitor’s device; not downloaded by Sierx.',
  },
  operator_services: 'Gateway, certificate, mail, backup, and other external services are selected and configured independently by each instance operator. See /privacy for this instance’s configured description.',
};
writeFileSync(join('dist', 'third-party.json'), `${JSON.stringify(inventory, null, 2)}\n`);
console.log(`third-party inventory: ${inventory.runtime.length} runtime packages and ${inventory.build_tools.length} build tools recorded`);
