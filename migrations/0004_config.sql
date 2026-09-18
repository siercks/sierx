-- SPEC §4.3 Configuration ⚠. status and item_type rows are IMMUTABLE after
-- insert (§5.6); the triggers that enforce it arrive in 0008 (task 0.5).
-- Additions from BUILD task 0.4's table: UNIQUE (project_id, id) on status and
-- item_type so item can carry project-scoped composite FKs (ADR-012).
-- +goose Up
CREATE TABLE project_config (
  project_id  uuid NOT NULL REFERENCES project(id),
  version     int  NOT NULL,
  source_yaml text,                              -- verbatim, for round-trip export
  applied_at  timestamptz NOT NULL DEFAULT now(),
  applied_by  uuid REFERENCES user_account(id),
  PRIMARY KEY (project_id, version)
);

-- IMMUTABLE after insert. Never UPDATE key, name, or category. (§5.6)
CREATE TABLE status (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,
  name       text NOT NULL,
  category   text NOT NULL CHECK (category IN ('open','active','done','cancelled')),
  CONSTRAINT status_project_id_uniq UNIQUE (project_id, id)          -- ADR-012
);

-- IMMUTABLE after insert.
CREATE TABLE item_type (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,
  name       text NOT NULL,
  level      int  NOT NULL,                      -- 0 = most granular
  is_idea    boolean NOT NULL DEFAULT false,
  CONSTRAINT item_type_project_id_uniq UNIQUE (project_id, id)       -- ADR-012
);

CREATE TABLE config_status (
  project_id    uuid NOT NULL,
  version       int  NOT NULL,
  status_id     uuid NOT NULL REFERENCES status(id),
  display_order int  NOT NULL,
  PRIMARY KEY (project_id, version, status_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE config_type (
  project_id        uuid NOT NULL,
  version           int  NOT NULL,
  item_type_id      uuid NOT NULL REFERENCES item_type(id),
  initial_status_id uuid NOT NULL REFERENCES status(id),
  PRIMARY KEY (project_id, version, item_type_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE config_transition (
  project_id     uuid NOT NULL,
  version        int  NOT NULL,
  from_status_id uuid NOT NULL REFERENCES status(id),
  to_status_id   uuid NOT NULL REFERENCES status(id),
  requires       jsonb NOT NULL DEFAULT '[]',    -- e.g. ["assignee","points"]
  PRIMARY KEY (project_id, version, from_status_id, to_status_id),
  FOREIGN KEY (project_id, version) REFERENCES project_config(project_id, version)
);

CREATE TABLE field_def (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  key        text NOT NULL,                      -- the jsonb key in item.fields
  name       text NOT NULL,
  data_type  text NOT NULL CHECK (data_type IN
               ('text','number','date','select','multiselect','user','url','bool')),
  options    jsonb NOT NULL DEFAULT '[]',
  UNIQUE (project_id, key)
);

-- +goose Down
DROP TABLE field_def;
DROP TABLE config_transition;
DROP TABLE config_type;
DROP TABLE config_status;
DROP TABLE item_type;
DROP TABLE status;
DROP TABLE project_config;
