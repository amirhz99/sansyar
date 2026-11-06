# SPEC-053: A card announced to the admin always carries its buttons

Status: verified
Owner: agent
Created: 2026-11-05

## Problem

On 2026-11-05 the operator asked in the management group: «سید امین طاهری رو و
سید مجتبی طاهری رو به هم لینک کن». The bot answered «کارت پیوند این دو آماده شد.
بعد از تأیید، …» — and there was **no button to press**. The pending row existed
(`player_link` #24 ↔ #20), but it had `message_id=null`: the card was written and
never delivered. The two players therefore could not see each other's balance or
settle for each other, which is the whole point of a link.

The cause is one line in the agent tool `manage_records`:

```python
reply, _ = bot.propose({'action': action, ...}, user_id, chat_id)
```

`Bot.propose` returns `(preview, markup)`; the markup *is* the approve/reject
keyboard. Every other operation copies it into `effects['markup']`, which
`Bot.message` then attaches to the answer. This branch dropped it, so the answer
was text-only. `suggest_links` had the same defect in a loop, one throw-away card
per pair.

A second, separate defect blocked the same feature: `propose_commands` rejected a
batch whose commands repeat the same `player`, so three players of one family
(«طاهری»: three pairs) failed with «درخواست مورد تکراری دارد». For a link the
target is the *pair*, not the player.

Both are the same failure class as SPEC-052: a card that exists, is announced, and
cannot be clicked.

## Goal

Any answer that tells an admin to press «تأیید» carries a working button. If a code
path creates a card and forgets the markup, the card is still delivered with its
buttons within the same turn, so the sentence is never false.

## Scope

- `manage_records` `link_players`/`unlink_players` sets `effects['markup']` (and
  `proposal_preview`), like every other proposal branch.
- `manage_records` `suggest_links` builds **one** card for up to ten pairs through
  `Bot.propose_commands`, matching the routed `suggest_links` action.
- `Bot.propose_commands` deduplicates on `(action, session, player, partner, name)`
  so two links that share one player are not a duplicate.
- `Bot.deliver_undelivered_cards(chat_id, markup, since)` sends every `commands`
  card of this chat that is `pending`, has `message_id IS NULL`, and was created
  during this turn, except the one the answer already carried.  `Bot.message`
  calls it right after queueing the answer.  It sweeps **only** the admin group.
- Every direct card send to the admin group (`request_self_debt`, `request_link`,
  `settle_partner`, `attach_claims`, and the agent's `declare_debt`) passes
  `ref=self.card_ref(markup)`, so the delivered message id is recorded and the
  card can neither be re-sent nor keep clickable buttons after expiry.

## Non-goals

- No change to the link semantics, to `is_admin`, or to who may approve.
- No automatic approval: the button still needs the admin's click.
- No change to the financial rules, the ledger, or the schema.
- No re-send of a card that was already delivered (`message_id` set).

## Contracts

- `effects['markup']` is set whenever a proposal card is created, so `Bot.message`
  attaches it to the answer.
- `deliver_undelivered_cards()` returns the ids it sent; it never sends a card
  whose `message_id` is set, whose status is not `pending`, or which belongs to
  another chat.
- The net is bounded to the current turn (`created_at >= since`), so it cannot
  resurrect an old card from a previous conversation.
- `card_ref` marks the delivered message (`proposal:<id>`) exactly as the ordinary
  answer does, so a delivered card is never sent twice.
- The batch fingerprint still refuses a genuine repeat: two commands for the same
  player and the same partner stay a `UserError`.

## Acceptance Criteria

- [x] AC-001: an agent turn that creates a `player_link` card delivers a message
  whose inline keyboard carries `yes:<id>`.
- [x] AC-002: pressing that button creates the link, and the two partners then see
  each other's balance through `shared_links`.
- [x] AC-003: `suggest_links` with three same-family players produces exactly one
  card holding three pairs, and its buttons reach the answer.
- [x] AC-004: a card created without markup in the current turn is delivered by
  the safety net, and the card the answer already carried is not sent twice.
- [x] AC-005: a card with a recorded `message_id` is never re-sent.
- [x] AC-006: the safety net never runs for a player's private chat, so an admin
  card cannot leak into it.

## Test Mapping

- AC-001 -> `tests/test_spec_053.py::UndeliveredCardTests::test_a_link_answer_always_carries_the_button`
- AC-002 -> `tests/test_spec_053.py::UndeliveredCardTests::test_the_button_actually_links`
- AC-003 -> `tests/test_spec_053.py::UndeliveredCardTests::test_suggest_links_sends_one_clickable_card_for_every_pair`
- AC-004 -> `tests/test_spec_053.py::UndeliveredCardTests::test_a_forgotten_markup_still_delivers_the_card`,
  `tests/test_spec_053.py::UndeliveredCardTests::test_the_card_carried_by_the_answer_is_not_sent_twice`
- AC-005 -> `tests/test_spec_053.py::UndeliveredCardTests::test_an_already_delivered_card_is_left_alone`
- AC-006 -> `tests/test_spec_053.py::UndeliveredCardTests::test_a_player_chat_is_never_swept`

## Safety Constraints

- The safety net only queues a message; it never approves, links, or writes a
  ledger row.
- It is scoped to one chat and one turn, so it cannot leak a card to another
  conversation or revive a stale proposal.
- Only `commands` cards are considered; identity, claim, and binding cards are
  already delivered by `db.say` with their markup.
- Financial rules, the ledger, and the schema are untouched.
## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: fix the call sites *and* add a turn-level net.  The call-site bug is
  obvious once seen, but the same mistake existed twice in one function and
  nothing failed loudly: the tool answered successfully, the model repeated
  «تأیید را بزنید», and only a human noticed the button was missing.  The net
  makes that sentence true regardless of which branch forgets next time.
- Decision: the net keys off `created_at >= turn start` rather than a marker
  column, because the schema may not change and the turn is the only window in
  which a card can be created and forgotten.
- Decision: `suggest_links` produces one card instead of ten.  It matches the
  routed action, matches the SPEC-011 «one batch, one card» rule, and a single
  click is the whole list.
- Limitation: the net cannot recover a card created in an *earlier* turn whose
  markup was lost, because the turn window is closed.  For the live row
  `c0e649a56cc546b3` the open card is re-delivered once by hand
  (`deliver_undelivered_cards` on the live database), which needs no restart.
- Related: SPEC-052 fixed the same class for identity claims.

## Validation Result

- `python3 -m unittest discover -s tests -t .`: 564 tests, OK (7 new
  `UndeliveredCardTests`).
- `python3 -m compileall -q app tests`: OK.
- `git diff --check`: clean.
- Live repair, no downtime: backup `data/backups/sans-auto-20261105-220005.sqlite3`,
  then the never-delivered card `c0e649a56cc546b3` (`player_link` #24 ↔ #20) was
  queued with its approve/reject buttons by `deliver_undelivered_cards()`; the
  running bot delivered it as message 1730 and recorded `message_id=1730`, so the
  card can no longer be re-sent and its buttons can be removed on expiry.
- Deployment: one restart (stop 22:01:26, «Bot started; polling enabled» 22:01:31,
  about five seconds down).  An earlier attempt at 22:00:25 stopped the wrapper
  shell instead of the service; the new instance refused to start with the
  instance-lock message «ربات یا ابزار ورود اطلاعات دیگری در حال اجراست» and no
  second poller ever ran.  The lock did its job.
- Regression found while testing the net: it originally swept any chat, and
  `pending.chat_id` is the *requester's* chat, so a player's declaration card
  could have been re-sent into that player's private chat.  The net is now
  restricted to the admin group (AC-006), and every direct card send records its
  delivered message id.
