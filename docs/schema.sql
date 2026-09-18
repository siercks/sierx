--
-- PostgreSQL database dump
--



SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: citext; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;


--
-- Name: EXTENSION citext; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION citext IS 'data type for case-insensitive character strings';


--
-- Name: ltree; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS ltree WITH SCHEMA public;


--
-- Name: EXTENSION ltree; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION ltree IS 'data type for hierarchical tree-like structures';


--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


SET default_tablespace = '';

--
-- Name: change_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event (
    workspace_id uuid NOT NULL,
    seq bigint NOT NULL,
    at timestamp with time zone DEFAULT now() NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
)
PARTITION BY RANGE (at);


SET default_table_access_method = heap;

--
-- Name: change_event_2026_09; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_09 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);


--
-- Name: change_event_2026_10; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_10 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);


--
-- Name: change_event_2026_11; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.change_event_2026_11 (
    workspace_id uuid CONSTRAINT change_event_workspace_id_not_null NOT NULL,
    seq bigint CONSTRAINT change_event_seq_not_null NOT NULL,
    at timestamp with time zone DEFAULT now() CONSTRAINT change_event_at_not_null NOT NULL,
    item_id uuid,
    actor_id uuid,
    kind text CONSTRAINT change_event_kind_not_null NOT NULL,
    field text,
    old_value jsonb,
    new_value jsonb
);


--
-- Name: comment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comment (
    id uuid DEFAULT uuidv7() NOT NULL,
    item_id uuid NOT NULL,
    author_id uuid NOT NULL,
    body text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    edited_at timestamp with time zone,
    deleted_at timestamp with time zone
);


--
-- Name: config_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_status (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    status_id uuid NOT NULL,
    display_order integer NOT NULL
);


--
-- Name: config_transition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_transition (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    from_status_id uuid NOT NULL,
    to_status_id uuid NOT NULL,
    requires jsonb DEFAULT '[]'::jsonb NOT NULL
);


--
-- Name: config_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.config_type (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    item_type_id uuid NOT NULL,
    initial_status_id uuid NOT NULL
);


--
-- Name: field_def; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.field_def (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    data_type text NOT NULL,
    options jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT field_def_data_type_check CHECK ((data_type = ANY (ARRAY['text'::text, 'number'::text, 'date'::text, 'select'::text, 'multiselect'::text, 'user'::text, 'url'::text, 'bool'::text])))
);


--
-- Name: item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    item_type_id uuid NOT NULL,
    status_id uuid NOT NULL,
    config_version integer NOT NULL,
    parent_id uuid,
    path public.ltree NOT NULL,
    title text NOT NULL,
    body text,
    assignee_id uuid,
    points numeric(6,2),
    start_date date,
    due_date date,
    rank text NOT NULL,
    fields jsonb DEFAULT '{}'::jsonb NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    change_seq bigint NOT NULL,
    origin_id uuid NOT NULL,
    origin_seq bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    deleted_at timestamp with time zone,
    search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, ((title || ' '::text) || COALESCE(body, ''::text)))) STORED,
    CONSTRAINT item_title_check CHECK (((length(title) >= 1) AND (length(title) <= 500)))
);


--
-- Name: item_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_link (
    id uuid DEFAULT uuidv7() NOT NULL,
    from_item_id uuid NOT NULL,
    to_item_id uuid NOT NULL,
    kind text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    created_by uuid,
    CONSTRAINT item_link_check CHECK ((from_item_id <> to_item_id)),
    CONSTRAINT item_link_kind_check CHECK ((kind = ANY (ARRAY['blocks'::text, 'duplicates'::text, 'relates'::text, 'implements'::text, 'discovered_from'::text])))
);


--
-- Name: item_rollup; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_rollup (
    item_id uuid NOT NULL,
    descendant_count integer DEFAULT 0 NOT NULL,
    done_count integer DEFAULT 0 NOT NULL,
    points_total numeric(10,2),
    points_done numeric(10,2),
    earliest_start date,
    latest_due date,
    computed_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: item_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_type (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    level integer NOT NULL,
    is_idea boolean DEFAULT false NOT NULL
);


--
-- Name: membership; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.membership (
    workspace_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role text NOT NULL,
    CONSTRAINT membership_role_check CHECK ((role = ANY (ARRAY['member'::text, 'admin'::text])))
);


--
-- Name: project; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    key_prefix text NOT NULL,
    name text NOT NULL,
    kind text NOT NULL,
    next_key_num integer DEFAULT 1 NOT NULL,
    archived_at timestamp with time zone,
    CONSTRAINT project_key_prefix_check CHECK ((key_prefix ~ '^[A-Z][A-Z0-9]{1,9}$'::text)),
    CONSTRAINT project_kind_check CHECK ((kind = ANY (ARRAY['delivery'::text, 'discovery'::text, 'portfolio'::text])))
);


