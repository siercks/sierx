# Workspace settings and faster editing

## Administrator Home and private member setup

Click your profile avatar/name in the userbar and choose **Administrator Home**.
This entry and `/admin` are restricted to active workspace administrators.
The profile disclosure works with keyboard activation, Tab and Escape; Escape
returns focus to the profile control. Existing workspace settings remain at
`/settings` and are linked from Administrator Home.

**Add Member** takes a display name and email address. It creates a regular
Member in the current workspace, without changing any existing account or
granting administrator access. Duplicate emails are rejected; the action never
resets a password, links an existing global identity, reactivates an account or
changes a role. Administrator member search shows only the current workspace's
names, emails, roles and active state. The ordinary assignee roster still exposes
only active names/IDs.

For local sign-in, the browser generates a cryptographically random initial
password before submitting the request. The server hashes it with the existing
Argon2id policy; it never stores or returns plaintext. Save/copy the login details
privately before choosing **I saved the login details**. The password is held
only in the current component's memory; save it before leaving or reloading
the page. It is not placed in a URL, browser
storage, query cache or member list. It is not an expiring password or an enforced
first-login password reset. No invitation email is sent.

If a response is lost, the login details remain visible with an unconfirmed
creation warning. Check the member list before explicitly retrying; writes are
not replayed automatically. Retrying a committed creation cannot replace its
credential. A known rejection on the initial request preserves name/email while
discarding the unused generated credential. Proxy-auth deployments retain
operator provisioning and do not create local-password members through this form.

The new member can sign in and is immediately eligible for the assignee picker.
Migration 0016 adds an isolated NOLOGIN function owner and narrowly scoped
administrator-checked member create/list functions. The application runtime
receives no direct account/membership write or password-read privilege. Its
server configuration does not gain an operator/maintenance credential. Both the
HTTP permission check and database functions verify administrator scope; the
functions independently verify actual active administrator membership.

API ownership: GET/POST `/api/v1/admin/members` are covered by
`TestAdminMemberProvisioningAuthorizationAndCredentials`, direct runtime/forged
scope tests, tenant-scoped pagination/search, populated 15→16→15→16 preservation,
golden route coverage, catalog privilege checks and real browser
profile/create/sign-in/assignment checks. GET `/admin` has a generated document
route and a lazy frontend chunk. This is private administrator provisioning;
registration/invitation modes remain disabled.

## Everyday editing

The item Details pane has Edit assignee, Edit start date and Edit due date
buttons beside their values. Each opens a focused editor and updates only that
field. Assignees are selected from active workspace members; dates use the
browser's calendar/date input and can be cleared. Saves retain the existing
item-version, permissions and conflict handling. Errors preserve the draft.

Descriptions and comments have a Markdown toolbar for bold, italic, headings,
bulleted/numbered lists, links, quotes and inline code, plus preview. Select text
before formatting, or use Ctrl/Cmd+B and Ctrl/Cmd+I in the editor. Source remains
ordinary Markdown. Preview uses the existing safe local renderer and loads only
when requested. Submitting a new comment clears its editor after success.

Successful item edits and status changes close their dialog with confirmation
and keyboard focus return. A status with no outgoing transitions does not leave
an open, unusable status dialog.

## Create another project

Administrators have Create project beside the project selector. It uses the
same form as Manage projects: name, stable key prefix, kind and optional
organizational owner. A project is a peer of SRX inside the workspace; no Topic
or Product entity is introduced. Selecting the new project gives it a dashboard
and makes it the owning-project choice in that dashboard's Create item flow.
Workspace-wide defaults and existing item identities are preserved.

## Workspace and item workflows

Administrators can open Settings from the application header, or `/settings`.
Workspace details edits the display name. The existing workspace identifier and
slug remain stable and read-only.

Choose a Workflow project to edit that project's item workflow. Status cards
show each status and arrows to its permitted destinations. Move earlier/later
changes display order; Edit transitions selects a status for connection editing.
The allowed-transition checkboxes, required-field controls and per-type initial
status selectors all have keyboard alternatives.

