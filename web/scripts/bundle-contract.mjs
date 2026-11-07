import assert from 'node:assert/strict';

// Inspect the transitive entry graph, including code emitted into shared chunks.
// These editors/views are intentionally lazy under ADR-031.
export function assertLazyModules(scripts, modules) {
  for (const file of scripts) {
    assert(Array.isArray(modules[file]), `Missing module inventory for ${file}`);
    for (const raw of modules[file]) {
      const module = raw.replaceAll('\\', '/');
      assert(
        !/markdown-it|src\/routes\/(?:Item|Login|Board|Account[^/]*)\.tsx|src\/components\/(?:AvatarEditor|DatePicker|Calendar)[^/]*\.tsx|node_modules\/(?:@dnd-kit|@hello-pangea\/dnd|react-easy-crop)\//.test(module),
        `${module} entered eager graph`,
      );
    }
  }
}
