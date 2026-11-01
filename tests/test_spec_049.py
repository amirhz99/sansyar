"""SPEC-049: a debt answer is short and carries the card, the details are opt-in.

The operator's request: say the balance briefly, give the card number in the same
message, and keep the per-session history for when the person asks for it.
"""

import unittest

from app.domain import ResponseLevel
from tests.test_sans import BaseCase

CARD = '5041721076234674 (بانک رسالت)'


class ShortDebtTests(BaseCase):
    """AC-001..AC-004: short by default, full on request, card next to the debt."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.apply('adjustment', player=1, amount=350000, note='بدهی قبلی')
        with self.db.conn:
            self.db.set_setting('card', CARD)
            self.db.set_setting('payment_note', 'رسید را همین‌جا بفرستید.')

    def test_the_summary_carries_the_balance_and_the_card(self):
        reply = self.service.debt(1, ResponseLevel.SUMMARY)

        self.assertIn('علی رضایی', reply)
        self.assertIn('بدهی: 350,000 تومان', reply)
        self.assertIn(f'کارت: {CARD}', reply)
        self.assertIn('رسید را همین‌جا بفرستید.', reply)
        self.assertNotIn('گردش حساب', reply)          # no ledger walk
        self.assertLessEqual(len(reply.splitlines()), 6)

    def test_the_full_report_still_exists(self):
        reply = self.service.debt(1)                  # the default stays DETAILS

        self.assertIn('گردش حساب', reply)
        self.assertIn('بدهی قبلی', reply)

    def test_a_settled_account_shows_no_card(self):
        self.apply('adjustment', player=1, amount=-350000, note='تسویه')

        reply = self.service.debt(1, ResponseLevel.SUMMARY)

        self.assertIn('مانده: 0 تومان', reply)
        self.assertNotIn('کارت:', reply)

    def test_the_command_is_short_and_its_detail_word_is_not(self):
        self.send('/debt', user=10, chat=10)
        short = self.replies(10)
        self.assertIn('بدهی: 350,000 تومان', short)
        self.assertIn('کارت:', short)
        self.assertNotIn('گردش حساب', short)

        self.send('/debt ریز', user=10, chat=10)
        self.assertIn('گردش حساب', self.replies(10))

    def test_the_tool_is_short_until_the_model_asks_for_full(self):
        bot = self.bot
        tools = {tool.name: tool for tool in
                 bot.agent._make_tools(10, 10, False, {'first_name': 'علی'}, {})}

        short = tools['query_database'].invoke({'target': 'debt'})
        self.assertIn('بدهی: 350,000 تومان', short)
        self.assertIn('کارت:', short)
        self.assertNotIn('گردش حساب', short)

        full = tools['query_database'].invoke({'target': 'debt', 'detail': 'full'})
        self.assertIn('گردش حساب', full)


if __name__ == '__main__':
    unittest.main()