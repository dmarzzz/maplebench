import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('queue_runner', Path(__file__).parents[1] / 'scripts/run-openai-queue.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ActionBoundaryTest(unittest.TestCase):
    def action(self, **changes):
        value = dict(type='basic_attack', x=None, y=None, targetId=1000000032, skillId=None, waitMs=500)
        return value | changes

    def test_attack_preserves_model_selected_target(self):
        action, delay = runner.translate_action(self.action())
        self.assertEqual(action, {'type': 'basic_attack', 'targetId': 1000000032})
        self.assertEqual(delay, 500)

    def test_rejects_privileged_or_invalid_actions(self):
        for change in [dict(type='add_exp'), dict(type='use_skill', skillId=999999),
                       dict(type='move_to', x=999999, y=334), dict(waitMs=999999),
                       dict(targetId=None), dict(targetId=True)]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                runner.translate_action(self.action(**change))

    def test_wait_cannot_mutate_game(self):
        action, delay = runner.translate_action(self.action(type='wait'))
        self.assertIsNone(action)
        self.assertEqual(delay, 500)


if __name__ == '__main__':
    unittest.main()
