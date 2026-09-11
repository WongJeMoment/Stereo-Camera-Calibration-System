"""Render RGB, visible instance masks, COCO/YOLO labels and camera calibration.

blender -b assets/scenes/environment.blend --python annotation/annotate.py -- --output results/annotation
Only objects with positive instance_id and a category custom property are labeled.
"""
import argparse
import json
from pathlib import Path
import struct
import sys
import zlib

import bpy
import numpy as np
from mathutils import Matrix

CAMERAS = ('Stereo_Left', 'Stereo_Right', 'Side_Overview')


def png(path, array):
    """Write lossless uint16 grayscale masks or uint8 RGB without extra packages."""
    h, w = array.shape[:2]
    depth, color = (16, 0) if array.ndim == 2 else (8, 2)
    data = array.astype('>u2' if depth == 16 else 'u1').tobytes()
    stride = w * (2 if depth == 16 else 3)
    raw = b''.join(b'\x00' + data[y * stride:(y + 1) * stride] for y in range(h))
    def chunk(kind, content):
        return struct.pack('>I', len(content)) + kind + content + struct.pack('>I', zlib.crc32(kind + content) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, depth, color, 0, 0, 0))
                          + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def pixels(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    w, h = image.size
    values = np.empty(w * h * image.channels, dtype=np.float32)
    image.pixels.foreach_get(values)
    values = values.reshape(h, w, image.channels)[::-1].copy()
    bpy.data.images.remove(image)
    return values


def rle(binary):
    """COCO uncompressed RLE, column-major, starting with the zero run."""
    flat = binary.flatten(order='F').astype(np.uint8)
    edges = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    counts = np.diff(np.concatenate(([0], edges, [flat.size]))).tolist()
    if flat[0]:
        counts.insert(0, 0)
    return {'size': list(binary.shape), 'counts': counts}


def calibration(scene, cam, w, h):
    # This project uses horizontal sensor fit, square pixels, zero lens shift.
    if cam.data.type != 'PERSP' or cam.data.sensor_fit != 'HORIZONTAL':
        raise ValueError('Calibration requires a perspective camera with HORIZONTAL sensor fit')
    if scene.render.pixel_aspect_x != scene.render.pixel_aspect_y:
        raise ValueError('Calibration requires square pixels')
    if cam.data.shift_x or cam.data.shift_y:
        raise ValueError('Calibration requires zero lens shift')
    fx = cam.data.lens / cam.data.sensor_width * w
    K = [[fx, 0, w / 2], [0, fx, h / 2], [0, 0, 1]]
    # Blender camera: +X right, +Y up, -Z forward. OpenCV: +X right,+Y down,+Z forward.
    conversion = Matrix.Diagonal((1, -1, -1, 1))
    world_to_cv = conversion @ cam.matrix_world.inverted()
    return {'width': w, 'height': h, 'K': K,
            'distortion_coefficients': [0, 0, 0, 0, 0],
            'world_to_camera_opencv': [list(row) for row in world_to_cv],
            'camera_to_world_opencv': [list(row) for row in world_to_cv.inverted()],
            'position_world_m': list(cam.matrix_world.translation)}


def main(args):
    scene = bpy.context.scene
    root = Path(args.output).resolve()
    for folder in ('images', 'masks', 'labels', 'previews', 'index_exr'):
        (root / folder).mkdir(parents=True, exist_ok=True)
    targets = sorted((o for o in scene.objects if 'instance_id' in o and 'category' in o),
                     key=lambda o: int(o['instance_id']))
    if not targets:
        raise ValueError('No annotated targets found. Run create_scene.py first.')
    ids = [int(o['instance_id']) for o in targets]
    if len(set(ids)) != len(ids) or min(ids) < 1 or max(ids) > 32767:
        raise ValueError('instance_id must be unique integers in [1, 32767]')
    for obj in scene.objects:
        obj.pass_index = int(obj.get('instance_id', 0))
    classes = sorted({str(o['category']) for o in targets})
    categories = {name: i + 1 for i, name in enumerate(classes)}
    (root / 'classes.txt').write_text('\n'.join(classes) + '\n')
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = args.width, args.height
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.use_compositing = True
    scene.render.use_border = False
    scene.render.use_file_extension = True
    scene.view_layers[0].use_pass_object_index = True
    scene.use_nodes = True
    tree = scene.node_tree
    tree.nodes.clear()
    layers = tree.nodes.new('CompositorNodeRLayers')
    layers.layer = scene.view_layers[0].name
    composite = tree.nodes.new('CompositorNodeComposite')
    tree.links.new(layers.outputs['Image'], composite.inputs[0])
    index_output = tree.nodes.new('CompositorNodeOutputFile')
    index_output.base_path = str(root / 'index_exr')
    index_output.format.file_format = 'OPEN_EXR'
    index_output.format.color_mode = 'RGB'
    index_output.format.color_depth = '32'
    tree.links.new(layers.outputs['IndexOB'], index_output.inputs[0])
    coco = {'images': [], 'annotations': [], 'categories': [
        {'id': i, 'name': name} for name, i in categories.items()]}
    metadata = {'units': 'meters', 'world_axes': 'Blender right-handed, Z up',
                'pixel_coordinates': 'origin top-left; bounding boxes use half-open pixel edges',
                'mask_background_id': 0, 'cameras': {},
                'objects': [{'instance_id': int(o['instance_id']), 'name': o.name,
                             'category': o['category'], 'dimensions_m': list(o.dimensions),
                             'object_to_world': [list(row) for row in o.matrix_world]} for o in targets]}
    for image_id, name in enumerate(CAMERAS, 1):
        cam = bpy.data.objects.get(name)
        if cam is None or cam.type != 'CAMERA':
            raise ValueError('Missing camera: ' + name)
        scene.camera = cam
        scene.frame_set(1)
        bpy.context.view_layer.update()
        metadata['cameras'][name] = calibration(scene, cam, args.width, args.height)
        scene.render.filepath = str(root / 'images' / (name + '.png'))
        index_output.file_slots[0].path = name + '_'
        bpy.ops.render.render(write_still=True)
        values = pixels(root / 'index_exr' / (name + '_0001.exr'))[:, :, 0]
        mask = np.rint(values).astype(np.uint16)
        if not set(np.unique(mask)).issubset({0, *ids}):
            raise RuntimeError('Unexpected object IDs in rendered mask')
        png(root / 'masks' / (name + '.png'), mask)
        rgb = pixels(root / 'images' / (name + '.png'))[:, :, :3]
        # Byte-backed PNG image pixels are already in the encoded color space.
        preview = np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8)
        coco['images'].append({'id': image_id, 'file_name': 'images/' + name + '.png',
                               'width': args.width, 'height': args.height})
        yolo = []
        for obj in targets:
            binary = mask == int(obj['instance_id'])
            ys, xs = np.nonzero(binary)
            if not len(xs):
                continue
            x, y, xmax, ymax = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
            width, height = xmax - x, ymax - y
            category = categories[str(obj['category'])]
            coco['annotations'].append({'id': len(coco['annotations']) + 1, 'image_id': image_id,
                'category_id': category, 'instance_id': int(obj['instance_id']),
                'bbox': [x, y, width, height], 'area': int(binary.sum()), 'iscrowd': 0,
                'segmentation': rle(binary)})
            yolo.append(f'{category - 1} {(x + width / 2) / args.width:.8f} {(y + height / 2) / args.height:.8f} {width / args.width:.8f} {height / args.height:.8f}')
            preview[y:min(y+2, ymax), x:xmax] = (255, 240, 50)
            preview[max(y,ymax-2):ymax, x:xmax] = (255, 240, 50)
            preview[y:ymax, x:min(x+2, xmax)] = (255, 240, 50)
            preview[y:ymax, max(x,xmax-2):xmax] = (255, 240, 50)
        (root / 'labels' / (name + '.txt')).write_text('\n'.join(yolo) + '\n')
        png(root / 'previews' / (name + '.png'), preview)
    left = Matrix(metadata['cameras']['Stereo_Left']['world_to_camera_opencv'])
    right = Matrix(metadata['cameras']['Stereo_Right']['world_to_camera_opencv'])
    relative = right @ left.inverted()
    metadata['stereo'] = {'left': 'Stereo_Left', 'right': 'Stereo_Right',
        'baseline_m': relative.translation.length,
        'left_to_right_opencv': [list(row) for row in relative],
        'depth_formula': 'Z = fx * baseline_m / (u_left - u_right); Z is optical-axis depth'}
    (root / 'annotations_coco.json').write_text(json.dumps(coco, indent=2))
    (root / 'calibration.json').write_text(json.dumps(metadata, indent=2))
    print('Dataset ready:', root, 'annotations:', len(coco['annotations']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1] / 'results/annotation'))
    parser.add_argument('--width', type=int, default=960)
    parser.add_argument('--height', type=int, default=640)
    parser.add_argument('--samples', type=int, default=24)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if min(args.width, args.height, args.samples) < 1:
        parser.error('width, height and samples must be positive')
    main(args)