Add a named status with a stable lowercase key and category, or use Add suggested
statuses to add missing Unassigned, Planned, On Hold, Blocked and Completed
labels. The seeded To Do and In Progress statuses remain available. Assignment
is independent: the optional Unassigned workflow status does not clear an
assignee. On Hold and Blocked are active statuses in the suggestions; Completed
uses the done category for existing completion/rollup behavior.

Suggestions do not connect themselves or modify the saved workflow. For
example, choose From status = To Do, enable Allow To Do → Planned, then choose
Planned and configure its destinations. Review requirements and initial statuses,
check the review confirmation, and Save workflow. Existing transitions and their
requirements are retained unless deliberately changed.

Saving appends an immutable configuration version. Existing items keep their
status IDs, keys and history; future transitions use the published flow. Existing
status definitions cannot be renamed, recategorized or removed in this additive
editor. Add a new definition for a different name; deliberate item migration and
retirement tooling are separate work. Workflow edits are specific to the chosen
project and are not applied automatically to other projects.

Stale workspace/workflow saves are rejected. The draft remains visible alongside
the conflict. Replace draft with latest is an explicit discard/reload operation;
there is no automatic retry that overwrites somebody else's configuration.

## API ownership and acceptance

| Route | Contract | Owning acceptance |
|---|---|---|
| GET `/api/v1/workspace` | Authenticated current-workspace ID, slug, name and numeric version | `TestWorkspaceSettingsAuthorizationConflictAndRoster`; `workspace-settings.json` |
| PATCH `/api/v1/workspace` | Administrator; only name; quoted current numeric workspace version in If-Match | Same test; `workspace-update.json` |
| GET `/api/v1/projects/{key}/config` | Existing current configuration read, including numeric version | Existing configuration/golden tests |
| PUT `/api/v1/projects/{key}/config` | Administrator; complete statuses, transitions and initial_statuses; If-Match uses current numeric config version | `TestWorkflowSnapshotsValidationAndTransitions`; `workflow-update.json` |
| GET `/api/v1/members` | Authenticated, paginated active names/IDs in the current workspace; no email/auth fields | Workspace/roster test and real browser field-edit check |
| GET `/settings` | Administrator-only document with initial workspace/project bootstrap | Generated route checks and real browser admin workflow |

The config write supports 1–50 statuses and at most 200 directed arcs. Status
keys are unique lowercase identifiers of at most 40 characters; names are unique
case-insensitively and at most 80 characters. Existing definitions must be
retained exactly. Transitions must reference distinct configured statuses without
duplicates; requirements must be known item/custom fields. Every existing item
type needs one configured initial status. Existing field/type definitions are
preserved. Project locking and version checks accept only one concurrent save
from the same base version. The read endpoint's weak representation ETag remains
separate from the numeric config version required for writes.

Browser acceptance exercises direct field edits without unrelated changes,
Markdown preview/submission/reset, project creation, workspace-name persistence,
suggested custom statuses, a real item transition into Planned and readable
default-size settings-button labels across all 23 appearances. Existing
keyboard/theme/conflict/session and 10k checks remain required.

## Release boundary

Migration 0015 adds workspace versioning and a tenant/admin-scoped update policy.
Migration 0016 adds private administrator member provisioning and scoped search.
Before deploying 0016, rehearse the upgrade on a protected populated restore,
verify existing account/membership/item preservation, and revalidate any recovery
operator that pins an earlier revision or schema version.
For a logical restore into an empty cluster, run the current `db-roles.sh`
before restoring the archive. It provisions the isolated NOLOGIN function owner
as well as the three application logins; an earlier role helper lacks this
schema-16 prerequisite. Never restore past role/ACL errors.
Use the normal reviewed release/migration procedure and preserve the live backlog
and recovery materials. Source checks use disposable databases; never run seed,
reset or migration reversibility gates against the daily-use instance. Local
validation does not publish an image, deploy the site, approve physical-phone
behavior or sign Phase 2 exit. See ADR-029 for the bounded early configuration
scope; this work does not add the Kanban board or a YAML reconcile service.
