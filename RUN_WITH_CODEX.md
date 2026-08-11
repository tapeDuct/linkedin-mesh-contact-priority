# Run the live LinkedIn orphan-discovery workflow

Use this prompt in a new Codex session after placing the two LinkedIn exports in this folder:

> Run the LinkedIn orphan-prospect discovery workflow using the Connections and Messages exports in `LinkedIn Orphan Discovery`. Run `linkedin_orphan_discovery.py` with a 90-day inactivity window, 730-day message-history window, and a maximum of 75 pre-filter candidates. Validate the survivors' current roles and seniority with Apollo in supported batches before making me.sh calls. Then use the live me.sh MCP to match by exact LinkedIn profile URL first, exact email second, and name plus company only as a possible manual match. Do not create or update any me.sh records. Return an editable review CSV and Markdown report containing only `create and contact`, `reactivate`, and `manual match` candidates.

## Queue control and Apollo validation

1. Use the local ranking to cap the initial queue; do not query all LinkedIn connections through Apollo or me.sh.
2. Enrich candidates through Apollo's bulk people-match operation in batches within its advertised limit. This is enrichment only: do not create Apollo contacts or sequences.
3. Retain candidates whose current title still supports executive, founder, leadership, or genuinely relevant director-level scope. Mark uncertain current roles for manual relevance review; do not silently discard them.
4. Complete Apollo validation before me.sh matching so stale or clearly irrelevant profiles consume no me.sh calls.

## Required live me.sh checks

1. Search each validated candidate once by name with `searchContacts`, including `social_links`, `emails`, and `interaction_history`.
2. Treat an identical normalized LinkedIn profile URL as an exact match. An exact email may be used only when no conflicting profile URL is present. Do not treat a name-only match as exact.
3. For an exact match whose returned interaction history does not establish recency, repeat `searchContacts` with the candidate name and `last_interaction_date.gte` set to the ISO **date** (not timestamp) 90 days before the run date.
   - A returned contact with the same profile URL is active and is excluded.
   - No returned exact match is a dormant record and becomes `reactivate`.
4. A missing exact match becomes `create and contact`. Any name/company-only, conflicting, or non-unique result becomes `manual match`.
5. If me.sh authentication or availability fails, stop the live stage and preserve the pre-filter report; never reinterpret a failed lookup as a missing contact.

## Safety boundary

The discovery run is read-only. Do not call `createContact`, `updateContact`, `createNote`, group modifications, archive, restore, or merge actions. Apply only a separately reviewed batch after the user explicitly authorizes it.
