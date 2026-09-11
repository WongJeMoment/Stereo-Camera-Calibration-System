"""Numerical regression tests: .venv/bin/python -m unittest discover -s tests -p 'test_multicamera.py'"""
import unittest
import cv2
import numpy as np
from calibration.calibrate import make_board, transform, project, calibrate


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.board = make_board({'squares_x': 7, 'squares_y': 5, 'square_length_m': 0.04,
                               'marker_length_m': 0.028, 'dictionary': 'DICT_4X4_50'})
        points = cls.board.getChessboardCorners()
        rng = np.random.default_rng(12)
        cls.truth = {'A': np.eye(4), 'B': transform([0.01, 0.03, -0.01], [-0.24, 0.005, 0.01]),
                     'C': transform([0.03, 0.2, -0.02], [-0.5, 0.03, 0.08])}
        cls.Ks = {'A': np.array([[900., 0, 480], [0, 910, 320], [0, 0, 1]]),
                  'B': np.array([[780., 0, 400], [0, 790, 300], [0, 0, 1]]),
                  'C': np.array([[1000., 0, 500], [0, 980, 350], [0, 0, 1]])}
        cls.sizes = {'A': (960, 640), 'B': (800, 600), 'C': (1000, 700)}
        cls.records = {c: {} for c in cls.truth}
        dist = np.array([-0.08, 0.02, 0.001, -0.002, 0.])
        for i in range(40):
            pose = transform(rng.uniform(-0.5, 0.5, 3),
                             [rng.uniform(-0.15, 0.1), rng.uniform(-0.15, 0.05), rng.uniform(0.65, 1.4)])
            for c in cls.truth:
                # A and C share no images; B bridges both groups.
                if (c == 'A' and i >= 20) or (c == 'C' and i < 20):
                    continue
                image = project(points, cls.truth[c] @ pose, cls.Ks[c], dist)
                image += rng.normal(0, 0.015, image.shape)
                cls.records[c][f'{i:04d}'] = {'ids': np.arange(len(points)), 'points': image.astype(np.float32)}
        cls.result = calibrate(cls.records, cls.sizes, cls.board, 'A')

    def test_chain_and_transform_direction(self):
        self.assertEqual(len(self.result['initial_pairwise_edges']), 2)
        for c, truth in self.truth.items():
            estimate = np.array(self.result['cameras'][c]['reference_to_camera'])
            self.assertLess(np.linalg.norm(estimate[:3, 3]-truth[:3, 3]), 0.005)
            self.assertLess(np.linalg.norm(cv2.Rodrigues(estimate[:3, :3] @ truth[:3, :3].T)[0]), 0.005)
            K = np.array(self.result['cameras'][c]['K'])
            self.assertLess(abs(K[0, 0]/self.Ks[c][0, 0]-1), 0.01)
        self.assertLess(self.result['joint_optimization']['rms_px'], 0.1)

    def test_disconnected_graph_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Disconnected'):
            calibrate({c: self.records[c] for c in ('A', 'C')}, self.sizes, self.board, 'A')

    def test_insufficient_views_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'training views'):
            calibrate({'A': dict(list(self.records['A'].items())[:2]), 'B': self.records['B']},
                      self.sizes, self.board, 'A')


if __name__ == '__main__':
    unittest.main()
