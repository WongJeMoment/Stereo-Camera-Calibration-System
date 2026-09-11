"""Image-based N-camera calibration. Run with normal Python, not Blender.

Each camera has one directory; matching file stems denote synchronized exposures.
ChArUco IDs establish correspondences even when cameras see different board regions.
"""
import argparse
from collections import deque
from itertools import combinations
from html import escape
import json
from pathlib import Path
import sys
from time import perf_counter

import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix

ROOT = Path(__file__).resolve().parents[1]

def make_board(config):
    dictionary = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, config['dictionary']))
    return cv2.aruco.CharucoBoard((config['squares_x'], config['squares_y']),
                                config['square_length_m'], config['marker_length_m'], dictionary)


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def transform(rvec, tvec):
    T = np.eye(4)
    T[:3, :3] = cv2.Rodrigues(np.asarray(rvec, dtype=float))[0]
    T[:3, 3] = np.asarray(tvec).reshape(3)
    return T


def pose_vector(T):
    return np.r_[cv2.Rodrigues(T[:3, :3])[0].ravel(), T[:3, 3]]


def project(points, T, K, dist):
    # Float64 is essential for stable finite-difference Jacobians in joint fitting.
    return cv2.projectPoints(np.asarray(points, dtype=np.float64), cv2.Rodrigues(T[:3, :3])[0], T[:3, 3], K, dist)[0].reshape(-1, 2)


