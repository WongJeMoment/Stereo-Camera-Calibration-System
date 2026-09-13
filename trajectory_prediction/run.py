"""Run from repository root: .venv/bin/python -m trajectory_prediction.run."""
import argparse
import csv
import html
import json
from pathlib import Path

import numpy as np

from .models import forecast
from .observations import simulate_stereo

ROOT = Path(__file__).resolve().parents[1]
METHODS = ("constant_velocity", "constant_acceleration", "gravity")


def metrics(prediction, truth, horizons):
    error = np.linalg.norm(prediction - truth, axis=1)
    result = {"ADE_m": float(error.mean()), "FDE_m": float(error[-1]),
              "RMSE_3D_m": float(np.sqrt(np.mean(error ** 2))),
              "max_error_m": float(error.max())}
    result["horizon_errors_m"] = {
        f"{h:.2f}s": {"actual_horizon_s": float(horizons[i]), "error_m": float(error[i])}
        for h in (.1, .25, .5, .75)
        if h <= horizons[-1] + 1e-9
        for i in [int(np.argmin(abs(horizons - h))) ]}
    return result


def load_truth(folder):
    calibration = json.loads((folder / "calibration.json").read_text())
    moving = [o for o in calibration["objects"] if o["is_moving"]]
    if len(moving) != 1:
        raise ValueError("V1 expects exactly one moving object")
    target = moving[0]["instance_id"]
    records = [json.loads(line) for line in (folder / "poses/Stereo_Left.jsonl").read_text().splitlines() if line.strip()]
    times = np.array([r["timestamp_s"] for r in records])
    centers = np.array([next(o for o in r["objects"] if o["instance_id"] == target)
                        ["geometry_center_world_m"] for r in records])
    if calibration["units"] != "meters" or not np.isfinite(centers).all() or centers.shape != (len(times), 3):
        raise ValueError("Expected finite world-space geometry centers in meters")
    if not np.isfinite(times).all() or np.any(np.diff(times) <= 0):
        raise ValueError("Invalid ground truth timestamps")
    return calibration, records, times, centers


