"""Predictors receive history and future TIMES only, never future positions."""
import numpy as np


def forecast(times, positions, future_times, method="gravity", gravity=9.81):
    times = np.asarray(times, dtype=float)
    positions = np.asarray(positions, dtype=float)
    future_times = np.asarray(future_times, dtype=float)
    if times.ndim != 1 or len(times) < 3 or positions.shape != (len(times), 3):
        raise ValueError("Need at least three timestamped XYZ observations")
    if (not all(np.isfinite(x).all() for x in (times, positions, future_times))
            or np.any(np.diff(times) <= 0) or future_times.ndim != 1
            or len(future_times) == 0 or np.any(np.diff(future_times) <= 0)
            or np.any(future_times <= times[-1])):
        raise ValueError("Times must be finite, increasing; forecasts must follow history")
    if not np.isfinite(gravity) or gravity <= 0:
        raise ValueError("Gravity must be positive and finite")
    # Anchor at last observation for better conditioning.
    t = times - times[-1]
    h = future_times - times[-1]
    a = np.array([0., 0., -gravity]) if method == "gravity" else np.zeros(3)
    if method in ("gravity", "constant_velocity"):
        design = np.column_stack([np.ones_like(t), t])
        p, v = np.linalg.lstsq(design, positions - .5 * t[:, None] ** 2 * a, rcond=None)[0]
    elif method == "constant_acceleration":
        design = np.column_stack([np.ones_like(t), t, .5 * t ** 2])
        p, v, a = np.linalg.lstsq(design, positions, rcond=None)[0]
    else:
        raise ValueError(f"Unknown method: {method}")
    prediction = p + h[:, None] * v + .5 * h[:, None] ** 2 * a
    velocity = v + h[:, None] * a
    state = {"anchor_time_s": float(times[-1]), "position_m": p.tolist(),
             "velocity_m_s": v.tolist(), "acceleration_m_s2": a.tolist()}
    return prediction, velocity, state
