"""SPEC-055: the health block and the daily digest are readable, and honest.

The operator's report: «الان اولش می‌زنی Fail که یعنی چی چرا؟ بعد یکمم واضح‌ترشو
کن، خیلی قابل فهم نیست.»

Two things were wrong:

1. The verdict was a false alarm.  The queue line compared `MIN(next_attempt)` with
   the clock, but `next_attempt` is `0` for a message that was just queued and never
   tried — so a brand-new row looked 56 years overdue and the report said
   `FAIL … oldest overdue 1793873755s` while nothing was broken.
2. Every word was an English token (`outbox 1 rows`, `p50 0s`, `RESULT FAIL`) with no
   statement of what it meant or what to do about it.
"""

import time
import unittest

from app import review
from tests.test_sans import BaseCase


class ReadableHealthTests(BaseCase):
    """AC-001..AC-005: no false alarm, plain Persian, and an action per problem."""

    def setUp(self):
        super().setUp()
        with self.db.conn:
            self.db.set_setting('last_tick', int(time.time()))

    def checks(self):
        return {item['name']: item for item in review.health(self.db.path)}

    def queue_one(self, attempts=0, next_attempt=0.0):
        with self.db.conn:
            self.db.queue('sendMessage', {'chat_id': 1, 'text': 'x'})
            if attempts or next_attempt:
                self.db.execute('UPDATE outbox SET attempts=?, next_attempt=?',
                                (attempts, next_attempt))

    def test_a_freshly_queued_message_is_not_an_error(self):
        # AC-001: the live false alarm.  next_attempt=0 means «send now», not 1970.
        self.queue_one()

        queue = self.checks()['QUEUE']
        self.assertEqual(queue['status'], 'OK')
        self.assertIn('تازه', queue['detail'])
        self.assertNotIn('overdue', queue['detail'])
        self.assertNotIn(str(int(time.time()))[:4], queue['detail'])

    def test_a_stuck_message_is_reported_with_an_action(self):
        # AC-002: five failed attempts is a real problem, and the line says so.
        self.queue_one(attempts=5, next_attempt=time.time() + 600)

        queue = self.checks()['QUEUE']
        self.assertEqual(queue['status'], 'FAIL')
        self.assertIn('5 بار ناموفق', queue['detail'])
        self.assertIn('توکن', queue['advice'])

    def test_every_check_has_a_persian_label_and_status(self):
        # AC-003: the machine contract stays OK/WARN/FAIL for the callers.
        checks = review.health(self.db.path)
        self.assertTrue(checks)
        for check in checks:
            self.assertEqual(check['status'], check['status'].upper())
            self.assertIn(check['status'], ('OK', 'WARN', 'FAIL'))
            self.assertTrue(check['label'])
            self.assertFalse(check['label'].isascii())

    def test_the_health_block_is_readable_persian(self):
        # AC-004: no English tokens, and a verdict sentence in words.
        with self.db.conn:
            self.db.set_setting('last_tick', 1700000000)      # long ago: TICK fails
        text = review.render_health(review.health(self.db.path))

        self.assertIn('ضربان ربات', text)
        self.assertIn('خطا', text)
        self.assertIn('نتیجه', text)
        self.assertIn('باید رسیدگی شود', text)
        self.assertIn('↳', text)                              # the action line
        for token in ('RESULT', 'outbox', 'oldest', 'last loop', ' rows'):
            self.assertNotIn(token, text)

    def test_a_healthy_install_reports_no_action_lines(self):
        # AC-004: a clean report says so once and carries no advice.
        checks = [check for check in review.health(self.db.path) if check['status'] == 'OK']
        text = review.render_health(checks)

        self.assertIn('همه‌چیز سالم است', text)
        self.assertNotIn('↳', text)

    def test_the_digest_explains_the_verdict(self):
        # AC-005: the daily message leads with a sentence, not a status code.
        digest = review.digest_text(review.health(self.db.path), [], 1)

        self.assertIn('وضعیت کلی:', digest)
        self.assertNotIn('OK', digest)
        self.assertNotIn('FAIL', digest)
        self.assertIn('راهنما', digest)

    def test_the_digest_lists_only_the_problem_lines(self):
        # AC-005: a healthy day is short; a sick day names each problem.
        healthy = [dict(check, status='OK', advice='') for check in review.health(self.db.path)]
        short = review.digest_text(healthy, [], 1)
        self.assertIn('همهٔ بخش‌ها سالم‌اند', short)
        self.assertNotIn('•', short)

        self.queue_one(attempts=5, next_attempt=time.time() + 600)
        long = review.digest_text(review.health(self.db.path), [], 1)
        self.assertIn('• صف ارسال:', long)
        self.assertIn('↳', long)
        self.assertNotIn('همهٔ بخش‌ها سالم‌اند', long)

    def test_the_report_opens_with_a_plain_language_summary(self):
        # AC-005: the saved file explains itself before the raw table.
        text = review.report_text(review.health(self.db.path), [], 1)
        self.assertIn('## وضعیت به زبان ساده', text)
        self.assertIn('راهنما', text)


if __name__ == '__main__':
    unittest.main()