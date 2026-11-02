"""SPEC-047: a failed model is asked once more before the fallback is used.

The operator's requirement is simple: if the provider drops one request, retry
that same model once — do not jump to a different model (or to the failure line)
on a single failure.

``SansAgent.run`` builds one client per model with ``type(llm)(model=...)``, so
the stub keeps its script at class level: a new instance is created for every
fallback model.
"""

import json
import unittest
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app import agent as agent_module
from app.bot import Bot
from tests.test_sans import BaseCase


class ScriptedProvider:
    """A fake provider: ``{model: (failures, answer)}`` shared by all instances."""

    script = {}
    calls = {}
    error = RuntimeError('HTTP 503')

    def __init__(self, **kwargs):
        self.model = kwargs.get('model')

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        ScriptedProvider.calls[self.model] = ScriptedProvider.calls.get(self.model, 0) + 1
        failures, answer = ScriptedProvider.script.get(self.model, (0, 'پاسخ مدل'))
        if ScriptedProvider.calls[self.model] <= failures:
            raise ScriptedProvider.error
        return AIMessage(content=answer)


class ModelRetryTests(BaseCase):
    """AC-001..AC-003: one retry per model, bounded, and always logged."""

    def setUp(self):
        super().setUp()
        self.seed()
        with self.db.conn:
            self.db.set_setting('welcomed:10', 1)

    def script(self, **per_model):
        ScriptedProvider.script = dict(per_model)
        ScriptedProvider.calls = {}

    def run_turn(self, body='وضعیت این هفته چطوره؟'):
        bot = Bot(self.db, self.config, SimpleNamespace(use_langgraph=True))
        name = next(item for item in dir(agent_module)
                    if item.startswith('Chat') and item.endswith('AI'))
        with patch.object(agent_module, name, side_effect=lambda **kwargs: ScriptedProvider(**kwargs)):
            bot.process({'update_id': 1, 'message': {
                'message_id': 1, 'chat': {'id': 10, 'type': 'private'},
                'from': {'id': 10}, 'text': body}})
        return bot

    def replies(self):
        return [json.loads(row['payload'])['text'] for row in
                self.db.all("SELECT payload FROM outbox WHERE method='sendMessage'")]

    def events(self):
        return [row['event'] for row in self.db.recent_agent_logs(40)]

    def test_a_transient_error_is_retried_on_the_same_model(self):
        self.script(**{'fake-model': (1, 'پاسخ سالم پس از تلاش دوم')})

        self.run_turn()

        self.assertEqual(ScriptedProvider.calls, {'fake-model': 2})   # one retry
        self.assertIn('پاسخ سالم پس از تلاش دوم', self.replies()[-1])
        events = self.events()
        self.assertIn('LLM_RETRY', events)
        self.assertNotIn('LLM_FALLBACK', events)

    def test_a_model_that_keeps_failing_is_replaced_by_the_fallback(self):
        self.script(**{'fake-model': (2, ''), 'fallback-model': (0, 'پاسخ مدل جایگزین')})
        self.config = replace(self.config, ai_fallback_models=('fallback-model',))

        self.run_turn()

        # Two attempts on the primary, then the fallback answers on its first.
        self.assertEqual(ScriptedProvider.calls,
                         {'fake-model': 2, 'fallback-model': 1})
        self.assertIn('پاسخ مدل جایگزین', self.replies()[-1])
        events = self.events()
        self.assertEqual(events.count('LLM_RETRY'), 2)
        self.assertIn('LLM_FALLBACK', events)

    def test_the_retry_is_bounded_and_every_model_is_tried(self):
        dead = (999, '')
        self.script(**{'fake-model': dead, 'fallback-one': dead, 'fallback-two': dead})
        self.config = replace(self.config,
                              ai_fallback_models=('fallback-one', 'fallback-two'))

        self.run_turn()

        # Three models × at most two attempts each, never a third.
        self.assertEqual(Counter(ScriptedProvider.calls),
                         Counter({'fake-model': 2, 'fallback-one': 2, 'fallback-two': 2}))
        self.assertIn('سرویس هوش مصنوعی', self.replies()[-1])


if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()