--
-- Name: project_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_config (
    project_id uuid NOT NULL,
    version integer NOT NULL,
    source_yaml text,
    applied_at timestamp with time zone DEFAULT now() NOT NULL,
    applied_by uuid
);


--
-- Name: saved_view; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.saved_view (
    id uuid DEFAULT uuidv7() NOT NULL,
    workspace_id uuid NOT NULL,
    owner_id uuid,
    name text NOT NULL,
    query text NOT NULL,
    layout text NOT NULL,
    shared boolean DEFAULT false NOT NULL,
    CONSTRAINT saved_view_layout_check CHECK ((layout = ANY (ARRAY['list'::text, 'board'::text, 'timeline'::text, 'grid'::text])))
);


--
-- Name: seq_counter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.seq_counter (
    workspace_id uuid NOT NULL,
    value bigint DEFAULT 0 NOT NULL
);


--
-- Name: session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session (
    id_hash bytea NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    last_seen_at timestamp with time zone
);


--
-- Name: sprint; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sprint (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    name text NOT NULL,
    goal text,
    starts_on date NOT NULL,
    ends_on date NOT NULL,
    state text NOT NULL,
    CONSTRAINT sprint_check CHECK ((ends_on > starts_on)),
    CONSTRAINT sprint_state_check CHECK ((state = ANY (ARRAY['planned'::text, 'active'::text, 'closed'::text])))
);


--
-- Name: sprint_item; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sprint_item (
    sprint_id uuid NOT NULL,
    item_id uuid NOT NULL,
    added_at timestamp with time zone DEFAULT now() NOT NULL,
    removed_at timestamp with time zone
);


--
-- Name: status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.status (
    id uuid DEFAULT uuidv7() NOT NULL,
    project_id uuid NOT NULL,
    key text NOT NULL,
    name text NOT NULL,
    category text NOT NULL,
    CONSTRAINT status_category_check CHECK ((category = ANY (ARRAY['open'::text, 'active'::text, 'done'::text, 'cancelled'::text])))
);


