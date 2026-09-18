-- internal/store/seed/config.sql — the seed's project configuration, inserted
-- as SQL because there is no YAML tooling until phase 7 (§2.1).
--
-- This mirrors SPEC §8.1's example exactly, so phase 7 has a known-good
-- round-trip target: exporting the seeded project must reproduce that file.
-- Two deliberate expansions:
--
--   ADR-011: {from: "*", to: dropped} is stored as one config_transition row
--   per live status, because "*" in a stored row would have to be interpreted
--   at every read. The wildcard is a file-format convenience; the database
--   holds the enumeration. Phase 7's exporter re-collapses a full fan-in to
--   "*" — which is why the fan-in must be complete here.
--
--   §8.1 has no dropped -> * transitions: dropped is terminal. The fan-in
--   covers every status except dropped itself (no self-transition).
--
-- Parameters, bound by the seed generator:
--   $1 project_id, $2 config version
--
-- Ordering matters: status and item_type rows first (they are referenced by
-- key below), then the config_* rows for the version.

-- statuses (§8.1 statuses:)
INSERT INTO status (project_id, key, name, category) VALUES
  ($1, 'todo',    'To Do',       'open'),
  ($1, 'doing',   'In Progress', 'active'),
  ($1, 'review',  'In Review',   'active'),
  ($1, 'done',    'Done',        'done'),
  ($1, 'dropped', 'Dropped',     'cancelled');

-- types (§8.1 types:) — level 0 is the most granular (§4.3). §8.1 numbers
-- story/bug at 1, epic 2, initiative 3; kept verbatim so the round-trip
-- matches, with 0 unused in this project.
INSERT INTO item_type (project_id, key, name, level, is_idea) VALUES
  ($1, 'initiative', 'Initiative', 3, false),
  ($1, 'epic',       'Epic',       2, false),
  ($1, 'story',      'Story',      1, false),
  ($1, 'bug',        'Bug',        1, false);

-- fields (§8.1 fields:)
INSERT INTO field_def (project_id, key, name, data_type, options) VALUES
  ($1, 'impact',    'Impact',    'number', '[]'),
  ($1, 'component', 'Component', 'select', '["api","web","infra"]');

-- display order follows the file's order (§8.1 statuses:)
INSERT INTO config_status (project_id, version, status_id, display_order)
SELECT $1, $2, s.id, x.ord
  FROM (VALUES ('todo',1), ('doing',2), ('review',3), ('done',4), ('dropped',5))
         AS x(key, ord)
  JOIN status s ON s.project_id = $1 AND s.key = x.key;

-- initial_status (§8.1 initial_status:) — every type starts at todo
INSERT INTO config_type (project_id, version, item_type_id, initial_status_id)
SELECT $1, $2, t.id, s.id
  FROM item_type t
  JOIN status s ON s.project_id = $1 AND s.key = 'todo'
 WHERE t.project_id = $1;

-- transitions (§8.1 transitions:), explicit arcs
INSERT INTO config_transition (project_id, version, from_status_id, to_status_id, requires)
SELECT $1, $2, f.id, t.id, x.requires::jsonb
  FROM (VALUES
         ('todo',   'doing',  '["assignee"]'),
         ('doing',  'review', '[]'),
         ('review', 'done',   '["assignee"]')
       ) AS x(from_key, to_key, requires)
  JOIN status f ON f.project_id = $1 AND f.key = x.from_key
  JOIN status t ON t.project_id = $1 AND t.key = x.to_key;

-- transitions: {from: "*", to: dropped} expanded per ADR-011
INSERT INTO config_transition (project_id, version, from_status_id, to_status_id, requires)
SELECT $1, $2, f.id, d.id, '[]'::jsonb
  FROM status f
  JOIN status d ON d.project_id = $1 AND d.key = 'dropped'
 WHERE f.project_id = $1 AND f.key <> 'dropped';
