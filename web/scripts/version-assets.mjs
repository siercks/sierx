import assert from 'node:assert/strict';
import {
  readdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from 'node:fs';
import { extname, join, parse } from 'node:path';

const version = process.env.SIERX_ASSET_VERSION;
if (!version) {
  console.log('asset version: skipped');
  process.exit(0);
}

assert(/^[a-zA-Z0-9_-]+$/.test(version), 'SIERX_ASSET_VERSION must be filename-safe');

const directory = 'dist/assets';
const files = readdirSync(directory);
const renamed = new Map();
for (const file of files) {
  const { name, ext } = parse(file);
  const next = `${name}-${version}${ext}`;
  assert(!files.includes(next), `asset version target already exists: ${next}`);
  renamed.set(file, next);
}

for (const [file, next] of renamed) renameSync(join(directory, file), join(directory, next));

function walk(directoryPath) {
  return readdirSync(directoryPath, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directoryPath, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

for (const path of walk('dist')) {
  if (!['.js', '.css', '.html', '.json'].includes(extname(path))) continue;
  let content = readFileSync(path, 'utf8');
  for (const [file, next] of renamed) content = content.replaceAll(file, next);
  writeFileSync(path, content);
}

console.log(`asset version: renamed ${renamed.size} files with ${version}`);
