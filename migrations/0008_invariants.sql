-- SPEC §5 invariants enforced in the database (BUILD task 0.5).
--   §5.6 / A.6  status and item_type are immutable in key, name, category, level
--   §5.3        no reparent that makes an item its own ancestor; depth ≤ 8
--               (also enforced in the API); path ends with the item's own id
--   task 0.5    path's penultimate label equals parent_id; NULL parent_id
--               means a single-label path — so path and parent_id cannot drift
-- These are checks, not maintenance: nothing here writes item, item_rollup, or
-- change_event (ADR-001, ADR-005).
-- +goose Up
-- +goose StatementBegin
CREATE FUNCTION status_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.key      IS DISTINCT FROM OLD.key
  OR NEW.name     IS DISTINCT FROM OLD.name
  OR NEW.category IS DISTINCT FROM OLD.category THEN
    RAISE EXCEPTION 'status % is immutable: key, name, category cannot change (SPEC §5.6); insert a new row and a new config version',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
-- +goose StatementEnd

-- +goose StatementBegin
CREATE FUNCTION item_type_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.key   IS DISTINCT FROM OLD.key
  OR NEW.name  IS DISTINCT FROM OLD.name
  OR NEW.level IS DISTINCT FROM OLD.level THEN
    RAISE EXCEPTION 'item_type % is immutable: key, name, level cannot change (SPEC §5.6); insert a new row and a new config version',
      OLD.id USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END $$;
-- +goose StatementEnd

CREATE TRIGGER status_immutable_trg
  BEFORE UPDATE ON status FOR EACH ROW EXECUTE FUNCTION status_immutable();
CREATE TRIGGER item_type_immutable_trg
  BEFORE UPDATE ON item_type FOR EACH ROW EXECUTE FUNCTION item_type_immutable();

-- +goose StatementBegin
CREATE FUNCTION item_path_check() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  depth       int := nlevel(NEW.path);
  parent_path ltree;
BEGIN
  -- §5.3: maximum depth 8 (a root item has depth 1)
  IF depth > 8 THEN
    RAISE EXCEPTION 'item % would be at depth %, maximum is 8 (SPEC §5.3)',
      NEW.id, depth USING ERRCODE = 'check_violation';
  END IF;

  -- §5.3: path always ends with the item's own id
  IF ltree2text(subpath(NEW.path, -1)) <> NEW.id::text THEN
    RAISE EXCEPTION 'item % path % does not end with its own id (SPEC §5.3)',
      NEW.id, NEW.path USING ERRCODE = 'check_violation';
  END IF;

  -- task 0.5: path and parent_id must agree
  IF NEW.parent_id IS NULL THEN
    IF depth <> 1 THEN
      RAISE EXCEPTION 'item % has no parent but path % has % labels; a root path is the id alone',
        NEW.id, NEW.path, depth USING ERRCODE = 'check_violation';
    END IF;
  ELSE
    IF depth < 2 OR ltree2text(subpath(NEW.path, -2, 1)) <> NEW.parent_id::text THEN
      RAISE EXCEPTION 'item % path % disagrees with parent_id % (penultimate label must be the parent)',
        NEW.id, NEW.path, NEW.parent_id USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  -- §5.3: reject a reparent that would make the item its own ancestor.
  -- Checked only when parent_id changes: a subtree rewrite in one statement
  -- (§5.3) leaves descendants' parent_id untouched and must not be re-judged
  -- row by row against paths that are mid-rewrite.
  IF TG_OP = 'UPDATE' AND NEW.parent_id IS NOT NULL
     AND NEW.parent_id IS DISTINCT FROM OLD.parent_id THEN
    SELECT path INTO parent_path FROM item WHERE id = NEW.parent_id;
    IF parent_path <@ OLD.path THEN
      RAISE EXCEPTION 'reparenting item % under % would make it its own ancestor (SPEC §5.3)',
        NEW.id, NEW.parent_id USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  RETURN NEW;
END $$;
-- +goose StatementEnd

CREATE TRIGGER item_path_check_trg
  BEFORE INSERT OR UPDATE OF parent_id, path ON item
  FOR EACH ROW EXECUTE FUNCTION item_path_check();

-- +goose Down
DROP TRIGGER item_path_check_trg ON item;
DROP FUNCTION item_path_check();
DROP TRIGGER item_type_immutable_trg ON item_type;
DROP TRIGGER status_immutable_trg ON status;
DROP FUNCTION item_type_immutable();
DROP FUNCTION status_immutable();
