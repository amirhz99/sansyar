# SPEC-052: A new player's identity card becomes actionable on its own

Status: verified
Owner: agent
Created: 2026-11-05

## Problem

On 2026-11-05 a brand-new player, «محمدطه مقدم» (Bale id `1041770596`), opened
the bot in a private chat and gave his full name.  He was a real newcomer, so
`Bot.identify()` matched nobody and filed a **claim**: pending
`0576a1f6fd294f0b`, `kind='claim'`, `payload.player=null`, `message_id=null`.
The card in the admin group carried no buttons, because there is nothing to
approve yet, and it closed with the instruction «باید بازیکن را دستی بسازید و
بعد پیوند بزنید: /link 0576a1f6fd294f0b شناسه».

The admin did exactly that — player #67 «محمدطه مقدم» was created — and the card
still could not be approved.  Nothing connected the new player to the claim:

- Attaching only existed as a human step, `Bot.resolve_claim`, reachable through
  `/link <code> <player>`; the request code had to be remembered and retyped.
- Creating the player (`/newplayer`, the approved `new_player` card, or the
  agent's `upsert_players`) never looked at `pending`, so the claim kept
  `player=null` and no button.
- The agent had no tool for it either; asked to resend the card it answered
  «من نمی‌توانم کارت را دوباره بفرستم — ابزارش در دست من نیست».
- The player himself could not retry: `identify()` answers «درخواست شناسایی شما
  منتظر ادمین است» while any claim is pending, so he stayed locked out of his
  own balance with a pending row that no click could resolve.

The result was a permanently open, unapprovable claim and a player with no
access to his account, on a flow the bot itself recommended.

## Goal

As soon as the player a claim names exists — created from any path — the claim
turns into an ordinary `identity` card with approve/reject buttons in the admin
group.  If the player does not exist yet, the claim card itself creates it with
one click, so no request code is ever needed to unblock a newcomer.

## Scope

- `Bot.attach_claims(player, actor=None)`: every pending `claim` whose declared
  name is exactly equal (after `normalize`) to `player['normalized_name']` is
  rewritten to `kind='identity'` with `payload['player']` set, and re-sent to
  `config.admin_group` with the approval buttons.  Returns the rewritten ids.
- Called from `Bot.confirm()` for each approved `new_player` command and from
  the agent's `manage_records` `upsert_players` operation.
- `Bot.claim_create(ident, actor)`: creates the player the claim names through
  `Service.ensure_player`, then attaches it and reports what happened.
- The claim card sent by `identify()` carries two buttons: «ساخت بازیکن و اتصال»
  (`mk:<ident>`) and «رد» (`no:<ident>`).  `Bot.callback()` routes `mk:` to
  `claim_create()`.
- The claim card text names the button and keeps the request code for manual
  `/link` use.

## Non-goals

- No fuzzy attach: a similar or shortened name is still a human decision, and
  `/link` stays exactly as it was.
- No change to `identify()`'s refusal while a request is pending, to the
  approval semantics, to the financial rules, the ledger, or the schema.
- No automatic approval: the button creates a player and a card; linking still
  needs the admin's explicit confirm click.
- No player-facing change to the welcome text (SPEC-021).

## Contracts

- `attach_claims()` returns `[]` for a player without a normalized name and
  never raises for a malformed payload; a `claim` outside `status='pending'` is
  never rewritten.
- Only one card per claim: after the rewrite the row is `kind='identity'`, so a
  second call cannot re-send or re-approve it.
- `claim_create()` fails closed with a `UserError` when the claim is gone, its
  payload is unreadable, its name is empty, or `ensure_player` refuses a name
  that is too close to an existing player.  It reuses an existing player with
  the same normalized name instead of duplicating it.
- `mk:` is an admin-only callback; the existing `is_admin` gate in
  `Bot.callback()` runs before any handler, and the reply is a plain
  `answerCallbackQuery` text.
- An approved `identity` card still attaches the number from the payload
  (SPEC-021) and still binds through `Service.bind`.
## Acceptance Criteria

- [x] AC-001: creating the player a claim names — through the approved
  `new_player` card or the agent's `upsert_players` — rewrites the claim into an
  `identity` card with `yes:`/`no:` buttons, so one click links the account.
- [x] AC-002: the claim card itself offers «ساخت بازیکن و اتصال», which creates
  the player, sends the approvable card, and a following `yes:` links the
  account (with the number that came with the request) and notifies the player.
  The «رد» button closes the claim with no player created and no link.
- [x] AC-003: only an exactly equal normalized name is attached; a similar name
  leaves the claim untouched and buttonless.
- [x] AC-004: a claim produces one approvable card; a second attach sends
  nothing.
- [x] AC-005: the create button is refused for a non-admin, and the whole flow
  makes no model call.

## Test Mapping

- AC-001 -> `tests/test_spec_052.py::ClaimCardTests::test_creating_the_player_makes_the_card_clickable`,
  `tests/test_spec_052.py::ClaimCardTests::test_the_agent_player_creation_attaches_the_claim`
- AC-002 -> `tests/test_spec_052.py::ClaimCardTests::test_one_click_creates_the_player_and_returns_the_card`,
  `tests/test_spec_052.py::ClaimCardTests::test_the_claim_card_can_be_rejected`
- AC-003 -> `tests/test_spec_052.py::ClaimCardTests::test_a_similar_name_is_not_attached`
- AC-004 -> `tests/test_spec_052.py::ClaimCardTests::test_the_card_is_sent_once_per_claim`
- AC-005 -> `tests/test_spec_052.py::ClaimCardTests::test_a_player_cannot_press_the_create_button`,
  `tests/test_spec_052.py::ClaimCardTests::test_the_card_is_not_built_by_the_model`

## Safety Constraints

- A guess never links, renames, or creates a player; only an admin click does.
- The create button is behind the same `is_admin` boundary as every card, and
  it fails closed on an unknown, resolved, or unreadable claim.
- No number, ledger row, or balance is sent to the model; the card is built
  deterministically by the bot.
- Financial rules, the ledger, and the schema are untouched.

## Validation

```bash
python3 -m unittest discover -s tests -t . -v
python3 -m compileall -q app tests
git diff --check
```

## Notes

- Decision: attach on player creation, not on a timer.  The admin's next action
  after «بازیکن را بسازید» is the creation itself, so the card must appear at
  that moment; a sweep would leave the player locked out for another tick.
- Decision: the name must match exactly.  Live data shows why a fuzzy attach is
  dangerous: «امیرحسین», «علی» and «محمد» each matched several players, and the
  user would then see somebody else's debt (SPEC-021 Notes).
- Decision: `mk:` creates a player instead of asking the model to call
  `new_player`; the operator reported that the model-driven path ended with
  «ابزارش در دست من نیست», and a newcomer must not depend on a model turn.
- Limitation: a claim whose declared name is misspelled stays a claim until the
  admin presses «رد» or resolves it with `/link`; the card lists the candidate
  names (SPEC-021) so that decision stays informed.


## Validation Result

- `python3 -m unittest discover -s tests -t .`: 557 tests, OK (the 8 new
  `ClaimCardTests` included).
- `python3 -m compileall -q app tests`: OK.
- `git diff --check`: clean.
- Live data: backup `data/backups/sans-auto-20261105-183101.sqlite3`; the open
  claim `0576a1f6fd294f0b` was attached to player #67 with
  `Bot.attach_claims(..., 'migration:spec-052')`, which rewrote it to
  `kind='identity'` and queued the approvable card.  The card reached the admin
  group at 18:34:23 and the admin approved it at 18:34:48: player #67
  «محمدطه مقدم» now has `bale_id=1041770596` and `phone=+989123333807`, with
  `claim_attached`, `bind` and `set_player_phone` audit rows.
- Deployment: the service was restarted once (stop 18:36:38, «Bot started;
  polling enabled» 18:36:43, about five seconds down); the repair itself needed
  no restart, because it only queues a message the running bot delivers.
