"""SPEC-060: an account the bot already knows can be linked from the admin side.

The operator's report: a returning player introduced himself with his full name,
the bot filed a claim because the player row still carried the short name, the
admin renamed the row to the declared name — and the card stayed buttonless.
Then, with both the player and the Bale account on file, the admin was told the
link could only come «از سمت خود بازیکن».
"""

import json
import unittest

from app.service import normalize
from tests.test_sans import BaseCase


class KnownAccountBindingTests(BaseCase):
    """AC-001..AC-009: a rename revives the claim, and a known account binds."""

    SHORT = 'قامتی'
    FULL = 'امیرحسین قامتی'
    PHONE = '+989121110000'

    def setUp(self):
        super().setUp()
        self.seed(linked=False)

    # --- helpers ---------------------------------------------------------

    def card_texts(self, chat=None):
        rows = [json.loads(r['payload']) for r in
                self.db.all("SELECT payload FROM outbox WHERE method='sendMessage' ORDER BY id")]
        return [p['text'] for p in rows if chat is None or p['chat_id'] == chat]

    def buttons(self, chat=None):
        found = []
        rows = [json.loads(r['payload']) for r in
                self.db.all("SELECT payload FROM outbox WHERE method='sendMessage' ORDER BY id")]
        for payload in rows:
            if chat is not None and payload['chat_id'] != chat:
                continue
            for row in (payload.get('reply_markup') or {}).get('inline_keyboard', []):
                found += [button['callback_data'] for button in row]
        return found

    def introduce(self, user_id=40, name=None, phone=PHONE):
        """A returning player opens the bot and shares his number."""
        self.send(sender={'id': user_id, 'first_name': self.FULL},
                  user=user_id, chat=user_id,
                  contact={'user_id': user_id, 'phone_number': phone})
        self.send('/identify ' + (name or self.FULL), user=user_id, chat=user_id)

    def open_claim(self):
        return self.db.one("SELECT * FROM pending WHERE kind='claim' AND status='pending'")

    def tools(self, admin=True, user=1, chat=-100):
        return {tool.name: tool for tool in
                self.bot.agent._make_tools(chat, user, admin, {'first_name': 'ادمین'}, {})}

    def binding_cards(self):
        return self.db.all("SELECT * FROM pending WHERE kind='binding'")

    # --- AC-001..AC-002: the rename makes the claim clickable ------------

    def test_rename_attaches_the_open_claim(self):
        # AC-001: the admin's own step — renaming the row to the declared name.
        self.apply('new_player', name=self.SHORT)
        player = self.db.one('SELECT * FROM players WHERE normalized_name=?', (normalize(self.SHORT),))
        self.introduce()
        claim = self.open_claim()
        self.assertIsNotNone(claim)
        self.assertNotIn('yes:' + claim['id'], self.buttons(self.config.admin_group))

        self.send('/rename %d %s' % (player['id'], self.FULL), user=1, chat=self.config.admin_group)

        row = self.db.one('SELECT * FROM pending WHERE id=?', (claim['id'],))
        self.assertEqual(row['kind'], 'identity')
        self.assertEqual(json.loads(row['payload'])['player'], player['id'])
        self.assertIn('yes:' + claim['id'], self.buttons(self.config.admin_group))
        self.assertIn('کارت', self.card_texts(self.config.admin_group)[-1])

        self.click('yes:' + claim['id'])
        self.assertEqual(self.service.linked(40)['id'], player['id'])

    def test_the_agent_rename_attaches_the_open_claim(self):
        # AC-002: the path the model actually takes when the admin says «همون
        # بازیکن هست، اسم کاملش اینه».
        self.apply('new_player', name=self.SHORT)
        player = self.db.one('SELECT * FROM players WHERE normalized_name=?', (normalize(self.SHORT),))
        self.introduce()
        claim = self.open_claim()

        answer = self.tools()['manage_records'].invoke(
            {'operation': 'rename_player',
             'data_json': json.dumps({'player': '#' + str(player['id']), 'name': self.FULL},
                                     ensure_ascii=False)})

        self.assertEqual(self.db.one('SELECT kind FROM pending WHERE id=?',
                                     (claim['id'],))['kind'], 'identity')
        self.assertIn('yes:' + claim['id'], self.buttons(self.config.admin_group))
        self.assertIn('کارت', answer)

    # --- AC-003..AC-004: binding an account the bot has seen -------------

    def test_the_admin_binds_a_known_account_by_id(self):
        # AC-003: both ends are known; one command and one click join them.
        self.send(sender={'id': 30, 'first_name': self.FULL}, user=30, chat=30)
        self.send('/bind 1 30', user=1, chat=self.config.admin_group)

        cards = self.binding_cards()
        self.assertEqual(len(cards), 1)
        payload = json.loads(cards[0]['payload'])
        self.assertEqual(payload['player'], 1)
        self.assertEqual(payload['user_id'], 30)
        self.assertIn('yes:' + cards[0]['id'], self.buttons(self.config.admin_group))
        # Nothing is bound before the click.
        self.assertIsNone(self.service.player(1)['bale_id'])
        self.assertIsNone(self.service.linked(30))

        self.click('yes:' + cards[0]['id'])

        self.assertEqual(self.service.player(1)['bale_id'], 30)
        self.assertEqual(self.service.linked(30)['id'], 1)
        self.assertTrue(self.db.one("SELECT id FROM audit_logs WHERE action='bind'"))

    def test_the_admin_binds_a_known_account_by_phone(self):
        # AC-004: the number the admin has in front of him is enough.
        self.introduce(user_id=31)
        with self.db.conn:
            self.db.execute("UPDATE pending SET status='rejected'")
        self.send('/bind 2 ' + self.PHONE, user=1, chat=self.config.admin_group)

        cards = self.binding_cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(json.loads(cards[0]['payload'])['user_id'], 31)
        self.click('yes:' + cards[0]['id'])
        self.assertEqual(self.service.linked(31)['id'], 2)

    # --- AC-005..AC-007: the refusals ------------------------------------

    def test_an_unknown_account_is_refused(self):
        # AC-005: an id nobody has ever used with the bot binds nothing.
        self.send('/bind 1 99999999', user=1, chat=self.config.admin_group)

        self.assertFalse(self.binding_cards())
        self.assertIsNone(self.service.player(1)['bale_id'])
        self.assertIn('با ربات', self.card_texts(self.config.admin_group)[-1])

    def test_a_linked_player_or_account_is_refused(self):
        # AC-006: no second binding, from either side.
        with self.db.conn:
            self.service.bind(1, 10, 1)
        self.send(sender={'id': 30, 'first_name': 'دیگری'}, user=30, chat=30)

        self.send('/bind 1 30', user=1, chat=self.config.admin_group)
        self.send('/bind 2 10', user=1, chat=self.config.admin_group)

        self.assertFalse(self.binding_cards())
        self.assertEqual(self.service.player(1)['bale_id'], 10)
        self.assertIsNone(self.service.player(2)['bale_id'])

    def test_only_an_admin_can_bind_an_account(self):
        # AC-007: the tool refuses a non-admin, and /bind is not a player command.
        self.send(sender={'id': 30, 'first_name': self.FULL}, user=30, chat=30)

        answer = self.tools(admin=False, user=30, chat=30)['manage_records'].invoke(
            {'operation': 'bind_account',
             'data_json': json.dumps({'player': '#1', 'user': 30})})
        self.send('/bind 1 30', user=30, chat=30)

        self.assertFalse(self.binding_cards())
        self.assertIsNone(self.service.player(1)['bale_id'])
        self.assertIn('ادمین', answer)

    # --- AC-008..AC-009: compatibility and no model ----------------------

    def test_a_two_word_name_still_needs_a_reply(self):
        # AC-008: `/bind <name with spaces>` keeps its meaning; the second word
        # is never mistaken for an account.
        self.send(sender={'id': 30, 'first_name': self.FULL}, user=30, chat=30)
        self.send('/bind رضا محمدی', user=1, chat=self.config.admin_group)

        self.assertFalse(self.binding_cards())
        self.assertIn('ریپلای', self.card_texts(self.config.admin_group)[-1])

    def test_the_card_is_not_built_by_the_model(self):
        # AC-009: the binding card is deterministic bot output.
        self.send(sender={'id': 30, 'first_name': self.FULL}, user=30, chat=30)
        before = len(self.ai.calls)
        self.send('/bind 1 30', user=1, chat=self.config.admin_group)
        self.assertEqual(len(self.ai.calls), before)


if __name__ == '__main__':
    unittest.main()
