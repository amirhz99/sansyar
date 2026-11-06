"""SPEC-053: a card the bot says «تأیید را بزنید» about always has a button.

The operator's report: «به ربات گفتم سید امین طاهری رو و سید مجتبی طاهری رو به
هم لینک کنه … ولی برام یه متن فرستاد که تایید رو بزن ولی دکمه تایید نداشت».

Cause: the agent tool `manage_records` built the `player_link` card and then threw
its markup away (`reply, _ = bot.propose(...)`), so `effects['markup']` stayed
empty, the answer was text-only, and the pending row was never delivered.
`suggest_links` had the same defect, and its multi-pair card was refused as a
duplicate because the batch check ignored the partner.
"""

import json
import unittest

from app.bot import Bot
from tests.test_sans import BaseCase


class UndeliveredCardTests(BaseCase):
    """AC-001..AC-005: every card that is announced is also clickable."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.apply('new_player', name='سید امین طاهری')
        self.apply('new_player', name='سید مجتبی طاهری')

    def tools(self, admin=True):
        return {tool.name: tool for tool in
                self.bot.agent._make_tools(-100, 1, admin, {'first_name': 'علی'}, {})}

    def card_data(self, chat=-100):
        """Return every callback data delivered to ``chat``."""
        found = []
        for row in self.db.all("SELECT payload FROM outbox WHERE method='sendMessage' ORDER BY id"):
            payload = json.loads(row['payload'])
            if payload['chat_id'] != chat:
                continue
            for line in (payload.get('reply_markup') or {}).get('inline_keyboard', []):
                found += [button['callback_data'] for button in line]
        return found

    def link_card(self):
        return self.db.one("SELECT * FROM pending WHERE kind='commands' "
                           "ORDER BY created_at DESC LIMIT 1")

    def agent_turn(self, text, operation, data):
        """Run one real agent turn with a scripted model, like production does."""
        from langchain_core.messages import AIMessage

        class Scripted:
            def __init__(self):
                self.calls = 0

            def bind_tools(self, tools):
                return self

            def invoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    return AIMessage(content='', tool_calls=[{
                        'id': 'link-1', 'name': 'manage_records',
                        'args': {'operation': operation,
                                 'data_json': json.dumps(data, ensure_ascii=False)},
                    }])
                return AIMessage(content='کارت آماده شد؛ تأیید را بزنید.')

        class Driver:
            use_langgraph = True

            def __init__(self):
                self.llm_override = Scripted()

        bot = Bot(self.db, self.config, Driver())
        self.update_id += 1
        with self.db.conn:
            self.db.set_setting('welcomed:1', 1)
        bot.process({'update_id': self.update_id, 'message': {
            'message_id': self.update_id,
            'chat': {'id': -100, 'type': 'group'},
            'from': {'id': 1, 'first_name': 'ادمین'},
            'text': text,
        }})
        return bot

    def test_a_link_answer_always_carries_the_button(self):
        # AC-001: the live defect.  The answer says «تأیید را بزنید», so the
        # button must be on the wire for that turn.
        self.agent_turn('مسئول سید امین طاهری رو با سید مجتبی طاهری لینک کن',
                        'link_players', {'player': '#3', 'partner': '#4'})

        card = self.link_card()
        self.assertIn('yes:' + card['id'], self.card_data())

    def test_the_button_actually_links(self):
        # AC-002: clicking it creates the link, and the two partners then see
        # each other's balance.
        self.agent_turn('مسئول سید امین طاهری رو با سید مجتبی طاهری لینک کن',
                        'link_players', {'player': '#3', 'partner': '#4'})
        card = self.link_card()
        self.click('yes:' + card['id'])

        self.assertTrue(self.service.are_linked(3, 4))
        self.assertIn('حساب‌های پیوندی', self.service.shared_links(3))

    def test_suggest_links_sends_one_clickable_card_for_every_pair(self):
        # AC-003: three players of one family are three different pairs; they
        # ride on one card whose buttons are handed to the answer.
        self.apply('new_player', name='سید محمد طاهری')
        effects = {}
        tools = {tool.name: tool for tool in
                 self.bot.agent._make_tools(-100, 1, True, {'first_name': 'علی'}, effects)}
        answer = tools['manage_records'].invoke(
            {'operation': 'suggest_links', 'data_json': '{}'})

        cards = self.db.all("SELECT id,payload FROM pending WHERE kind='commands'")
        self.assertEqual(len(cards), 1)
        self.assertEqual(len(json.loads(cards[0]['payload'])), 3)
        self.assertIn('yes:' + cards[0]['id'], json.dumps(effects['markup'], ensure_ascii=False))
        self.assertNotIn('تکراری', answer)

    def test_a_player_chat_is_never_swept(self):
        # AC-006: `pending.chat_id` is where the request was filed, not where the
        # card went.  Sweeping a private chat would leak an admin card into it.
        with self.db.conn:
            card_id = self.bot.new_pending(
                'commands',
                [self.service.prepare('player_link', {'player': 3, 'partner': 4})], 10, 10)

        self.assertEqual(self.bot.deliver_undelivered_cards(10, None, 0), [])
        self.assertEqual(self.card_data(10), [])
        self.assertIsNotNone(card_id)

    def test_a_forgotten_markup_still_delivers_the_card(self):
        # AC-004: the safety net.  A path that creates a card and forgets the
        # markup must not leave the admin with a text-only answer.
        with self.db.conn:
            card_id = self.bot.new_pending(
                'commands',
                [self.service.prepare('player_link', {'player': 3, 'partner': 4})], 1, -100)
        self.db.say(-100, 'کارت ساخته شد؛ تأیید را بزنید.', None)
        with self.db.conn:
            sent = self.bot.deliver_undelivered_cards(-100, None, 0)

        self.assertEqual(sent, [card_id])
        self.assertIn('yes:' + card_id, self.card_data())

    def test_the_card_carried_by_the_answer_is_not_sent_twice(self):
        # AC-004: the net skips the card the answer already carried.
        self.agent_turn('مسئول سید امین طاهری رو با سید مجتبی طاهری لینک کن',
                        'link_players', {'player': '#3', 'partner': '#4'})
        card = self.link_card()
        markup = [[{'text': 'تأیید', 'callback_data': 'yes:' + card['id']},
                   {'text': 'رد', 'callback_data': 'no:' + card['id']}]]
        with self.db.conn:
            again = self.bot.deliver_undelivered_cards(-100, markup, 0)

        self.assertEqual(again, [])
        self.assertEqual(self.card_data().count('yes:' + card['id']), 1)

    def test_an_already_delivered_card_is_left_alone(self):
        # AC-005: a card with a recorded message id is never re-sent, so the
        # admin cannot see the same proposal twice.
        self.agent_turn('مسئول سید امین طاهری رو با سید مجتبی طاهری لینک کن',
                        'link_players', {'player': '#3', 'partner': '#4'})
        card = self.link_card()
        with self.db.conn:
            self.db.execute('UPDATE pending SET message_id=? WHERE id=?', (777, card['id']))
            again = self.bot.deliver_undelivered_cards(-100, None, 0)

        self.assertEqual(again, [])
        self.assertEqual(self.card_data().count('yes:' + card['id']), 1)


if __name__ == '__main__':
    unittest.main()