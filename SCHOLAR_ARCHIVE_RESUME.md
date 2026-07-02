# Resume checkpoint — Google Scholar email archive + filing

_Created 2026-06-28. Read this first when resuming after the Gmail reconnect + session restart._

## Goal (3 parts)
1. Save every **unread** Google Scholar alert as `.eml` into `~/Documents/Papers/PapersWiki/email_src/`.
2. **Mark each saved email read** (remove `UNREAD` label).
3. **Move ALL read Scholar emails** into the Gmail label **`Work/Academe`** (CONFIRMED nested label:
   parent `Work` → child `Academe`). "Move" = apply that label + remove `INBOX`. Scope CONFIRMED =
   every already-read Scholar email in the inbox, not just this task's emails.

## Scope / filter
Senders: `scholaralerts-noreply@google.com OR scholarcitations-noreply@google.com OR scholar-noreply@google.com`
Total unread at start: ~201 threads.

## Decisions (locked in by user)
- Auth: user fully reconnects Gmail (needs `gmail.modify`) + restarts session, then resume. The
  earlier "permission fix" did NOT take effect live (kept returning "insufficient authentication scopes").
- Fidelity for remaining: **fast snippet-based** — build `.eml` from `search_threads` MINIMAL snippets
  (title, authors, abstract teaser, arXiv id→`https://arxiv.org/pdf/<id>` when present). No per-email
  `get_thread` needed. ~half lack a precise URL; acceptable.
- Format: condensed `.eml` = headers (From/To/Subject/Date, MIME) + small HTML body w/ title, link,
  authors, snippet, attribution. (Not byte-exact MIME — MCP exposes no raw RFC822.)
- Naming: `surname_MMDD.eml`; on collision with existing file → `surname_MMDDYY.eml` (2-digit year);
  still colliding → append `_b`, `_c`. Surname from "<Name> - new articles" subject.

## STATUS (updated 2026-06-28, after reconnect+restart)
- SAVE PHASE: ✅ COMPLETE. All 115 unread Scholar threads saved as .eml in email_src/
  (snippet-based fidelity). Total dir count went 48 → 163. Paginated all 5 pages to the end.
- MARK-READ: ❌ STILL BLOCKED. After the user's reconnect + session restart, unlabel_thread
  UNREAD STILL returns "insufficient authentication scopes". The connector is effectively
  read-only; gmail.modify is not being granted. Needs deeper fix (re-grant manage-mail scope,
  possibly remove+re-add the whole Gmail integration, not just toggle a permission).
- MOVE TO Work/Academe: ❌ BLOCKED (same write-scope issue).

## REMAINING WORK (when write scope finally granted)
1. Mark read: query `is:unread from:<scholar senders>`, paginate, unlabel_thread UNREAD on each.
   (All 115 are already saved, so this is pure label cleanup — no re-saving needed.)
2. Move ALL read Scholar mail to Work/Academe: list_labels (create_label "Work/Academe" if
   missing), then query `from:<scholar senders> is:read in:inbox`, paginate, label_thread with
   the Work/Academe id + unlabel_thread INBOX.

## (historical) first 12 saved in prior session, thread IDs:
19f08edbddd30c59 19f08edbdaf1b0ff 19f08edbc7dccaa8 19f08edbc489d429 19ef281b1cd1d5ac 19ef281b0f666029
19ef281b0f047e5a 19ef281b0e801d29 19ef281b0babc5ad 19ee9c99cd927881 19ee9c99cc766575 19ee9c99c2d3f976

## RESUME PROCEDURE (after reconnect + restart)
1. Sanity-check write scope: `unlabel_thread` UNREAD on one already-saved thread. If still scope error,
   stop and tell user the reconnect didn't take.
2. Ensure label exists: `list_labels`; if `Work/Academe` missing, `create_label`.
3. Loop until `is:unread from:<scholar senders>` is empty:
   - `search_threads` MINIMAL (pageSize 25). For each thread: build condensed `.eml` from snippet,
     write to `email_src/` (skip if filename already exists), then `unlabel_thread` UNREAD (mark read).
   - Because mark-read removes it from the unread set, the next search returns fresh ones (resumable).
4. Move ALL read Scholar emails to `Work/Academe`: query `from:<scholar senders> is:read in:inbox`,
   paginate, for each thread `label_thread` with the `Work/Academe` label id + `unlabel_thread` `INBOX`.
   (Note: after step 3, every email this task marked read also becomes eligible here.)
5. Report: total saved, marked read, moved; any failures.

## Confirmed (no open questions)
- Label: `Work/Academe` (nested Work → Academe).
- Move scope: ALL read Scholar mail in inbox.