--
-- Name: user_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_account (
    id uuid DEFAULT uuidv7() NOT NULL,
    email public.citext NOT NULL,
    display_name text NOT NULL,
    password_hash text,
    totp_secret bytea,
    theme text DEFAULT 'system'::text NOT NULL,
    reduced_motion boolean,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: workspace; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workspace (
    id uuid DEFAULT uuidv7() NOT NULL,
    slug text NOT NULL,
    name text NOT NULL,
    origin_id uuid NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: change_event_2026_09; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_09 FOR VALUES FROM ('2026-09-01 00:00:00+00') TO ('2026-10-01 00:00:00+00');


--
-- Name: change_event_2026_10; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_10 FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00');


--
-- Name: change_event_2026_11; Type: TABLE ATTACH; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event ATTACH PARTITION public.change_event_2026_11 FOR VALUES FROM ('2026-11-01 00:00:00+00') TO ('2026-12-01 00:00:00+00');


--
-- Name: change_event change_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event
    ADD CONSTRAINT change_event_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_09 change_event_2026_09_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_09
    ADD CONSTRAINT change_event_2026_09_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_10 change_event_2026_10_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_10
    ADD CONSTRAINT change_event_2026_10_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: change_event_2026_11 change_event_2026_11_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.change_event_2026_11
    ADD CONSTRAINT change_event_2026_11_pkey PRIMARY KEY (workspace_id, seq, at);


--
-- Name: comment comment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_pkey PRIMARY KEY (id);


--
-- Name: config_status config_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_pkey PRIMARY KEY (project_id, version, status_id);


--
-- Name: config_transition config_transition_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_pkey PRIMARY KEY (project_id, version, from_status_id, to_status_id);


--
-- Name: config_type config_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_pkey PRIMARY KEY (project_id, version, item_type_id);


--
-- Name: field_def field_def_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_pkey PRIMARY KEY (id);


--
-- Name: field_def field_def_project_id_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_project_id_key_key UNIQUE (project_id, key);


--
-- Name: item_link item_link_from_item_id_to_item_id_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_from_item_id_to_item_id_kind_key UNIQUE (from_item_id, to_item_id, kind);


--
-- Name: item_link item_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_pkey PRIMARY KEY (id);


--
-- Name: item item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_pkey PRIMARY KEY (id);


--
-- Name: item item_project_rank_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_project_rank_uniq UNIQUE (project_id, rank) DEFERRABLE;


--
-- Name: item_rollup item_rollup_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_rollup
    ADD CONSTRAINT item_rollup_pkey PRIMARY KEY (item_id);


--
-- Name: item_type item_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_pkey PRIMARY KEY (id);


--
-- Name: item_type item_type_project_id_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_project_id_uniq UNIQUE (project_id, id);


--
-- Name: item item_workspace_id_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_workspace_id_key_key UNIQUE (workspace_id, key);


--
-- Name: membership membership_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_pkey PRIMARY KEY (workspace_id, user_id);


--
-- Name: project_config project_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_pkey PRIMARY KEY (project_id, version);


--
-- Name: project project_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_pkey PRIMARY KEY (id);


--
-- Name: project project_workspace_id_key_prefix_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_workspace_id_key_prefix_key UNIQUE (workspace_id, key_prefix);


--
-- Name: saved_view saved_view_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_pkey PRIMARY KEY (id);


--
-- Name: seq_counter seq_counter_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seq_counter
    ADD CONSTRAINT seq_counter_pkey PRIMARY KEY (workspace_id);


--
-- Name: session session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session
    ADD CONSTRAINT session_pkey PRIMARY KEY (id_hash);


--
-- Name: sprint_item sprint_item_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_pkey PRIMARY KEY (sprint_id, item_id);


--
-- Name: sprint sprint_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint
    ADD CONSTRAINT sprint_pkey PRIMARY KEY (id);


--
-- Name: status status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_pkey PRIMARY KEY (id);


--
-- Name: status status_project_id_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_project_id_uniq UNIQUE (project_id, id);


--
-- Name: user_account user_account_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_account
    ADD CONSTRAINT user_account_email_key UNIQUE (email);


--
-- Name: user_account user_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_account
    ADD CONSTRAINT user_account_pkey PRIMARY KEY (id);


--
-- Name: workspace workspace_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace
    ADD CONSTRAINT workspace_pkey PRIMARY KEY (id);


--
-- Name: workspace workspace_slug_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workspace
    ADD CONSTRAINT workspace_slug_key UNIQUE (slug);


--
-- Name: change_event_item; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_item ON ONLY public.change_event USING btree (item_id, at DESC);


--
-- Name: change_event_2026_09_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_09_item_id_at_idx ON public.change_event_2026_09 USING btree (item_id, at DESC);


--
-- Name: change_event_ws_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_ws_seq ON ONLY public.change_event USING btree (workspace_id, seq);


--
-- Name: change_event_2026_09_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_09_workspace_id_seq_idx ON public.change_event_2026_09 USING btree (workspace_id, seq);


--
-- Name: change_event_2026_10_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_10_item_id_at_idx ON public.change_event_2026_10 USING btree (item_id, at DESC);


--
-- Name: change_event_2026_10_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_10_workspace_id_seq_idx ON public.change_event_2026_10 USING btree (workspace_id, seq);


--
-- Name: change_event_2026_11_item_id_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_11_item_id_at_idx ON public.change_event_2026_11 USING btree (item_id, at DESC);


--
-- Name: change_event_2026_11_workspace_id_seq_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX change_event_2026_11_workspace_id_seq_idx ON public.change_event_2026_11 USING btree (workspace_id, seq);


--
-- Name: item_assignee; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_assignee ON public.item USING btree (assignee_id) WHERE (deleted_at IS NULL);


--
-- Name: item_fields_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_fields_gin ON public.item USING gin (fields jsonb_path_ops);


--
-- Name: item_link_to; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_link_to ON public.item_link USING btree (to_item_id, kind);


--
-- Name: item_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_parent ON public.item USING btree (parent_id);


--
-- Name: item_path_gist; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_path_gist ON public.item USING gist (path);


--
-- Name: item_proj_stat; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_proj_stat ON public.item USING btree (project_id, status_id) WHERE (deleted_at IS NULL);


--
-- Name: item_search; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_search ON public.item USING gin (search_tsv);


--
-- Name: item_ws_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX item_ws_seq ON public.item USING btree (workspace_id, change_seq);


--
-- Name: session_expires_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX session_expires_at ON public.session USING btree (expires_at);


--
-- Name: change_event_2026_09_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_09_item_id_at_idx;


--
-- Name: change_event_2026_09_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_09_pkey;


--
-- Name: change_event_2026_09_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_09_workspace_id_seq_idx;


--
-- Name: change_event_2026_10_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_10_item_id_at_idx;


--
-- Name: change_event_2026_10_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_10_pkey;


--
-- Name: change_event_2026_10_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_10_workspace_id_seq_idx;


--
-- Name: change_event_2026_11_item_id_at_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_item ATTACH PARTITION public.change_event_2026_11_item_id_at_idx;


--
-- Name: change_event_2026_11_pkey; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_pkey ATTACH PARTITION public.change_event_2026_11_pkey;


--
-- Name: change_event_2026_11_workspace_id_seq_idx; Type: INDEX ATTACH; Schema: public; Owner: -
--

ALTER INDEX public.change_event_ws_seq ATTACH PARTITION public.change_event_2026_11_workspace_id_seq_idx;


--
-- Name: comment comment_author_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_author_id_fkey FOREIGN KEY (author_id) REFERENCES public.user_account(id);


--
-- Name: comment comment_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment
    ADD CONSTRAINT comment_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id);


--
-- Name: config_status config_status_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: config_status config_status_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_status
    ADD CONSTRAINT config_status_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.status(id);


--
-- Name: config_transition config_transition_from_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_from_status_id_fkey FOREIGN KEY (from_status_id) REFERENCES public.status(id);


--
-- Name: config_transition config_transition_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: config_transition config_transition_to_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_transition
    ADD CONSTRAINT config_transition_to_status_id_fkey FOREIGN KEY (to_status_id) REFERENCES public.status(id);


--
-- Name: config_type config_type_initial_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_initial_status_id_fkey FOREIGN KEY (initial_status_id) REFERENCES public.status(id);


--
-- Name: config_type config_type_item_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_item_type_id_fkey FOREIGN KEY (item_type_id) REFERENCES public.item_type(id);


--
-- Name: config_type config_type_project_id_version_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.config_type
    ADD CONSTRAINT config_type_project_id_version_fkey FOREIGN KEY (project_id, version) REFERENCES public.project_config(project_id, version);


--
-- Name: field_def field_def_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_def
    ADD CONSTRAINT field_def_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item item_assignee_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_assignee_id_fkey FOREIGN KEY (assignee_id) REFERENCES public.user_account(id);


--
-- Name: item item_config_version_exists; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_config_version_exists FOREIGN KEY (project_id, config_version) REFERENCES public.project_config(project_id, version);


--
-- Name: item item_item_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_item_type_id_fkey FOREIGN KEY (item_type_id) REFERENCES public.item_type(id);


--
-- Name: item_link item_link_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.user_account(id);


--
-- Name: item_link item_link_from_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_from_item_id_fkey FOREIGN KEY (from_item_id) REFERENCES public.item(id);


--
-- Name: item_link item_link_to_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link
    ADD CONSTRAINT item_link_to_item_id_fkey FOREIGN KEY (to_item_id) REFERENCES public.item(id);


--
-- Name: item item_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.item(id);


--
-- Name: item item_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item_rollup item_rollup_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_rollup
    ADD CONSTRAINT item_rollup_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id) ON DELETE CASCADE;


