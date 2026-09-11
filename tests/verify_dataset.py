"""blender -b assets/scenes/environment.blend --python-exit-code 1 --python tests/verify_dataset.py"""
import argparse
import json
from pathlib import Path
import struct
import zlib
import sys
import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

parser = argparse.ArgumentParser()
parser.add_argument('--dataset', type=Path, default=Path(__file__).resolve().parents[1] / 'results/annotation')
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
root = args.dataset.resolve()
coco = json.loads((root / 'annotations_coco.json').read_text())
cal = json.loads((root / 'calibration.json').read_text())
assert len([o for o in bpy.context.scene.objects if o.type == 'CAMERA']) == 3
assert len(coco['images']) == 3 and len(coco['annotations']) == 18
for info in coco['images']:
    name = Path(info['file_name']).stem
    content = (root / 'masks' / (name + '.png')).read_bytes()
    pos, compressed = 8, b''
    while pos < len(content):
        size = struct.unpack('>I', content[pos:pos + 4])[0]
        kind = content[pos + 4:pos + 8]
        if kind == b'IDAT':
            compressed += content[pos + 8:pos + 8 + size]
        pos += size + 12
    rows = np.frombuffer(zlib.decompress(compressed), dtype=np.uint8).reshape(info['height'], 1 + 2 * info['width'])
    assert np.all(rows[:, 0] == 0)
    mask = np.frombuffer(rows[:, 1:].copy().tobytes(), dtype='>u2').reshape(info['height'], info['width'])
    annotations = [a for a in coco['annotations'] if a['image_id'] == info['id']]
    yolo = (root / 'labels' / (name + '.txt')).read_text().splitlines()
    assert len(yolo) == len(annotations)
    for a, line in zip(annotations, yolo):
        binary = mask == a['instance_id']
        counts = a['segmentation']['counts']
        decoded = np.repeat(np.arange(len(counts)) % 2, counts).reshape(binary.shape, order='F')
        assert np.array_equal(decoded, binary)
        ys, xs = np.nonzero(binary)
        box = [int(xs.min()), int(ys.min()), int(xs.max()-xs.min()+1), int(ys.max()-ys.min()+1)]
        assert box == a['bbox'] and int(binary.sum()) == a['area']
        x, y, w, h = box
        fields = list(map(float, line.split()))
        assert fields[0] == a['category_id'] - 1
        assert np.allclose(fields[1:], [(x+w/2)/info['width'], (y+h/2)/info['height'], w/info['width'], h/info['height']], atol=1e-7)
    camera = bpy.data.objects[name]
    data = cal['cameras'][name]
    K, extrinsic = np.array(data['K']), np.array(data['world_to_camera_opencv'])
    for obj in [o for o in bpy.context.scene.objects if 'instance_id' in o]:
        point = np.array([*obj.matrix_world.translation, 1])
        cv = extrinsic @ point
        uv = K @ cv[:3]
        uv = uv[:2] / uv[2]
        ndc = world_to_camera_view(bpy.context.scene, camera, obj.matrix_world.translation)
        assert np.allclose(uv, [ndc.x*info['width'], (1-ndc.y)*info['height']], atol=0.001)
    print(name + ': mask, COCO RLE, bounding boxes, YOLO and calibration OK')
relative = np.array(cal['stereo']['left_to_right_opencv'])
assert np.allclose(relative[:3, :3], np.eye(3), atol=1e-6)
assert np.allclose(relative[:3, 3], [-0.24, 0, 0], atol=1e-6)
side = bpy.data.objects['Side_Overview']
for name in ('Experiment platform', 'Stereo foot', 'Stereo_Left_Housing', 'Stereo_Right_Housing'):
    obj = bpy.data.objects[name]
    for corner in obj.bound_box:
        ndc = world_to_camera_view(bpy.context.scene, side, obj.matrix_world @ Vector(corner))
        assert 0 < ndc.x < 1 and 0 < ndc.y < 1 and ndc.z > 0
print('PASS: parallel stereo, 0.24 m baseline, full overview coverage')
