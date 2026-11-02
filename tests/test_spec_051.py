"""SPEC-051: group routing survives a misspelled bot name and is visible.

Two failures this guards against: the room writes «مسیول»/«مسول» and the bot
ignored the message, and a wrong `ADMIN_GROUP_ID` made the bot silent in the group
while every other health line stayed green.
"""

import unittest

from app import review
from tests.test_sans import BaseCase

GROUP = -1001234567890


class NameVariantTests(BaseCase):
    """AC-001/AC-002: the configured name is matched in its common spellings."""

    def setUp(self):
        super().setUp()
        self.config = type(self.config)(
            'fake-token', GROUP, frozenset(), 'https://example.com/v1', 'k', 'm',
            self.path, bot_name='مسئول')
        self.bot.config = self.config
        with self.db.conn:
            self.db.set_setting('bot_username', 'sansrobot')

    def addressed(self, body):
        return self.bot.addressed({'chat': {'id': GROUP, 'type': 'group'}}, body)

    def test_the_common_spellings_of_the_name_are_accepted(self):
        for body in ('مسئول بدهی من چقدره', 'مسیول بدهی من چقدره',
                     'مسول بدهی من چقدره', 'مسئول، سانس بعدی کیه؟'):
            self.assertTrue(self.addressed(body), body)

    def test_other_words_and_plain_chatter_are_still_ignored(self):
        for body in ('سلام بچه‌ها', 'مسئولیت با شماست', 'حالا چقدره بدهیش',
                     'من مسئولم امروز'):
            self.assertFalse(self.addressed(body), body)

    def test_a_command_and_the_username_still_work(self):
        self.assertTrue(self.addressed('/debt'))
        self.assertTrue(self.addressed('@sansrobot بدهی من چقدره'))

    def test_the_variants_come_from_the_configured_name(self):
        self.assertEqual(set(self.bot.name_variants('مسئول')),
                         {'مسئول', 'مسیول', 'مسول'})
        self.assertEqual(self.bot.name_variants(''), ())
        self.assertIn('منشی', self.bot.name_variants('منشي'))


class GroupHealthTests(BaseCase):
    """AC-003: the doctor notices a configured group that never receives."""

    def group_check(self, configured=GROUP):
        checks = review.health(self.db.path, configured)
        return next(item for item in checks if item['name'] == 'GROUP')

    def test_a_wrong_group_id_is_reported(self):
        with self.db.conn:
            self.db.log_agent_event(999, 999, 'کاربر', 'INCOMING', summary='سلام',
                                    details={'private': True})
        check = self.group_check()
        self.assertEqual(check['status'], 'WARN')
        self.assertIn(str(GROUP), check['detail'])

    def test_traffic_from_the_configured_group_is_ok(self):
        with self.db.conn:
            self.db.log_agent_event(GROUP, 1, 'ادمین', 'INCOMING', summary='مسئول',
                                    details={'private': False})
        self.assertEqual(self.group_check()['status'], 'OK')

    def test_no_line_when_no_group_is_configured(self):
        checks = review.health(self.db.path, None)
        self.assertNotIn('GROUP', [item['name'] for item in checks])


if __name__ == '__main__':
    unittest.main()