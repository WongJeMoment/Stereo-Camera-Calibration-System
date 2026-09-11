"""Compare image-derived calibration against separately stored Blender truth."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--result', type=Path, default=root / 'results/calibration/calibration.json')
    parser.add_argument('--truth', type=Path, default=root / 'data/calibration/ground_truth.json')
    args = parser.parse_args()
    result = json.loads(args.result.read_text())
    truth = json.loads(args.truth.read_text())['cameras']
    ref = np.array(truth[result['reference_camera']]['world_to_camera'])
    metrics = {}
    for camera, data in result['cameras'].items():
        expected = np.array(truth[camera]['world_to_camera']) @ np.linalg.inv(ref)
        estimate = np.array(data['reference_to_camera'])
        K, true_K = np.array(data['K']), np.array(truth[camera]['K'])
        focal_error = float(max(abs(K[0, 0]/true_K[0, 0]-1), abs(K[1, 1]/true_K[1, 1]-1)))
        rotation_error = float(np.rad2deg(np.linalg.norm(cv2.Rodrigues(estimate[:3, :3] @ expected[:3, :3].T)[0])))
        center_error = float(np.linalg.norm(np.linalg.inv(estimate)[:3, 3]-np.linalg.inv(expected)[:3, 3]))
        metrics[camera] = {'max_focal_relative_error': focal_error, 'rotation_error_deg': rotation_error,
                           'camera_center_error_m': center_error}
        assert focal_error < 0.01, (camera, 'Focal error exceeds demo tolerance 1%')
        assert rotation_error < 0.5, (camera, 'Rotation error exceeds demo tolerance 0.5 degree')
        assert center_error < 0.06, (camera, 'Camera center error exceeds demo tolerance 6 cm')
        print(f'{camera}: focal error {focal_error*100:.4f}%, rotation {rotation_error:.4f} deg, center {center_error*1000:.3f} mm')
    for pair in result['pairs']:
        if pair['from'] == 'Stereo_Left' and pair['to'] == 'Stereo_Right':
            T = np.array(truth['Stereo_Right']['world_to_camera']) @ np.linalg.inv(np.array(truth['Stereo_Left']['world_to_camera']))
            expected = float(np.linalg.norm(T[:3, 3]))
            error = abs(pair['baseline_m']-expected)
            assert error < 0.002, 'Stereo baseline error exceeds demo tolerance 2 mm'
            metrics['stereo_baseline'] = {'estimated_m': pair['baseline_m'], 'true_m': expected, 'absolute_error_m': error}
            print(f'Stereo baseline: {pair["baseline_m"]:.6f} m; true {expected:.6f} m; error {error*1000:.3f} mm')
    assert result['validation']['per_view'], 'Missing held-out validation'
    assert all(v['rms_px'] < 0.5 for v in result['validation']['per_camera'].values())
    (args.result.parent / 'ground_truth_comparison.json').write_text(json.dumps(metrics, indent=2))
    print('PASS: Blender image-based calibration meets demo regression tolerances')


if __name__ == '__main__':
    main()
