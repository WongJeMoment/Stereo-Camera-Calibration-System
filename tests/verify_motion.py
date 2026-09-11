"""Validate synchronized videos, metric 6D pose transforms, and fast motion."""
import argparse
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


def main(root):
    meta = json.loads((root / 'calibration.json').read_text())
    names = ['Stereo_Left', 'Stereo_Right', 'Side_Overview']
    frames, count, fps = {}, meta['frames_per_camera'], meta['fps']
    for name in names:
        frames[name] = [json.loads(line) for line in (root / 'poses' / (name+'.jsonl')).read_text().splitlines()]
        assert len(frames[name]) == count, (name, 'Missing pose records')
        p = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_read_frames,avg_frame_rate,width,height', '-of', 'json',
            str(root / (name+'.mp4'))], check=True, capture_output=True, text=True)
        info = json.loads(p.stdout)['streams'][0]
        numerator, denominator = map(int, info['avg_frame_rate'].split('/'))
        assert numerator/denominator == fps and int(info['nb_read_frames']) == count
        assert [info['width'], info['height']] == [meta['cameras'][name]['width'], meta['cameras'][name]['height']]
    bounds = {o['instance_id']: np.array(o['bounds_local_m']) for o in meta['objects']}
    motion, tracks, rotations = {}, {}, {}
    moving_models = meta['moving_models']
    assert len(moving_models) == 1, 'Exactly one moving object is required'
    for index in range(count):
        source = frames[names[0]][index]
        frame = meta['first_frame'] + index
        worlds = {o['instance_id']: np.array(o['object_to_world']) for o in source['objects']}
        for name in names:
            item = frames[name][index]
            assert item['frame'] == frame
            assert abs(item['timestamp_s']-(frame-1)/fps) < 1e-10
            assert abs(item['video_timestamp_s']-index/fps) < 1e-10
            assert (root / item['image']).is_file()
            assert len(item['objects']) == len(bounds)
            E = np.array(meta['cameras'][name]['world_to_camera_opencv'])
            K = np.array(meta['cameras'][name]['K'])
            for obj in item['objects']:
                identity = obj['instance_id']
                world, camera = np.array(obj['object_to_world']), np.array(obj['object_to_camera'])
                assert np.allclose(world, worlds[identity], atol=1e-8)
                assert np.allclose(E @ world, camera, atol=1e-6)
                assert np.allclose(world[:3, :3].T @ world[:3, :3], np.eye(3), atol=1e-6)
                assert abs(np.linalg.det(world[:3, :3])-1) < 1e-6
                corners = np.c_[bounds[identity], np.ones(8)] @ camera.T
                assert np.all(corners[:, 2] > 0)
                pixels = corners[:, :3] @ K.T
                pixels = pixels[:, :2] / pixels[:, 2:3]
                size = np.array([meta['cameras'][name]['width'], meta['cameras'][name]['height']])
                assert np.all(pixels >= 0) and np.all(pixels < size), (name, frame, obj['model'], 'Object cropped')
        for obj in source['objects']:
            name = obj['model']
            tracks.setdefault(name, []).append(obj['geometry_center_world_m'])
            rotations.setdefault(name, []).append(np.array(obj['object_to_world'])[:3, :3])
    for name, positions in tracks.items():
        speed = np.linalg.norm(np.diff(positions, axis=0), axis=1)*fps
        Rs = rotations[name]
        angular_speed = [float(np.linalg.norm(cv2.Rodrigues(b @ a.T)[0])*fps*180/np.pi) for a, b in zip(Rs, Rs[1:])]
        if name in moving_models:
            assert speed.max() > 1.0, (name, 'Default high-dynamic trajectory too slow')
            assert max(angular_speed) > 400, (name, 'Default rotational motion too slow')
        else:
            assert speed.max() < 1e-6, (name, 'Stationary object translated')
            assert max(angular_speed) < 0.01, (name, 'Stationary object rotated')
        motion[name] = {'is_moving': name in moving_models, 'max_center_speed_m_s': float(speed.max()), 'max_angular_speed_deg_s': max(angular_speed)}
    left = np.array(meta['cameras']['Stereo_Left']['world_to_camera_opencv'])
    right = np.array(meta['cameras']['Stereo_Right']['world_to_camera_opencv'])
    relative = right @ np.linalg.inv(left)
    assert np.allclose(relative[:3, :3], np.eye(3), atol=1e-6)
    assert np.allclose(relative[:3, 3], [-0.24, 0, 0], atol=1e-6)
    result = {'passed': True, 'frames_per_camera': count, 'fps': fps, 'moving_models': moving_models, 'objects': motion,
              'checks': ['MP4 frame counts and rate', 'shared timestamps and world poses', 'OpenCV pose transforms',
                         'metric rigid transforms', 'all object 3D bounds inside all cameras', '0.24 m parallel stereo']}
    (root / 'verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'results/motion')
    args = parser.parse_args()
    main(args.output)
