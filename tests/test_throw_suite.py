"""Validate the experiment plan independently of Blender and video rendering."""
import json
from pathlib import Path
import unittest

import numpy as np

from trajectory_prediction.models import forecast


class ThrowSuiteTests(unittest.TestCase):
    def test_six_models_six_distinct_airborne_throws(self):
        config = json.loads((Path(__file__).resolve().parents[1]/'experiments/throw_suite.json').read_text())
        self.assertEqual(len(set(config['models'])), 6)
        self.assertEqual(len({p['id'] for p in config['presets']}), 6)
        self.assertEqual(len({tuple(p['velocity_m_s']) for p in config['presets']}), 6)
        t = np.arange(config['frames']) / config['fps']
        for preset in config['presets']:
            positions = np.array(preset['start_m']) + t[:, None]*np.array(preset['velocity_m_s'])
            positions[:, 2] -= .5*9.81*t*t
            self.assertGreater(positions[:, 2].min(), .3)
            self.assertGreater(positions[:, 1].min(), -2.)
            count = config['observe_frames']
            predicted, _, _ = forecast(t[:count], positions[:count], t[count:])
            np.testing.assert_allclose(predicted, positions[count:], atol=1e-10)


if __name__ == '__main__':
    unittest.main()
