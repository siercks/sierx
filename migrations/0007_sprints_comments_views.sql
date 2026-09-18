-- SPEC §4.8 Sprints, comments, views. Transcribed verbatim. Sprint bounds are
-- date, not timestamptz (A.3). sprint_item.removed_at is what makes an honest
-- burndown possible — never replace it with a hard delete.
-- +goose Up
CREATE TABLE sprint (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  project_id uuid NOT NULL REFERENCES project(id),
  name       text NOT NULL,
  goal       text,
  starts_on  date NOT NULL,
  ends_on    date NOT NULL,
  state      text NOT NULL CHECK (state IN ('planned','active','closed')),
  CHECK (ends_on > starts_on)
);

CREATE TABLE sprint_item (
  sprint_id  uuid NOT NULL REFERENCES sprint(id),
  item_id    uuid NOT NULL REFERENCES item(id),
  added_at   timestamptz NOT NULL DEFAULT now(),
  removed_at timestamptz,
  PRIMARY KEY (sprint_id, item_id)
);

CREATE TABLE comment (
  id         uuid PRIMARY KEY DEFAULT uuidv7(),
  item_id    uuid NOT NULL REFERENCES item(id),
  author_id  uuid NOT NULL REFERENCES user_account(id),
  body       text NOT NULL,                      -- Markdown
  created_at timestamptz NOT NULL DEFAULT now(),
  edited_at  timestamptz,
  deleted_at timestamptz
);

CREATE TABLE saved_view (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  workspace_id uuid NOT NULL REFERENCES workspace(id),
  owner_id     uuid REFERENCES user_account(id),
  name         text NOT NULL,
  query        text NOT NULL,                    -- an sxq string (§7)
  layout       text NOT NULL CHECK (layout IN ('list','board','timeline','grid')),
  shared       boolean NOT NULL DEFAULT false
);

-- +goose Down
DROP TABLE saved_view;
DROP TABLE comment;
DROP TABLE sprint_item;
DROP TABLE sprint;
