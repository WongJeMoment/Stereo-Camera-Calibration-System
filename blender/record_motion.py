"""Render three synchronized RGB streams, encode MP4, and save per-frame 6D poses."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

import bpy
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'annotation'))
from annotate import calibration

CAMERAS = ('Stereo_Left', 'Stereo_Right', 'Side_Overview')


def configure_device(scene, requested):
    preferences = bpy.context.preferences.addons['cycles'].preferences
    options = ['OPTIX', 'CUDA'] if requested == 'AUTO' else ([requested] if requested != 'CPU' else [])
    for backend in options:
        try:
            preferences.compute_device_type = backend
            preferences.get_devices()
            selected = [d for d in preferences.devices if d.type == backend]
            if selected:
                for device in preferences.devices:
                    device.use = device.type == backend
                scene.cycles.device = 'GPU'
                print('Render device:', backend, ', '.join(d.name for d in selected), flush=True)
                return backend
        except (TypeError, RuntimeError):
            continue
    if requested not in ('AUTO', 'CPU'):
        raise RuntimeError('Requested GPU backend is unavailable: ' + requested)
    scene.cycles.device = 'CPU'
    print('Render device: CPU', flush=True)
    return 'CPU'


def encode(root, frames, fps, first, selected=CAMERAS):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('ffmpeg is required to encode MP4; rendered PNG and poses are already saved.')
    for name in selected:
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-framerate', str(fps),
               '-start_number', str(first), '-i', str(root / 'frames' / name / '%06d.png'),
               '-frames:v', str(frames), '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
               '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(root / (name+'.mp4'))]
        subprocess.run(cmd, check=True)
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y']
    for name in CAMERAS:
        cmd.extend(['-i', str(root / (name+'.mp4'))])
    filters = []
    for i, name in enumerate(CAMERAS):
        filters.append(f'[{i}:v]scale=640:-2,drawtext=text={name}:x=12:y=12:fontsize=22:fontcolor=white:box=1:boxcolor=black@0.6[v{i}]')
    filters.append('[v0][v1][v2]hstack=inputs=3[v]')
    cmd.extend(['-filter_complex', ';'.join(filters), '-map', '[v]', '-c:v', 'libx264',
                '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(root / 'multiview.mp4')])
    subprocess.run(cmd, check=True)
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(root / 'multiview.mp4'),
                    '-frames:v', '1', '-update', '1', str(root / 'preview.jpg')], check=True)


def main(args):
    scene = bpy.context.scene
    if scene.get('scene_kind') != 'ycb_high_dynamic':
        raise ValueError('Open assets/scenes/ycb_motion.blend, or create it first.')
    start = scene.frame_start if args.start is None else args.start
    end = scene.frame_end if args.end is None else args.end
    if not scene.frame_start <= start <= end <= scene.frame_end:
        raise ValueError('Requested recording range is outside the scene animation')
    if args.width % 2 or args.height % 2 or min(args.width, args.height, args.samples) < 1:
        raise ValueError('Video dimensions must be positive even numbers; samples must be positive')
    root = args.output.resolve()
    selected = tuple(args.cameras)
    if len(set(selected)) != len(selected):
        raise ValueError('Each selected camera must be listed only once')
    root.mkdir(parents=True, exist_ok=True)
    (root / 'poses').mkdir(exist_ok=True)
    fps = scene.render.fps / scene.render.fps_base
    targets = sorted((o for o in scene.objects if 'ycb_model' in o), key=lambda o: o['instance_id'])
    scene.render.engine = 'BLENDER_EEVEE_NEXT' if args.engine == 'EEVEE' else 'CYCLES'
    if args.engine == 'EEVEE':
        scene.eevee.taa_render_samples = args.samples
        device = 'EEVEE GPU'
        print('Render engine: EEVEE GPU', flush=True)
    else:
        device = configure_device(scene, args.device)
        scene.cycles.samples = args.samples
        scene.cycles.use_denoising = True
        if device == 'OPTIX':
            scene.cycles.denoiser = 'OPTIX'
            scene.cycles.denoising_use_gpu = True
    scene.render.resolution_x, scene.render.resolution_y = args.width, args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.use_border = False
    scene.render.use_compositing = False
    scene.render.use_persistent_data = True
    scene.render.use_motion_blur = args.shutter > 0
    scene.render.motion_blur_shutter = args.shutter
    scene.render.motion_blur_position = 'CENTER'
    scene.render.film_transparent = False
    scene.frame_set(start)
    bpy.context.view_layer.update()
    meta = {'units': 'meters', 'pose_convention': 'P_opencv_camera = object_to_camera @ P_original_YCB_google16k_OBJ',
            'note': 'Model frames are original Google scans, not automatically YCB-V/BOP-compatible frames.',
            'render_engine': args.engine, 'render_device': device, 'fps': fps, 'first_frame': start, 'last_frame': end, 'frames_per_camera': end-start+1,
            'duration_s': (end-start+1)/fps, 'exposure_s': args.shutter/fps,
            'pose_timestamp': 'Frame center; RGB integrates exposure around this time when motion blur is enabled.',
            'motion_type': scene['motion_type'], 'speed_multiplier': scene['motion_speed_multiplier'],
            'moving_models': [o['ycb_model'] for o in targets if o.get('is_moving', True)],
            'cameras': {}, 'objects': []}
    if 'gravity_m_s2' in scene:
        meta['trajectory'] = {'start_m': list(scene['trajectory_start_m']),
            'launch_velocity_m_s': list(scene['launch_velocity_m_s']),
            'gravity_m_s2': scene['gravity_m_s2'], 'flight_duration_s': scene['flight_duration_s']}
    for name in CAMERAS:
        (root / 'frames' / name).mkdir(parents=True, exist_ok=True)
        meta['cameras'][name] = calibration(scene, bpy.data.objects[name], args.width, args.height)
    for obj in targets:
        meta['objects'].append({'instance_id': int(obj['instance_id']), 'model': obj['ycb_model'],
            'is_moving': bool(obj.get('is_moving', True)),
            'model_center_local_m': list(obj['model_center_local']),
            'bounds_local_m': [list(v) for v in obj.bound_box],
            'model_file': f'assets/models/ycb/{obj["ycb_model"]}/google_16k/textured.obj'})
    calibration_path = root / 'calibration.json'
    if set(selected) != set(CAMERAS):
        # Reusing other cameras is safe only if their settings and every object pose match.
        if not calibration_path.is_file():
            raise ValueError('Partial recording requires an existing complete recording in --output')
        previous = json.loads(calibration_path.read_text())
        for key in ('fps', 'first_frame', 'last_frame', 'exposure_s', 'objects', 'trajectory', 'render_engine'):
            if previous.get(key) != meta.get(key):
                raise ValueError('Cannot reuse camera videos: recording setting changed: '+key)
        unchanged = [name for name in CAMERAS if name not in selected]
        for name in unchanged:
            if previous['cameras'][name] != meta['cameras'][name] or not (root / (name+'.mp4')).is_file():
                raise ValueError('Cannot reuse video for changed or missing camera: '+name)
            records = [json.loads(line) for line in (root / 'poses' / (name+'.jsonl')).read_text().splitlines()]
            if len(records) != end-start+1:
                raise ValueError('Incomplete pose records for '+name)
            for frame, record in zip(range(start, end+1), records):
                scene.frame_set(frame)
                if record['frame'] != frame or abs(record['timestamp_s']-(frame-1)/fps) > 1e-9:
                    raise ValueError('Frame synchronization mismatch: '+name)
                stored = {item['model']: item['object_to_world'] for item in record['objects']}
                for obj in targets:
                    actual = obj.matrix_world
                    if obj['ycb_model'] not in stored or any(abs(actual[i][j]-stored[obj['ycb_model']][i][j]) > 1e-6 for i in range(4) for j in range(4)):
                        raise ValueError('Animation changed; record all cameras again')
        scene.frame_set(start)
        print('Reusing unchanged camera videos:', ', '.join(unchanged), flush=True)
    calibration_path.write_text(json.dumps(meta, indent=2))
    streams = {name: (root / 'poses' / (name+'.jsonl')).open('w') for name in selected}
    started = perf_counter()
    try:
        for frame in range(start, end+1):
            scene.frame_set(frame)
            bpy.context.view_layer.update()
            # Snapshot once per time step, shared by all three camera records.
            poses = [(o, o.matrix_world.copy()) for o in targets]
            for name in selected:
                cam = bpy.data.objects[name]
                scene.camera = cam
                extrinsic = Matrix(meta['cameras'][name]['world_to_camera_opencv'])
                filename = f'{frame:06d}.png'
                scene.render.filepath = str(root / 'frames' / name / filename)
                bpy.ops.render.render(write_still=True)
                items = []
                for obj, world in poses:
                    cv = extrinsic @ world
                    items.append({'instance_id': int(obj['instance_id']), 'model': obj['ycb_model'],
                        'object_to_world': [list(row) for row in world],
                        'object_to_camera': [list(row) for row in cv],
                        'R_model_to_camera': [list(row) for row in cv.to_3x3()],
                        't_model_to_camera_m': list(cv.translation),
                        'geometry_center_world_m': list(world @ Vector(obj['model_center_local']))})
                streams[name].write(json.dumps({'frame': frame, 'timestamp_s': (frame-1)/fps,
                    'video_timestamp_s': (frame-start)/fps, 'image': 'frames/'+name+'/'+filename,
                    'camera': name, 'objects': items})+'\n')
                streams[name].flush()
            elapsed = perf_counter()-started
            done = frame-start+1
            print(f'SYNC FRAME {done}/{end-start+1} | t={(frame-1)/fps:.3f}s | elapsed={elapsed:.1f}s | ETA={elapsed/done*(end-frame):.1f}s', flush=True)
    finally:
        for stream in streams.values():
            stream.close()
    encode(root, end-start+1, fps, start, selected)
    # Remove stale frames from longer previous recordings after successful encoding.
    for name in CAMERAS:
        for image_path in (root / 'frames' / name).glob('*.png'):
            if len(image_path.stem) == 6 and image_path.stem.isdigit() and not start <= int(image_path.stem) <= end:
                image_path.unlink()
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>YCB 三相机高速运动</title>
<style>body{font-family:system-ui;max-width:1400px;margin:32px auto;padding:0 20px;background:#101a29;color:#eee}video{width:100%;background:#000}a{color:#83caff}</style>
<h1>单物体抛掷 · 三相机同步录制</h1><p><a href="../trajectory_prediction/views/gravity/index.html">查看三视角预测轨迹、XYZ 坐标及偏差</a>（先运行 trajectory_prediction.render_views）</p><p>场景只保留一个拍摄目标，沿重力抛物线从远处飞向双目相机并翻滚。__VIDEO_INFO__。下面的并排预览经过缩小，从左到右为左目、右目、侧面全景。</p>
<video controls loop poster="preview.jpg" src="multiview.mp4"></video>
<p><button onclick="document.querySelector('video').playbackRate=1">正常速度</button>
<button onclick="document.querySelector('video').playbackRate=0.25">0.25 倍慢放</button></p>
<p><a href="Stereo_Left.mp4">左目视频</a> · <a href="Stereo_Right.mp4">右目视频</a> · <a href="Side_Overview.mp4">侧面视频</a> · <a href="calibration.json">相机参数与模型说明</a></p>
<p>视频已保存为本地 MP4：<a href="multiview.mp4" download>保存并排视频</a> · <a href="Stereo_Left.mp4" download>保存左目视频</a> · <a href="Stereo_Right.mp4" download>保存右目视频</a> · <a href="Side_Overview.mp4" download>保存侧面视频</a>。也可直接从本目录复制这些文件。</p>
<p>poses/ 中每台相机一个 JSONL 文件，包含每帧每个物体的旋转、平移与 4×4 变换。此处为运动场景真值，不是从图像估计的标定结果。</p></html>'''
    html = html.replace('__VIDEO_INFO__', f'三路原始 MP4 均为 {args.width}×{args.height}、{fps:g} FPS，共 {end-start+1} 帧；文件已保存到本机')
    (root / 'index.html').write_text(html, encoding='utf-8')
    print('Three synchronized videos ready:', root, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'results/motion')
    parser.add_argument('--width', type=int, default=3840)
    parser.add_argument('--height', type=int, default=2160)
    parser.add_argument('--samples', type=int, default=16)
    parser.add_argument('--engine', choices=['EEVEE', 'CYCLES'], default='EEVEE')
    parser.add_argument('--device', choices=['AUTO', 'CPU', 'OPTIX', 'CUDA'], default='AUTO')
    parser.add_argument('--shutter', type=float, default=0.25, help='Exposure as fraction of frame interval; 0 disables blur')
    parser.add_argument('--start', type=int)
    parser.add_argument('--end', type=int)
    parser.add_argument('--cameras', nargs='+', choices=CAMERAS, default=list(CAMERAS))
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if not 0 <= args.shutter <= 1:
        parser.error('shutter must be between 0 and 1')
    main(args)