--
-- Name: item item_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_status_id_fkey FOREIGN KEY (status_id) REFERENCES public.status(id);


--
-- Name: item item_status_same_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_status_same_project FOREIGN KEY (project_id, status_id) REFERENCES public.status(project_id, id);


--
-- Name: item_type item_type_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_type
    ADD CONSTRAINT item_type_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: item item_type_same_project; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_type_same_project FOREIGN KEY (project_id, item_type_id) REFERENCES public.item_type(project_id, id);


--
-- Name: item item_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item
    ADD CONSTRAINT item_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: membership membership_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id);


--
-- Name: membership membership_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.membership
    ADD CONSTRAINT membership_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: project_config project_config_applied_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_applied_by_fkey FOREIGN KEY (applied_by) REFERENCES public.user_account(id);


--
-- Name: project_config project_config_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_config
    ADD CONSTRAINT project_config_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: project project_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project
    ADD CONSTRAINT project_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: saved_view saved_view_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.user_account(id);


--
-- Name: saved_view saved_view_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.saved_view
    ADD CONSTRAINT saved_view_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: seq_counter seq_counter_workspace_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.seq_counter
    ADD CONSTRAINT seq_counter_workspace_id_fkey FOREIGN KEY (workspace_id) REFERENCES public.workspace(id);


--
-- Name: session session_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session
    ADD CONSTRAINT session_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.user_account(id) ON DELETE CASCADE;


--
-- Name: sprint_item sprint_item_item_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_item_id_fkey FOREIGN KEY (item_id) REFERENCES public.item(id);


--
-- Name: sprint_item sprint_item_sprint_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint_item
    ADD CONSTRAINT sprint_item_sprint_id_fkey FOREIGN KEY (sprint_id) REFERENCES public.sprint(id);


--
-- Name: sprint sprint_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sprint
    ADD CONSTRAINT sprint_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- Name: status status_project_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.status
    ADD CONSTRAINT status_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.project(id);


--
-- PostgreSQL database dump complete
--


