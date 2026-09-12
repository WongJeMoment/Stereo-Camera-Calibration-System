"""Synthetic observations are explicitly distinct from video detections."""
import numpy as np


def project(points, camera):
    points = np.asarray(points, dtype=float)
    extrinsic = np.asarray(camera["world_to_camera_opencv"], dtype=float)
    pc = points @ extrinsic[:3, :3].T + extrinsic[:3, 3]
    if np.any(pc[:, 2] <= 0):
        raise ValueError("Point behind camera")
    uvw = pc @ np.asarray(camera["K"], dtype=float).T
    return uvw[:, :2] / uvw[:, 2:3]


def triangulate(left_uv, right_uv, left, right):
    if any(np.any(np.asarray(c["distortion_coefficients"]) != 0) for c in (left, right)):
        raise ValueError("V1 requires undistorted observations and zero-distortion cameras")
    if np.shape(left_uv) != np.shape(right_uv) or np.asarray(left_uv).ndim != 2 or np.shape(left_uv)[1] != 2:
        raise ValueError("Stereo observations must have matching Nx2 shapes")
    projections = [np.asarray(c["K"]) @ np.asarray(c["world_to_camera_opencv"])[:3]
                   for c in (left, right)]
    points = []
    for l, r in zip(left_uv, right_uv):
        rows = []
        for uv, p in zip((l, r), projections):
            rows.extend((uv[0] * p[2] - p[0], uv[1] * p[2] - p[1]))
        rows = np.asarray(rows)
        if not np.isfinite(rows).all():
            raise ValueError("Nonfinite image observation")
        _, _, vh = np.linalg.svd(rows)
        if abs(vh[-1, 3]) < 1e-12:
            raise ValueError("Degenerate triangulation")
        points.append(vh[-1, :3] / vh[-1, 3])
    points = np.asarray(points)
    for camera in (left, right):
        project(points, camera)  # Also reject negative depth.
    return points


def simulate_stereo(history_centers, cameras, noise_px, seed):
    if not np.isfinite(noise_px) or noise_px < 0:
        raise ValueError("Pixel noise must be finite and nonnegative")
    rng = np.random.default_rng(seed)
    left, right = [cameras[n] for n in ("Stereo_Left", "Stereo_Right")]
    uv = [project(history_centers, c) for c in (left, right)]
    uv = [x + rng.normal(0., noise_px, x.shape) for x in uv]
    return triangulate(*uv, left, right), uv
