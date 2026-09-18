-- SPEC §4.4 Items. Transcribed verbatim. search_tsv is STORED (PG 18 defaults
-- generated columns to virtual, which cannot be indexed). Path labels are the
-- items' own UUIDs. Additions from BUILD task 0.4's table:
--   item_project_rank_uniq  UNIQUE (project_id, rank) DEFERRABLE   (ADR-003)
--   composite FKs tying status, type, and config version to the item's own
--   project                                                          (ADR-012)
-- +goose Up
CREATE TABLE item (
  id             uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id   uuid NOT NULL REFERENCES workspace(id),
  project_id     uuid NOT NULL REFERENCES project(id),
  key            text NOT NULL,                  -- 'SRX-142'; immutable for life (§A.1)
  item_type_id   uuid NOT NULL REFERENCES item_type(id),
  status_id      uuid NOT NULL REFERENCES status(id),
  config_version int  NOT NULL,
  parent_id      uuid REFERENCES item(id),
  path           ltree NOT NULL,                 -- ancestry incl. self (§5.3)
  title          text NOT NULL CHECK (length(title) BETWEEN 1 AND 500),
  body           text,                           -- Markdown
  assignee_id    uuid REFERENCES user_account(id),
  points         numeric(6,2),
  start_date     date,                            -- date, NOT timestamptz (§A.3)
  due_date       date,
  rank           text NOT NULL,                  -- LexoRank (§5.5)
  fields         jsonb NOT NULL DEFAULT '{}',
  version        int  NOT NULL DEFAULT 1,        -- optimistic concurrency (§5.4)
  change_seq     bigint NOT NULL,                -- §5.1
  origin_id      uuid NOT NULL,                  -- §5.7
  origin_seq     bigint,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz,
  search_tsv     tsvector GENERATED ALWAYS AS (
                   to_tsvector('english', title || ' ' || coalesce(body, ''))
                 ) STORED,
  UNIQUE (workspace_id, key),
  CONSTRAINT item_project_rank_uniq UNIQUE (project_id, rank)
    DEFERRABLE INITIALLY IMMEDIATE,                                          -- ADR-003
  CONSTRAINT item_status_same_project
    FOREIGN KEY (project_id, status_id) REFERENCES status(project_id, id),   -- ADR-012
  CONSTRAINT item_type_same_project
    FOREIGN KEY (project_id, item_type_id) REFERENCES item_type(project_id, id), -- ADR-012
  CONSTRAINT item_config_version_exists
    FOREIGN KEY (project_id, config_version)
      REFERENCES project_config(project_id, version)                          -- ADR-012
);

CREATE INDEX item_path_gist  ON item USING gist (path);
CREATE INDEX item_ws_seq     ON item (workspace_id, change_seq);
CREATE INDEX item_proj_stat  ON item (project_id, status_id) WHERE deleted_at IS NULL;
CREATE INDEX item_parent     ON item (parent_id);
CREATE INDEX item_assignee   ON item (assignee_id) WHERE deleted_at IS NULL;
CREATE INDEX item_fields_gin ON item USING gin (fields jsonb_path_ops);
CREATE INDEX item_search     ON item USING gin (search_tsv);

-- +goose Down
DROP TABLE item;
