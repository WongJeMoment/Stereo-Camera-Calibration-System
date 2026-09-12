"""Overlay saved forecasts on all three original videos, preserving 4K/FPS."""
import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .observations import project
from .run import ROOT, METHODS, load_truth

CAMERAS = ("Stereo_Left", "Stereo_Right", "Side_Overview")
ORANGE = (40, 170, 255)  # OpenCV BGR
CYAN = (255, 230, 60)


def load_prediction(folder, method, records, times, truth):
    report = json.loads((folder / "metrics.json").read_text())
    count = report["observed_frames"]
    with (folder / "predictions.csv").open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["method"] == method]
    if not 3 <= count < len(times) or len(rows) != len(times)-count:
        raise ValueError("Prediction length mismatch; rerun trajectory_prediction.run")
    p = np.array([[float(r[f"pred_{a}_m"]) for a in "xyz"] for r in rows])
    gt = np.array([[float(r[f"true_{a}_m"]) for a in "xyz"] for r in rows])
    if (not np.isfinite(p).all()
            or not np.allclose(gt, truth[count:], atol=1e-7, rtol=0)
            or not np.allclose([float(r["time_s"]) for r in rows], times[count:], atol=1e-9, rtol=0)
            or [int(r["frame"]) for r in rows] != [r["frame"] for r in records[count:]]
            or not np.isclose(report["cutoff_time_s"], times[count-1], atol=1e-9, rtol=0)):
        raise ValueError("Stale/invalid prediction for this motion sequence; rerun prediction")
    return count, p, report


