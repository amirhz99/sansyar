"""SPEC-052: a new player's identity card becomes actionable on its own.

The operator's report: a brand-new player (محمدطه مقدم) introduced himself in a
private chat, the bot filed a *claim* because no player carried that name, the
admin was told to «create the player and then link», he did create it — and the
card still could not be approved.  The claim had no player and no button, and
nothing connected the new player to it.
"""

import json
import unittest

from app.service import normalize
from tests.test_sans import BaseCase


class ClaimCardTests(BaseCase):
    """AC-001..AC-005: creating the player is enough to get a clickable card."""

    NAME = 'محمدطه مقدم'
    PHONE = '+989123333807'

    def setUp(self):
        super().setUp()
        self.seed(linked=False)

    def claim(self):
        return self.db.one("SELECT * FROM pending WHERE kind='claim' AND status='pending'")

    def player_row(self, name=None):
        return self.db.one('SELECT * FROM players WHERE normalized_name=?',
                           (normalize(name or self.NAME),))

    def new_request(self, name=None):
        self.send(sender={'id': 10}, contact={'user_id': 10, 'phone_number': self.PHONE})
        self.send(f'/identify {name or self.NAME}')

    def sent(self, chat=-100):
        rows = [json.loads(r['payload']) for r in
                self.db.all("SELECT payload FROM outbox WHERE method='sendMessage' ORDER BY id")]
        return [payload for payload in rows if payload['chat_id'] == chat]

    def buttons(self, chat=-100):
        found = []
        for payload in self.sent(chat):
            for row in (payload.get('reply_markup') or {}).get('inline_keyboard', []):
                found += [button['callback_data'] for button in row]
        return found

    def test_creating_the_player_makes_the_card_clickable(self):
        # AC-001: the path the card itself asks for (/newplayer, then approve).
        self.new_request()
        claim = self.claim()
        self.assertNotIn('yes:' + claim['id'], self.buttons())
        self.assertIn('mk:' + claim['id'], self.buttons())

        self.send('/newplayer ' + self.NAME, user=1, chat=-100)
        self.click('yes:' + self.proposal())

        row = self.db.one('SELECT * FROM pending WHERE id=?', (claim['id'],))
        self.assertEqual(row['kind'], 'identity')
        self.assertEqual(json.loads(row['payload'])['player'], self.player_row()['id'])
        self.assertIn('yes:' + claim['id'], self.buttons())

        self.click('yes:' + claim['id'])
        self.assertEqual(self.service.linked(10)['name'], self.NAME)

    def test_the_agent_player_creation_attaches_the_claim(self):
        # AC-001: the same, through the tool the model actually uses.
        self.new_request()
        claim = self.claim()
        tools = {tool.name: tool for tool in
                 self.bot.agent._make_tools(-100, 1, True, {'first_name': 'علی'}, {})}
        answer = tools['manage_records'].invoke(
            {'operation': 'upsert_players',
             'data_json': json.dumps({'players': [{'name': self.NAME}]}, ensure_ascii=False)})

        self.assertIn('کارت اتصال حساب', answer)
        self.assertIn('yes:' + claim['id'], self.buttons())
        self.assertEqual(self.db.one('SELECT kind FROM pending WHERE id=?',
                                     (claim['id'],))['kind'], 'identity')

    def test_one_click_creates_the_player_and_returns_the_card(self):
        # AC-002: a brand-new name needs no memorised request code.
        self.new_request()
        claim = self.claim()
        self.click('mk:' + claim['id'])

        player = self.player_row()
        self.assertIsNotNone(player)
        self.assertEqual(player['name'], self.NAME)
        self.assertEqual(self.db.one('SELECT kind FROM pending WHERE id=?',
                                     (claim['id'],))['kind'], 'identity')
        self.assertIn('yes:' + claim['id'], self.buttons())
        self.assertIn('ساخته و به درخواست', self.replies(-100))

        self.click('yes:' + claim['id'])
        self.assertEqual(self.service.linked(10)['id'], player['id'])
        # The number the request carried is attached by the approval (SPEC-021).
        self.assertEqual(self.service.player(player['id'])['phone'], self.PHONE)

    def test_the_claim_card_can_be_rejected(self):
        # AC-002: the second button closes the claim without any side effect.
        self.new_request()
        claim = self.claim()
        self.assertIn('no:' + claim['id'], self.buttons())

        self.click('no:' + claim['id'])

        self.assertEqual(self.db.one('SELECT status FROM pending WHERE id=?',
                                     (claim['id'],))['status'], 'rejected')
        self.assertIsNone(self.player_row())
        self.assertIsNone(self.service.linked(10))

    def test_a_similar_name_is_not_attached(self):
        # AC-003: only an equal normalized name is attached; a near miss stays a
        # human decision, exactly as /link leaves it.
        self.new_request(name='محمد طاها مقدمی')
        claim = self.claim()
        with self.db.conn:
            self.db.execute('INSERT INTO players(name, normalized_name, note) VALUES (?,?,?)',
                            ('محمدطه مقدم', normalize('محمدطه مقدم'), ''))
        self.bot.attach_claims(self.service.player('محمدطه مقدم'), 1)

        self.assertEqual(self.db.one('SELECT kind FROM pending WHERE id=?',
                                     (claim['id'],))['kind'], 'claim')
        self.assertNotIn('yes:' + claim['id'], self.buttons())

    def test_the_card_is_sent_once_per_claim(self):
        # AC-004: a second attach cannot duplicate the card or re-approve it.
        self.new_request()
        claim = self.claim()
        self.click('mk:' + claim['id'])
        self.click('yes:' + claim['id'])

        self.assertEqual(self.buttons().count('yes:' + claim['id']), 1)
        self.assertEqual(self.service.linked(10)['name'], self.NAME)
        self.assertFalse(self.bot.attach_claims(self.service.linked(10), 1))

    def test_a_player_cannot_press_the_create_button(self):
        # AC-005: the button is an admin power, like every other card.
        self.new_request()
        claim = self.claim()
        self.click('mk:' + claim['id'], user=99, chat=-200)

        self.assertIsNone(self.player_row())
        self.assertEqual(self.db.one('SELECT kind FROM pending WHERE id=?',
                                     (claim['id'],))['kind'], 'claim')

    def test_the_card_is_not_built_by_the_model(self):
        # AC-005: the card is a deterministic reply, never a model answer.
        self.new_request()
        self.assertFalse(self.ai.calls)


if __name__ == '__main__':
    unittest.main()