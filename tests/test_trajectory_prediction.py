"""Numerical checks: python -m unittest discover -s tests -p test_trajectory_prediction.py"""
import unittest

import numpy as np

from trajectory_prediction.models import forecast
from trajectory_prediction.observations import project, triangulate
from trajectory_prediction.run import metrics


class TrajectoryTests(unittest.TestCase):
    def test_unseen_ballistic_future_with_irregular_timestamps(self):
        history = np.array([2., 2.012, 2.035, 2.09, 2.14])
        future = np.array([2.2, 2.4, 2.7])
        def position(t):
            t = (t - 2.)[:, None]
            return [1., 3., 2.] + t * np.array([-.5, -2., 4.]) + .5*t*t*np.array([0., 0., -9.81])
        for method in ("gravity", "constant_acceleration"):
            predicted, _, _ = forecast(history, position(history), future, method)
            np.testing.assert_allclose(predicted, position(future), atol=1e-10)
        cv, _, _ = forecast(history, position(history), future, "constant_velocity")
        self.assertGreater(np.linalg.norm(cv[-1]-position(future)[-1]), 1.)

    def test_stereo_world_coordinate_roundtrip(self):
        k = [[2500., 0., 1920.], [0., 2500., 1080.], [0., 0., 1.]]
        left = {"K": k, "world_to_camera_opencv": np.eye(4), "distortion_coefficients": [0]*5}
        right = {**left, "world_to_camera_opencv": np.eye(4)}
        right["world_to_camera_opencv"][0, 3] = -.24
        truth = np.array([[.2, -.3, 2.], [-.1, .4, 4.]])
        result = triangulate(project(truth, left), project(truth, right), left, right)
        np.testing.assert_allclose(result, truth, atol=1e-10)

    def test_reject_future_overlap_and_duplicate_history(self):
        for times, future in (([0, 1, 1], [2]), ([0, 1, 2], [2])):
            with self.assertRaises(ValueError):
                forecast(times, np.zeros((3, 3)), future)

    def test_metrics_are_euclidean_future_errors(self):
        report = metrics(np.array([[3., 4., 0.], [0., 0., 12.]]), np.zeros((2, 3)), np.array([.1, .2]))
        self.assertEqual(report["ADE_m"], 8.5)
        self.assertEqual(report["FDE_m"], 12.)
        self.assertAlmostEqual(report["RMSE_3D_m"], np.sqrt(84.5))


if __name__ == "__main__":
    unittest.main()
