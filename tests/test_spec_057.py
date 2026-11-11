"""SPEC-057: the card says it once, and the bot does not repeat it.

The admins' report: «پیام‌ها یه مقدار طولانیه هم تو گروه ادمین هم بعضی اوقات به
کاربران… میخوام یکم کوتاه‌تر جواب بدی، نوشتهٔ اضافه نداشته باشی».

Measured on 117 live answers: median 417 characters, p90 859, longest 1455.  The
longest ones say the same thing two or three times, because every card-producing
tool hands the whole card back to the model and the answer then carries the card
again.  Nothing here truncates a text: the repetition and the boilerplate go, and
every fact an admin approves stays on the card.
"""

import json
import unittest

from app.agent import AGENT_SYSTEM_PROMPT
from tests.test_sans import BaseCase


class ShortAnswerTests(BaseCase):
    """AC-001..AC-007: same facts, said once."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.apply('attendance', session=1, player=1, guests=2)
        self.apply('attendance', session=1, player=2)

    def tools(self, admin=True):
        self.effects = {}
        return {tool.name: tool for tool in
                self.bot.agent._make_tools(-100, 1, admin, {'first_name': 'علی'}, self.effects)}

    def finalize_card(self, session=1):
        return self.service.preview(self.service.prepare('finalize', {'session': session}))

    def test_the_tool_result_does_not_echo_the_card(self):
        # AC-001: the model repeats whatever the tool hands it, so the tool must
        # hand it the instruction, not the card.
        tools = self.tools()
        answer = tools['propose_financial_change'].invoke({'action': 'finalize', 'session': '1'})

        preview = self.effects['proposal_preview']
        self.assertIn('جمع بدهی جدید', preview)
        self.assertNotIn(preview, answer)
        self.assertNotIn('جمع بدهی جدید', answer)
        self.assertIn('بازگو نکن', answer)
        self.assertIsNotNone(self.effects['markup'])

    def test_the_finalize_card_names_everyone_once(self):
        # AC-002: the names are what the admin approves, so they stay — once.
        text = self.finalize_card()

        self.assertIn('علی رضایی', text)
        self.assertIn('رضا محمدی', text)
        self.assertEqual(text.count('علی رضایی'), 1)
        self.assertEqual(text.count('رضا محمدی'), 1)
        self.assertIn('2 نفر', text)
        self.assertIn('جمع بدهی جدید', text)
        # The fee is stated once, in the summary line, not once per player.
        self.assertEqual(text.count('150,000'), 1)
        self.assertNotIn('مهمان، 150,000', text)
        self.assertLess(len(text), 400)

    def test_the_venue_note_only_appears_with_a_venue_cost(self):
        # AC-003: boilerplate that is true of every session is noise.
        self.assertIn('هزینهٔ زمین', self.finalize_card())

        self.apply('new_session', title='سانس بی‌زمین', when_text='جمعه ساعت ۲۰', venue_cost=0)
        self.apply('attendance', session=2, player=1)
        text = self.finalize_card(2)

        self.assertNotIn('هزینهٔ زمین', text)
        self.assertIn('جمع بدهی جدید', text)

    def test_a_broadcast_card_caps_each_name_list(self):
        # AC-004: an admin never verifies seven names on a card; the count is the
        # fact and the rest is one message away.
        names = [f'بازیکن شماره {index}' for index in range(1, 8)]
        for user_id, name in enumerate(names, start=100):
            self.apply('new_player', name=name)
            player = self.db.one('SELECT id FROM players WHERE name=?', (name,))
            with self.db.conn:
                self.service.bind(player['id'], user_id, 1)
        preview = self.service.preview(
            self.service.prepare('broadcast', {'text': 'سانس فردا لغو شد',
                                              'players': '، '.join(names)}))

        self.assertIn('گیرندگان (7 نفر)', preview)
        self.assertIn('و 2 نفر دیگر', preview)
        self.assertNotIn('پیام فقط پس از تأیید شما ارسال می‌شود', preview)

    def test_the_card_tail_is_the_bare_code(self):
        # AC-005: the buttons ask the question; the code stays for reference.
        command = self.service.prepare('adjustment', {'player': 1, 'amount': -50000,
                                                     'note': 'اصلاح'})
        with self.db.conn:
            text, markup = self.bot.propose_commands([command], 1, -100)
        ident = markup[0][0]['callback_data'].split(':', 1)[1]

        self.assertTrue(text.rstrip().endswith(f'کد: {ident}'))
        self.assertNotIn('ثبت شود؟', text)
        self.assertNotIn('تمام مبلغ‌ها تومان هستند', text)

    def test_the_prompt_asks_for_a_short_answer(self):
        # AC-006: the rule lives in the prompt; no code truncates a reply.
        self.assertIn('دو خط', AGENT_SYSTEM_PROMPT)
        self.assertIn('بازگو نکن', AGENT_SYSTEM_PROMPT)
        self.assertIn('جمع‌بندی پایانی', AGENT_SYSTEM_PROMPT)

    def test_a_batch_card_keeps_its_skip_note(self):
        # AC-007: the one thing the model must say is what fell outside the card.
        self.apply('adjustment', player=1, amount=150000, note='بدهی سانس')
        tools = self.tools()
        answer = tools['propose_financial_change'].invoke({
            'action': 'settle', 'players': 'علی رضایی، رضا محمدی'})

        self.assertIn('بدون بدهی', answer)
        self.assertIn('رضا محمدی', answer)
        self.assertNotIn(self.effects['proposal_preview'], answer)
        self.assertIsNotNone(self.effects['markup'])


if __name__ == '__main__':
    unittest.main()