def line(image, points, color, dashed=False):
    # Clip segments before integer conversion, including out-of-view forecasts.
    h, w = image.shape[:2]
    for i in range(1, len(points)):
        if dashed and i % 2 == 0:
            continue
        a, b = np.rint(np.clip(points[i-1:i+1], -1e7, 1e7)).astype(int)
        visible, a, b = cv2.clipLine((0, 0, w, h), tuple(a), tuple(b))
        if visible:
            cv2.line(image, a, b, color, max(2, w//600), cv2.LINE_AA)


def overlay(image, i, times, truth, predicted, count, gt_uv, pred_uv, name, method, mode, font):
    h, w = image.shape[:2]
    line(image, gt_uv[:i+1], CYAN)
    if i >= count-1:
        line(image, pred_uv, ORANGE, dashed=True)
    true_pixel = tuple(np.rint(gt_uv[i]).astype(int))
    cv2.circle(image, true_pixel, max(7, w//240), CYAN, max(2, w//900), cv2.LINE_AA)
    pred = predicted[i-count] if i >= count else None
    if pred is not None:
        p = tuple(np.rint(np.clip(pred_uv[i-count], -1e7, 1e7)).astype(int))
        visible, a, b = cv2.clipLine((0, 0, w, h), true_pixel, p)
        if visible:
            cv2.line(image, a, b, (80, 80, 255), max(2, w//700), cv2.LINE_AA)
        if 0 <= p[0] < w and 0 <= p[1] < h:
            cv2.drawMarker(image, p, ORANGE, cv2.MARKER_CROSS, w//65, max(2, w//700))
    xyz = lambda value: "  ".join(f"{a.upper()} {v:+.3f}" for a, v in zip("xyz", value))
    texts = [
        (f"{name} | {method} | {i+1}/{len(times)} 帧 | {times[i]:.3f}s", "white"),
        ("世界坐标 / 米 · 瓶子几何中心", "white"),
        ("真实: " + xyz(truth[i]), (60, 230, 255)),
        ("预测: " + xyz(pred) if pred is not None else "预测: --  正在收集历史观测", (255, 170, 40)),
        ("偏差: " + xyz(pred-truth[i]) if pred is not None else "偏差: --", "white"),
        (f"三维误差: {np.linalg.norm(pred-truth[i])*100:.2f} cm | 提前 {times[i]-times[count-1]:.3f}s"
         if pred is not None else f"观测截止: 第 {count} 帧 / {times[count-1]:.3f}s", "white"),
        ("青色实线/圆: 真值   橙色虚线/十字: 预测", "white"),
        ("输入: " + ("带噪声双目仿真观测" if mode == "synthetic_stereo" else "理想历史真值观测"), "white"),
    ]
    x, y = w//100, h//60
    spacing = int(font.size*1.4)
    panel_w, panel_h = min(w-x, int(w*.46)), spacing*len(texts)+24
    crop = image[y:y+panel_h, x:x+panel_w]
    crop[:] = (crop*.18).astype(np.uint8)
    panel = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(panel)
    for j, (text, color) in enumerate(texts):
        draw.text((14, 8+j*spacing), text, font=font, fill=color)
    image[y:y+panel_h, x:x+panel_w] = cv2.cvtColor(np.asarray(panel), cv2.COLOR_RGB2BGR)
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--motion", type=Path, default=ROOT / "results/motion")
    parser.add_argument("--prediction", type=Path, default=ROOT / "results/trajectory_prediction")
    parser.add_argument("--method", choices=METHODS, default="gravity")
    parser.add_argument("--font", type=Path, default=Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"))
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not args.font.is_file():
        parser.error("ffmpeg and a Chinese font are required; use --font to select a font")
    calibration, records, times, truth = load_truth(args.motion)
    count, predicted, report = load_prediction(args.prediction, args.method, records, times, truth)
    output = args.prediction / "views" / args.method
    output.mkdir(parents=True, exist_ok=True)
    fps = calibration["fps"]
    verification = {}
    for name in CAMERAS:
        camera = calibration["cameras"][name]
        w, h = camera["width"], camera["height"]
        if any(camera["distortion_coefficients"]):
            raise ValueError("This renderer expects the current zero-distortion Blender cameras")
        gt_uv, pred_uv = project(truth, camera), project(predicted, camera)
        cap = cv2.VideoCapture(str(args.motion / f"{name}.mp4"))
        if (not cap.isOpened() or int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) != w
                or int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) != h
                or int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) != len(times)
                or not np.isclose(cap.get(cv2.CAP_PROP_FPS), fps)):
            cap.release()
            raise ValueError(f"Video/pose dimensions, FPS or length mismatch: {name}")
        font = ImageFont.truetype(str(args.font), max(16, w//96))
        path = output / f"{name}.mp4"
        temp = output / f"{name}.tmp.mp4"
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-threads", "4",
               "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temp)]
        with subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
            try:
                for i in range(len(times)):
                    ok, frame = cap.read()
                    if not ok:
                        raise ValueError(f"Cannot decode {name} frame {i+1}")
                    overlay(frame, i, times, truth, predicted, count, gt_uv, pred_uv, name,
                            args.method, report["observation_mode"], font)
                    proc.stdin.write(frame.tobytes())
                    if i == len(times)-1:
                        cv2.imwrite(str(output / f"{name}.jpg"), frame)
                proc.stdin.close()
                if proc.wait() != 0:
                    raise RuntimeError(f"Encoding failed: {name}")
            finally:
                cap.release()
                if not proc.stdin.closed:
                    proc.stdin.close()
        temp.replace(path)
        probe = cv2.VideoCapture(str(path))
        verification[name] = {"width": int(probe.get(cv2.CAP_PROP_FRAME_WIDTH)),
                              "height": int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                              "fps": probe.get(cv2.CAP_PROP_FPS), "frames": int(probe.get(cv2.CAP_PROP_FRAME_COUNT))}
        probe.release()
        if verification[name] != {"width": w, "height": h, "fps": fps, "frames": len(times)}:
            raise RuntimeError(f"Encoded video verification failed: {name}")
        print(f"Saved {path}", flush=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for name in CAMERAS:
        cmd.extend(["-i", str(output / f"{name}.mp4")])
    filters = ";".join(f"[{i}:v]scale=960:540[v{i}]" for i in range(3))
    filters += ";[v0][v1][v2]xstack=inputs=3:layout=0_0|960_0|0_540:fill=black[v]"
    subprocess.run(cmd + ["-filter_complex_threads", "1", "-filter_complex", filters, "-map", "[v]",
                         "-c:v", "libx264", "-threads", "4", "-crf", "18", "-pix_fmt", "yuv420p",
                         "-movflags", "+faststart", str(output / "multiview.mp4")], check=True)
    (output / "verification.json").write_text(json.dumps(verification, indent=2)+"\n")
    links = " · ".join(f'<a href="{n}.mp4">{label} 4K 视频</a>' for n, label in zip(CAMERAS, ("左目", "右目", "侧面")))
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>三视角预测轨迹对比</title>
<style>body{background:#101a29;color:#eee;font:17px/1.7 system-ui;max-width:1400px;margin:30px auto;padding:0 20px}video{width:100%}a{color:#83caff}button,select{font:inherit;margin:6px;padding:5px}input{width:80%}</style>
<h1>三视角 · 预测轨迹与真实轨迹</h1>
<p>左上：左目；右上：右目；左下：侧面。青色实线/圆为已发生的真实轨迹，橙色虚线/十字为预测，红线连接当前预测与真实位置。</p>
<p>每个画面左上角显示世界坐标 XYZ（米）、各轴偏差（预测 − 真实）和三维欧氏误差（厘米）。三个相机展示同一个三维预测，因此同一帧的 XYZ 和三维误差相同。</p>
<p>__INFO__。前 __COUNT__ 帧收集历史观测，预测坐标显示 --；预测从下一帧开始。真实坐标仅用于对比。</p>
<video id="video" controls loop src="multiview.mp4"></video>
<p><button id="previous">上一帧</button><button id="next">下一帧</button><select id="rate"><option value="0.25">0.25 倍慢放</option><option value="0.1">0.1 倍慢放</option><option value="1">正常速度</option></select></p>
<p><input id="frame" aria-label="视频帧" type="range" min="1" max="__FRAMES__" value="1"><span id="label"></span></p>
<p>__LINKS__ · <a href="multiview.mp4" download>下载三视角合成视频</a></p>
<p>合成预览为 1920×1080；查看清晰坐标请打开单独 4K 视频。单个视频也可用本地播放器逐帧查看。</p>
<script>const v=document.getElementById('video'), s=document.getElementById('frame'), label=document.getElementById('label');
const fps=__FPS__, total=__FRAMES__;v.playbackRate=.25;
function seek(n){v.pause();n=Math.max(1,Math.min(total,n));v.currentTime=(n-1+.1)/fps;s.value=n;label.textContent=n+'/'+total;}
s.oninput=()=>seek(Number(s.value));document.getElementById('previous').onclick=()=>seek(Number(s.value)-1);document.getElementById('next').onclick=()=>seek(Number(s.value)+1);
document.getElementById('rate').onchange=e=>v.playbackRate=Number(e.target.value);
v.ontimeupdate=()=>{s.value=Math.min(total,Math.floor(v.currentTime*fps)+1);label.textContent=s.value+'/'+total;};label.textContent='1/'+total;
</script></html>'''
    info = f"方法：{args.method}；输入：{report['observation_mode']}（尚未从视频检测瓶子）"
    for key, value in {"__INFO__": info, "__COUNT__": count, "__FRAMES__": len(times), "__FPS__": fps, "__LINKS__": links}.items():
        page = page.replace(key, str(value))
    (output / "index.html").write_text(page, encoding="utf-8")
    print(f"Open {output / 'index.html'}", flush=True)


if __name__ == "__main__":
    main()
