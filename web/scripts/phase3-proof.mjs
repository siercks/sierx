import assert from 'node:assert/strict';
import { assertLazyModules } from './bundle-contract.mjs';

const scripts = new Set(['entry.js', 'shared.js']);
const baseline = {
  'entry.js': ['src/main.tsx', 'src/routes/List.tsx'],
  'shared.js': ['node_modules/react/index.js'],
  'board.js': ['src/routes/Board.tsx'],
};
assertLazyModules(scripts, baseline);
for (const module of [
  'src/routes/Board.tsx', 'src/routes/Account.tsx',
  'src/routes/AccountPreferences.tsx', 'src/components/AvatarEditor.tsx',
  'src/components/DatePicker.tsx', 'src/components/Calendar.tsx',
  'node_modules/@dnd-kit/core/dist/core.js',
  'node_modules/react-easy-crop/index.js',
]) {
  for (const file of scripts) {
    const planted = structuredClone(baseline);
    planted[file].push(module);
    assert.throws(() => assertLazyModules(scripts, planted), /entered eager graph/);
    planted[file] = [module.replaceAll('/', '\\')];
    assert.throws(() => assertLazyModules(scripts, planted), /entered eager graph/);
  }
}
assert.throws(() => assertLazyModules(scripts, {}), /Missing module inventory/);
console.log('Phase 3 lazy-graph proofs: direct/shared/Windows-path violations rejected');
