"""SPEC-054: the after-approval report belongs to the card that was approved.

The operator's report: «واسه همه کارتا بعد ثبت شد یه قیمت گزارش میده که من اونو
برای تغییر بدهی و اینا میخواستم نه روی هر کارتی دیگه؛ توی کارتای دیگه گزارش
خودشونو بده که چی شدش.»

Live proof: approving the broadcast card `a5110346c0924857` (one message to سید
امین) ended with «#20 سید امین طاهری: مانده 0 تومان», which reads like a price
change although no money moved.
"""

import json
import unittest

from tests.test_sans import BaseCase


class CardSpecificReportTests(BaseCase):
    """AC-001..AC-006: money cards report money, every other card its own result."""

    def setUp(self):
        super().setUp()
        self.seed()
        self.apply('adjustment', player=1, amount=350000, note='بدهی قبلی')

    def report(self, command):
        return self.service.applied_report([command])

    def prepare(self, action, **args):
        return self.service.prepare(action, args)

    def test_a_money_card_reports_the_balance(self):
        # AC-001: adjustment, settle and declare_debt are the balance cards.
        adjustment = self.report(self.prepare('adjustment', player=1, amount=-50000))
        self.assertIn('#1 علی رضایی: مانده 350,000 تومان', adjustment)

        settlement = self.report(self.prepare('settle', player=1))
        self.assertIn('مانده 350,000 تومان', settlement)

    def test_a_broadcast_reports_its_audience_and_no_amount(self):
        # AC-002: the live defect.  A message card moved no money.
        command = self.prepare('broadcast', text='سانس فردا لغو شد', players='علی رضایی')
        with self.db.conn:
            self.service.apply(command, 1, 'test:broadcast')
        text = self.report(command)

        self.assertIn('برای 1 مخاطب', text)
        self.assertNotIn('مانده', text)
        self.assertNotIn('تومان', text)

    def test_a_link_card_reports_the_pair(self):
        # AC-003: linking is a read permission, not a financial movement.
        command = self.prepare('player_link', player=1, partner=2)
        with self.db.conn:
            self.service.apply(command, 1, 'test:link')
        text = self.report(command)

        self.assertIn('علی رضایی ↔', text)
        self.assertIn('پیوند برقرار شد', text)
        self.assertNotIn('مانده', text)

    def test_a_new_player_card_reports_the_creation(self):
        # AC-004: the outcome is the new row, not a zero balance.
        command = self.prepare('new_player', name='سعید کاظمی')
        with self.db.conn:
            self.service.apply(command, 1, 'test:new')
        text = self.report(command)

        self.assertIn('«سعید کاظمی» ثبت شد', text)
        self.assertNotIn('مانده', text)

    def test_a_settings_card_reports_the_stored_value_in_words(self):
        # AC-005: a default fee is shown the way it is displayed everywhere.
        command = self.prepare('settings', key='default_person_fee', value='200000')
        with self.db.conn:
            self.service.apply(command, 1, 'test:setting')
        text = self.report(command)

        self.assertIn('سهم هر نفر پیش‌فرض', text)
        self.assertIn('200,000 تومان', text)
        self.assertNotIn('مانده', text)

    def test_a_session_card_reports_the_session_only(self):
        # AC-006: an attendance card describes the session, never a player.
        command = self.prepare('attendance', session=1, player=1)
        with self.db.conn:
            self.service.apply(command, 1, 'test:attendance')
        text = self.report(command)

        self.assertIn('سانس #1', text)
        self.assertIn('1 حاضر', text)
        self.assertNotIn('مانده', text)

    def test_a_batch_reports_each_card_kind_once(self):
        # AC-001/AC-002: a mixed batch keeps every line distinct and deduplicated.
        link = self.prepare('player_link', player=1, partner=2)
        with self.db.conn:
            self.service.apply(link, 1, 'test:link')
        text = self.service.applied_report([
            link,
            self.prepare('adjustment', player=1, amount=-50000),
        ])

        self.assertIn('پیوند برقرار شد', text)
        self.assertIn('مانده 350,000 تومان', text)
        self.assertEqual(text.count('مانده'), 1)

    def test_an_unknown_action_reports_nothing(self):
        # AC-006: no line is better than a misleading one.
        self.assertEqual(self.report({'action': 'unknown', 'args': {'player': 1}}), '')
        self.assertEqual(json.dumps(self.report({'action': 'player_delete',
                                                 'args': {'player': 1}})), '""')


if __name__ == '__main__':
    unittest.main()