def write_report(output, times, truth, observed, count, predictions, report):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(13, 9), layout="constrained")
    ax = fig.add_subplot(221, projection="3d")
    ax.plot(*truth.T, color="black", label="Blender truth")
    ax.scatter(*observed.T, s=12, color="royalblue", label="Observed prefix")
    for method, p in predictions.items():
        ax.plot(*p.T, label=method)
    ax.set(xlabel="X (m)", ylabel="Y (m)", zlabel="Z (m)", title="Object geometry center: 3D trajectory")
    ax.legend(fontsize=7)
    ax = fig.add_subplot(222)
    ax.plot(truth[:, 1], truth[:, 2], color="black", label="Truth")
    ax.scatter(observed[:, 1], observed[:, 2], s=12, label="History")
    for method, p in predictions.items():
        ax.plot(p[:, 1], p[:, 2], label=method)
    ax.set(xlabel="Y (m)", ylabel="Z (m)", title="Y-Z projection (throw arc)")
    ax.grid(alpha=.25)
    ax = fig.add_subplot(223)
    for method, p in predictions.items():
        ax.plot(times[count:] - times[count-1], np.linalg.norm(p - truth[count:], axis=1) * 100, label=method)
    ax.set(xlabel="Forecast horizon (s)", ylabel="3D error (cm)", title="Future frames only")
    ax.legend(fontsize=8)
    ax.grid(alpha=.25)
    ax = fig.add_subplot(224)
    ax.plot(times, truth[:, 2], color="black", label="Truth")
    for method, p in predictions.items():
        ax.plot(times[count:], p[:, 2], label=method)
    ax.axvline(times[count-1], color="royalblue", linestyle="--", label="Observation cutoff")
    ax.set(xlabel="Time (s)", ylabel="Z (m)", title="Height: history vs future")
    ax.grid(alpha=.25)
    fig.suptitle(f"{report['observation_mode']} | history={count} frames | seed={report['seed']}")
    fig.savefig(output / "comparison.png", dpi=160)
    fig.savefig(output / "comparison.svg")
    svg = output / "comparison.svg"
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    plt.close(fig)
    rows = "".join(f"<tr><td>{m}</td><td>{v['ADE_m']*100:.3f}</td><td>{v['FDE_m']*100:.3f}</td>"
                   f"<td>{v['RMSE_3D_m']*100:.3f}</td></tr>" for m, v in report["metrics"].items())
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>物体轨迹预测 V1</title><style>body{{max-width:1100px;margin:36px auto;padding:0 20px;font:17px/1.7 sans-serif;background:#f5f7fb;color:#182535}}img{{width:100%}}table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}a{{color:#1654ba}}</style>
<h1>物体轨迹预测 · V1</h1><p><a href="views/gravity/index.html">三视角视频：预测轨迹、XYZ 和误差</a>（先运行 trajectory_prediction.render_views 生成）</p>
<p>观测前 {count} 帧（{times[0]:.3f}–{times[count-1]:.3f} 秒），固定在此时刻预测后 {len(times)-count} 帧。
所有误差仅在未来帧上计算，单位为厘米，数值越低越好。</p>
<p><strong>输入：{html.escape(report['observation_mode'])}。</strong>双目仿真模式使用真实中心投影后添加 {report['noise_px']} 像素高斯噪声，再三角化；没有运行视频检测器。
真值为 Blender 几何中心，当前场景为理想重力抛物线。单条轨迹结果不能证明真实视频或多场景泛化精度。</p>
<table><tr><th>方法</th><th>平均距离 ADE (cm)</th><th>终点 FDE (cm)</th><th>3D RMSE (cm)</th></tr>{rows}</table>
<img src="comparison.png" alt="三维轨迹、抛物线、未来误差与高度对比">
<p>黑线为真值；蓝色散点为历史观测；gravity 为已知重力预测，constant_velocity 为匀速对照，constant_acceleration 为自由估计加速度对照。</p>
<p><a href="comparison.svg">下载矢量图</a> · <a href="predictions.csv">逐帧预测及真值</a> · <a href="observations.csv">历史观测</a> · <a href="metrics.json">完整指标及初始状态</a></p>
</html>'''
    (output / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, default=ROOT / "results/motion")
    parser.add_argument("--output", type=Path, default=ROOT / "results/trajectory_prediction")
    parser.add_argument("--observe-frames", type=int, default=15)
    parser.add_argument("--mode", choices=("synthetic_stereo", "oracle_history"), default="synthetic_stereo")
    parser.add_argument("--noise-px", type=float, default=1.)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--gravity", type=float, default=9.81)
    args = parser.parse_args()
    calibration, records, times, truth = load_truth(args.motion)
    count = args.observe_frames
    if not 3 <= count < len(times):
        parser.error("observe-frames must be >=3 and leave at least one future frame")
    if args.mode == "synthetic_stereo":
        observed, uv = simulate_stereo(truth[:count], calibration["cameras"], args.noise_px, args.seed)
    else:
        observed, uv = truth[:count].copy(), None
    predictions, velocities, states = {}, {}, {}
    for method in METHODS:
        predictions[method], velocities[method], states[method] = forecast(
            times[:count], observed, times[count:], method, args.gravity)
    # Future truth is used below only for scoring/export; never in forecast().
    report = {
        "version": 1, "observation_mode": args.mode, "seed": args.seed,
        "noise_px": args.noise_px if uv is not None else 0.,
        "gravity_prior_m_s2": args.gravity,
        "observed_frames": count, "predicted_frames": len(times)-count,
        "cutoff_time_s": float(times[count-1]), "forecast_duration_s": float(times[-1]-times[count-1]),
        "target": next(o['model'] for o in calibration['objects'] if o['is_moving']) + " geometry_center_world_m",
        "coordinate_system": "Blender world, meters, Z up",
        "source_motion": str(args.motion.resolve()),
        "protocol": "Single fixed prefix; no future position or launch-velocity input; ideal ballistic simulation",
        "observation_ADE_m": float(np.linalg.norm(observed-truth[:count], axis=1).mean()),
        "metrics": {m: metrics(p, truth[count:], times[count:]-times[count-1]) for m, p in predictions.items()},
        "estimated_states": states,
    }
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "metrics.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    with (output / "observations.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["frame", "time_s", "x_m", "y_m", "z_m", "left_u_px", "left_v_px", "right_u_px", "right_v_px"])
        for i in range(count):
            writer.writerow([records[i]["frame"], times[i], *observed[i], *(list(uv[0][i])+list(uv[1][i]) if uv is not None else [""]*4)])
    with (output / "predictions.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["method", "frame", "time_s", "horizon_s", "pred_x_m", "pred_y_m", "pred_z_m",
                         "true_x_m", "true_y_m", "true_z_m", "vx_m_s", "vy_m_s", "vz_m_s", "error_m"])
        for method, p in predictions.items():
            for j, i in enumerate(range(count, len(times))):
                writer.writerow([method, records[i]["frame"], times[i], times[i]-times[count-1],
                                 *p[j], *truth[i], *velocities[method][j], np.linalg.norm(p[j]-truth[i])])
    write_report(output, times, truth, observed, count, predictions, report)
    print(json.dumps(report["metrics"], indent=2))
    print(f"Report: {output / 'index.html'}")


if __name__ == "__main__":
    main()