def detect(root, board, output, min_corners):
    detector = cv2.aruco.CharucoDetector(board)
    records, sizes, log = {}, {}, []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'))
        if not files:
            continue
        camera, seen = folder.name, set()
        records[camera] = {}
        preview_dir = output / 'detections' / camera
        preview_dir.mkdir(parents=True, exist_ok=True)
        print(f'检测相机 {camera}：共 {len(files)} 张图像', flush=True)
        for index, path in enumerate(files, 1):
            if path.stem in seen:
                raise ValueError(f'Duplicate frame stem: {camera}/{path.stem}')
            seen.add(path.stem)
            started = perf_counter()
            progress = f'[{camera} {index}/{len(files)}]'
            print(f'{progress} 读取 {path.name} …', flush=True)
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError(f'Cannot read image: {path}')
            size = image.shape[1], image.shape[0]
            if camera in sizes and sizes[camera] != size:
                raise ValueError(f'Image resolution changes within camera {camera}')
            sizes[camera] = size
            read_seconds = perf_counter() - started
            print(f'{progress} 读取完成（{read_seconds:.3f}s），检测角点 …', flush=True)
            corners, ids, _, _ = detector.detectBoard(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
            count = 0 if ids is None else len(ids)
            valid = count >= min_corners and not board.checkCharucoCornersCollinear(ids)
            log.append({'camera': camera, 'frame': path.stem, 'corners': count, 'accepted': bool(valid)})
            if valid:
                records[camera][path.stem] = {'ids': ids.ravel(), 'points': corners.reshape(-1, 2), 'path': str(path)}
                cv2.aruco.drawDetectedCornersCharuco(image, corners, ids)
            cv2.putText(image, f'{camera} / {path.stem}: {count} corners; {"OK" if valid else "REJECTED"}',
                        (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 180, 0) if valid else (0, 0, 255), 2)
            cv2.imwrite(str(preview_dir / (path.stem + '.jpg')), image)
            print(f'{progress} {count} 个角点，{"有效" if valid else "跳过"}，耗时 {perf_counter()-started:.2f}s', flush=True)
        print(f'{camera}: detected {len(records[camera])}/{len(files)} frames', flush=True)
    write_json(output / 'detection_report.json', log)
    if len(records) < 2:
        raise ValueError('At least two camera folders containing images are required')
    return records, sizes


def calibrate(records, sizes, board, reference, min_views=8, min_shared=6,
              holdout_every=5, zero_distortion=False):
    if reference not in records:
        raise ValueError(f'Reference camera not found: {reference}')
    points = board.getChessboardCorners()
    frames = sorted(set().union(*(set(v) for v in records.values())))
    heldout = set(frames[holdout_every-1::holdout_every]) if holdout_every else set()
    training = {c: {f: d for f, d in ds.items() if f not in heldout} for c, ds in records.items()}
    cameras, board_poses = {}, {}
    flags = cv2.CALIB_FIX_K3  # Five-coefficient model with k3 constrained by default.
    if zero_distortion:
        flags |= cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K1 | cv2.CALIB_FIX_K2
    for camera, data in training.items():
        if len(data) < min_views:
            raise ValueError(f'{camera}: only {len(data)} training views; need {min_views}. Capture more diverse poses.')
        names = sorted(data)
        objects = [points[data[f]['ids']].astype(np.float32) for f in names]
        images = [data[f]['points'].astype(np.float32) for f in names]
        print(f'估计 {camera} 内参：{len(names)} 个训练姿态 …', flush=True)
        rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(objects, images, sizes[camera], None, None, flags=flags)
        if not np.isfinite(K).all() or min(K[0, 0], K[1, 1]) <= 0:
            raise ValueError(f'{camera}: invalid intrinsic solution')
        per_view = {}
        board_poses[camera] = {}
        for f, obj, img, r, t in zip(names, objects, images, rvecs, tvecs):
            T = transform(r, t)
            board_poses[camera][f] = T
            per_view[f] = float(np.sqrt(np.mean(np.sum((project(obj, T, K, dist) - img)**2, axis=1))))
        cameras[camera] = {'image_size': list(sizes[camera]), 'K': K.tolist(),
                           'distortion_coefficients': dist.ravel().tolist(),
                           'intrinsic_rms_px': rms, 'training_views': len(names), 'per_view_rms_px': per_view}
        print(f'{camera}: intrinsic RMS {rms:.4f} px', flush=True)
    # Edges need synchronized common corner IDs, not merely similarly named images.
    edges, graph = [], {c: [] for c in cameras}
    for a, b in combinations(cameras, 2):
        object_list, images_a, images_b, shared_frames = [], [], [], []
        for frame in sorted(set(training[a]) & set(training[b])):
            da, db = training[a][frame], training[b][frame]
            ids, ia, ib = np.intersect1d(da['ids'], db['ids'], return_indices=True)
            if len(ids) < min_shared or board.checkCharucoCornersCollinear(ids.astype(np.int32)):
                continue
            object_list.append(points[ids].astype(np.float32))
            images_a.append(da['points'][ia].astype(np.float32))
            images_b.append(db['points'][ib].astype(np.float32))
            shared_frames.append(frame)
        if len(shared_frames) < min_views:
            continue
        ca, cb = cameras[a], cameras[b]
        print(f'估计相对外参 {a} → {b}：{len(shared_frames)} 个共同姿态 …', flush=True)
        result = cv2.stereoCalibrate(object_list, images_a, images_b,
            np.array(ca['K']), np.array(ca['distortion_coefficients']),
            np.array(cb['K']), np.array(cb['distortion_coefficients']), sizes[a],
            flags=cv2.CALIB_FIX_INTRINSIC,
            criteria=(cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 1e-9))
        rms, R, t = result[0], result[5], result[6]
        T = np.eye(4)
        T[:3, :3], T[:3, 3] = R, t.ravel()
        edges.append({'from': a, 'to': b, 'rms_px': rms, 'shared_frames': shared_frames,
                      'pairwise_transform': T.tolist()})
        graph[a].append((b, T, rms))
        graph[b].append((a, np.linalg.inv(T), rms))
    transforms, queue = {reference: np.eye(4)}, deque([reference])
    while queue:
        a = queue.popleft()
        for b, T, _ in sorted(graph[a], key=lambda item: item[2]):
            if b not in transforms:
                transforms[b] = T @ transforms[a]
                queue.append(b)
    missing = set(cameras) - set(transforms)
    if missing:
        raise ValueError(f'Disconnected camera graph: {sorted(missing)}. Need at least {min_views} synchronized training views with shared corners along a path to {reference}.')
    # Jointly refine all camera extrinsics and board poses; intrinsics stay fixed.
    names = [c for c in cameras if c != reference]
    camera_offsets = {c: 6*i for i, c in enumerate(names)}
    train_frames = sorted(set().union(*(set(d) for d in training.values())))
    frame_offsets = {f: 6*(len(names)+i) for i, f in enumerate(train_frames)}
    initial = [pose_vector(transforms[c]) for c in names]
    for f in train_frames:
        source = reference if f in training[reference] else next(c for c in cameras if f in training[c])
        initial.append(pose_vector(np.linalg.inv(transforms[source]) @ board_poses[source][f]))
    x0 = np.concatenate(initial)
    observations = [(c, f, points[d['ids']], d['points']) for c, ds in training.items() for f, d in ds.items()]
    Kds = {c: (np.array(d['K']), np.array(d['distortion_coefficients'])) for c, d in cameras.items()}
    def unpack(x):
        Ts = {reference: np.eye(4)}
        Ts.update({c: transform(x[o:o+3], x[o+3:o+6]) for c, o in camera_offsets.items()})
        Bs = {f: transform(x[o:o+3], x[o+3:o+6]) for f, o in frame_offsets.items()}
        return Ts, Bs
    def residual(x):
        Ts, Bs = unpack(x)
        return np.concatenate([(project(obj, Ts[c] @ Bs[f], *Kds[c])-img).ravel() for c, f, obj, img in observations])
    sparsity = lil_matrix((sum(2*len(o[2]) for o in observations), len(x0)), dtype=int)
    row = 0
    for c, f, obj, _ in observations:
        count, offset = 2*len(obj), frame_offsets[f]
        sparsity[row:row+count, offset:offset+6] = 1
        if c != reference:
            offset = camera_offsets[c]
            sparsity[row:row+count, offset:offset+6] = 1
        row += count
    print(f'联合优化：{len(cameras)} 台相机、{len(train_frames)} 个标定板姿态 …', flush=True)
    fit = least_squares(residual, x0, jac_sparsity=sparsity.tocsr(), loss='soft_l1', f_scale=1,
                        x_scale='jac', max_nfev=300, ftol=1e-7)
    if not np.isfinite(fit.x).all() or not fit.success:
        raise RuntimeError(f'Joint extrinsic optimization did not converge: {fit.message}')
    transforms, _ = unpack(fit.x)
    for c, T in transforms.items():
        cameras[c]['reference_to_camera'] = T.tolist()
        cameras[c]['camera_to_reference'] = np.linalg.inv(T).tolist()
        cameras[c]['camera_center_in_reference_m'] = np.linalg.inv(T)[:3, 3].tolist()
    pairs = []
    for a, b in combinations(cameras, 2):
        T = transforms[b] @ np.linalg.inv(transforms[a])
        pairs.append({'from': a, 'to': b, 'transform': T.tolist(), 'baseline_m': float(np.linalg.norm(T[:3, 3]))})
    return {'reference_camera': reference, 'units': 'meters',
            'convention': 'OpenCV: x right, y down, z forward; P_camera = reference_to_camera @ P_reference',
            'distortion_order': ['k1', 'k2', 'p1', 'p2', 'k3'],
            'distortion_model': 'zero (explicit ideal pinhole assumption)' if zero_distortion else 'Brown-Conrady; k3 fixed to zero',
            'cameras': cameras, 'pairs': pairs, 'initial_pairwise_edges': edges,
            'held_out_frames': sorted(heldout),
            'joint_optimization': {'intrinsics_fixed': True, 'success': bool(fit.success),
                                   'rms_px': float(np.sqrt(np.mean(residual(fit.x)**2)*2)),
                                   'evaluations': fit.nfev, 'message': fit.message}}


def validate(records, board, result, output):
    """Pose from one held-out view, predict corners in the other cameras."""
    points, cameras = board.getChessboardCorners(), result['cameras']
    errors, rows = {}, []
    reference = result['reference_camera']
    for frame in result['held_out_frames']:
        available = [c for c in cameras if frame in records[c]]
        if len(available) < 2:
            continue
        source = reference if reference in available else available[0]
        data, cal = records[source][frame], cameras[source]
        ok, r, t = cv2.solvePnP(points[data['ids']], data['points'], np.array(cal['K']),
                              np.array(cal['distortion_coefficients']))
        if not ok:
            continue
        board_to_ref = np.array(cal['camera_to_reference']) @ transform(r, t)
        for camera in available:
            if camera == source:
                continue
            d, c = records[camera][frame], cameras[camera]
            T = np.array(c['reference_to_camera']) @ board_to_ref
            predicted = project(points[d['ids']], T, np.array(c['K']), np.array(c['distortion_coefficients']))
            e = np.linalg.norm(predicted-d['points'], axis=1)
            errors.setdefault(camera, []).extend(e.tolist())
            rows.append({'frame': frame, 'pose_source': source, 'predicted_camera': camera,
                         'corners': len(e), 'rms_px': float(np.sqrt(np.mean(e**2)))})
            image = cv2.imread(d['path'])
            for measured, fitted in zip(d['points'], predicted):
                p, q = tuple(np.rint(measured).astype(int)), tuple(np.rint(fitted).astype(int))
                cv2.circle(image, p, 4, (0, 220, 0), 1)
                cv2.drawMarker(image, q, (0, 0, 255), cv2.MARKER_CROSS, 8, 1)
                cv2.line(image, p, q, (0, 180, 255), 1)
            cv2.putText(image, f'HELD OUT / {source} -> {camera}: RMS {np.sqrt(np.mean(e**2)):.3f}px',
                        (15, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            folder = output / 'validation' / camera
            folder.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(folder / (frame+'.jpg')), image)
    return {'method': 'Held-out synchronized frames: solve board pose in source camera, project into other cameras without fitting their poses.',
            'per_camera': {c: {'rms_px': float(np.sqrt(np.mean(np.square(e)))),
                               'p95_px': float(np.percentile(e, 95)), 'corners': len(e)} for c, e in errors.items()},
            'per_view': rows}


def report_html(result, output):
    rows = []
    for name, c in result['cameras'].items():
        v = result['validation']['per_camera'].get(name)
        heldout = f'{v["rms_px"]:.4f} px' if v else '作为验证位姿来源或无验证数据'
        K = c['K']
        rows.append(f'<tr><td>{escape(name)}</td><td>{c["training_views"]}</td>'
                    f'<td>{K[0][0]:.3f}, {K[1][1]:.3f}</td><td>{K[0][2]:.3f}, {K[1][2]:.3f}</td>'
                    f'<td>{c["intrinsic_rms_px"]:.4f} px</td><td>{heldout}</td></tr>')
    pairs = ''.join(f'<tr><td>{escape(p["from"])}</td><td>{escape(p["to"])}</td>'
                    f'<td>{p["baseline_m"]:.6f} m</td></tr>' for p in result['pairs'])
    images = []
    for item in result['validation']['per_view']:
        path = output / 'validation' / item['predicted_camera'] / (item['frame'] + '.jpg')
        rel = escape(path.relative_to(output).as_posix(), quote=True)
        images.append(f'<figure><a href="{rel}"><img loading="lazy" src="{rel}"></a>'
                      f'<figcaption>{escape(path.parent.name)} / {escape(path.stem)}</figcaption></figure>')
    warnings = ''.join(f'<li>{escape(w)}</li>' for w in result['warnings'])
    content = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>多相机标定报告</title><style>
body{{font-family:system-ui,sans-serif;max-width:1200px;margin:40px auto;padding:0 24px;background:#f5f7fb;color:#203047}}
table{{border-collapse:collapse;background:white;width:100%;margin:24px 0}}td,th{{padding:14px;text-align:left;border-bottom:1px solid #ddd}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:18px}}figure{{margin:0}}img{{width:100%;border-radius:8px}}figcaption{{padding:8px}}
</style><h1>多相机标定报告</h1>
<p>参考相机：{escape(result['reference_camera'])}。单位：米。联合训练重投影 RMS：{result['joint_optimization']['rms_px']:.4f} 像素。</p>
<p>先独立估计内参，再固定内参、联合优化所有相机外参与标定板位姿。下方验证帧未参与参数求解。</p>
<table><tr><th>相机</th><th>训练帧</th><th>fx, fy</th><th>cx, cy</th><th>内参训练 RMS</th><th>留出帧跨相机 RMS</th></tr>{''.join(rows)}</table>
<table><tr><th>起点相机</th><th>终点相机</th><th>相机中心距离</th></tr>{pairs}</table>
<p><a href="calibration.json">完整参数 JSON</a> · <a href="detection_report.json">角点检测统计</a></p><ul>{warnings}</ul>
<h2>验证图像</h2><p>绿色圆圈是检测角点，红色十字是从另一台相机推算的位置。两者越重合，跨相机预测误差越小。点击图片查看原图。</p>
<p>低像素误差不保证所有位置的三维精度；应结合实际测距要求、标定板覆盖范围与独立长度测量判断。</p>
<div class="gallery">{''.join(images) or '没有可用的留出验证图像。'}</div></html>'''
    (output / 'report.html').write_text(content, encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    generate = sub.add_parser('board', help='Generate ChArUco board image and physical configuration')
    generate.add_argument('--output', type=Path, default=ROOT / 'assets/boards/real')
    generate.add_argument('--square', type=float, default=0.04, help='Measured square edge length in meters')
    generate.add_argument('--squares-x', type=int, default=7)
    generate.add_argument('--squares-y', type=int, default=5)
    run = sub.add_parser('calibrate')
    run.add_argument('--images', type=Path, required=True)
    run.add_argument('--board', type=Path, required=True)
    run.add_argument('--output', type=Path, default=ROOT / 'results/calibration')
    run.add_argument('--reference', default='Stereo_Left')
    run.add_argument('--min-views', type=int, default=8)
    run.add_argument('--min-corners', type=int, default=8)
    run.add_argument('--holdout-every', type=int, default=5, help='Reserve every Nth frame; 0 disables validation')
    run.add_argument('--zero-distortion', action='store_true', help='Only for known ideal pinhole inputs, e.g. Blender')
    args = parser.parse_args()
    if args.command == 'board':
        if args.square <= 0 or min(args.squares_x, args.squares_y) < 3 or args.squares_x*args.squares_y > 90:
            parser.error('Board requires positive square length, at least 3x3 squares, and at most 90 squares')
        args.output.mkdir(parents=True, exist_ok=True)
        config = {'squares_x': args.squares_x, 'squares_y': args.squares_y,
                  'square_length_m': args.square, 'marker_length_m': args.square*0.7,
                  'dictionary': 'DICT_4X4_50'}
        board = make_board(config)
        image = board.generateImage((args.squares_x*240, args.squares_y*240), marginSize=0, borderBits=1)
        cv2.imwrite(str(args.output / 'board.png'), image)
        cv2.imwrite(str(args.output / 'board_print.png'), cv2.copyMakeBorder(image, 120, 120, 120, 120, cv2.BORDER_CONSTANT, value=255))
        write_json(args.output / 'board.json', config)
        print('Board ready:', args.output)
    else:
        if args.min_views < 3 or args.min_corners < 6 or args.holdout_every < 0 or args.holdout_every == 1:
            parser.error('Need min-views >= 3, min-corners >= 6, and holdout-every = 0 or >= 2')
        if not args.images.is_dir():
            parser.error('Image directory does not exist')
        if args.output.resolve() == args.images.resolve() or args.images.resolve() in args.output.resolve().parents:
            parser.error('Output must be outside the input image directory')
        args.output.mkdir(parents=True, exist_ok=True)
        config = json.loads(args.board.read_text())
        board = make_board(config)
        started = perf_counter()
        print(f'开始多相机标定。输入：{args.images.resolve()}', flush=True)
        records, sizes = detect(args.images, board, args.output, args.min_corners)
        result = calibrate(records, sizes, board, args.reference, args.min_views,
                           args.min_corners, args.holdout_every, args.zero_distortion)
        result['board'] = config
        print('验证留出图像并生成报告 …', flush=True)
        result['validation'] = validate(records, board, result, args.output)
        result['warnings'] = []
        if not result['validation']['per_view']:
            result['warnings'].append('No cross-camera held-out validation available; training RMS alone does not establish accuracy.')
        for c, info in result['cameras'].items():
            if info['intrinsic_rms_px'] > 1:
                result['warnings'].append(f'{c}: intrinsic training RMS exceeds 1 pixel; inspect detections and capture diversity.')
        for c, info in result['validation']['per_camera'].items():
            if info['rms_px'] > 1:
                result['warnings'].append(f'{c}: held-out cross-camera RMS exceeds 1 pixel; inspect synchronization, distortion and pose coverage.')
        write_json(args.output / 'calibration.json', result)
        report_html(result, args.output)
        lines = ['Multi-camera calibration', f'Reference: {args.reference}',
                 f'Joint training RMS: {result["joint_optimization"]["rms_px"]:.4f} px']
        for c, data in result['validation']['per_camera'].items():
            lines.append(f'{c}: held-out cross-camera RMS {data["rms_px"]:.4f} px, P95 {data["p95_px"]:.4f} px')
        lines.extend('WARNING: '+w for w in result['warnings'])
        (args.output / 'report.txt').write_text('\n'.join(lines)+'\n')
        print('\n'.join(lines))
        print(f'标定完成，总耗时 {perf_counter()-started:.1f}s。报告：{(args.output / "report.html").resolve()}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\n已收到 Ctrl+C，标定已取消。本次运行未完成，可重新执行命令。', file=sys.stderr, flush=True)
        sys.exit(130)
