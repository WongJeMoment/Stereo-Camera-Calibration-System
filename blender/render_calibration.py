"""Blender: render a moving ChArUco board with the existing fixed camera rig.

blender -b assets/scenes/environment.blend --python-exit-code 1 --python blender/render_calibration.py
"""
import argparse
import json
from pathlib import Path
import random
import sys

import bpy
from mathutils import Matrix, Vector, Euler


def main(args):
    config = json.loads((args.board / 'board.json').read_text())
    width = config['squares_x'] * config['square_length_m']
    height = config['squares_y'] * config['square_length_m']
    scene = bpy.context.scene
    cameras = [o for o in scene.objects if o.type == 'CAMERA']
    if len(cameras) < 2:
        raise ValueError('Open a scene with at least two fixed cameras')
    args.output.mkdir(parents=True, exist_ok=True)
    # Calibration capture mode: remove clutter only in memory; do not overwrite the environment.
    for obj in scene.objects:
        if obj.type not in ('CAMERA', 'LIGHT'):
            obj.hide_render = True
    image = bpy.data.images.load(str((args.board / 'board.png').resolve()))
    material = bpy.data.materials.new('ChArUco emission texture')
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = image
    tex.interpolation = 'Closest'
    emission = nodes.new('ShaderNodeEmission')
    output = nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(tex.outputs['Color'], emission.inputs['Color'])
    material.node_tree.links.new(emission.outputs[0], output.inputs[0])
    mesh = bpy.data.meshes.new('ChArUco plane')
    mesh.from_pydata([(0, 0, 0), (width, 0, 0), (width, height, 0), (0, height, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new()
    for loop, coord in zip(uv.data, [(0, 1), (1, 1), (1, 0), (0, 0)]):
        loop.uv = coord
    board = bpy.data.objects.new('Calibration_ChArUco', mesh)
    scene.collection.objects.link(board)
    board.data.materials.append(material)
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 8
    scene.cycles.use_denoising = False
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1066
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    scene.render.use_compositing = False
    scene.render.use_border = False
    scene.render.film_transparent = False
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.look = 'None'
    scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
    background = next(node for node in scene.world.node_tree.nodes if node.type == 'BACKGROUND')
    background.inputs[0].default_value = (0.18, 0.18, 0.18, 1)
    background.inputs[1].default_value = 1
    cv_to_blender = Matrix.Diagonal((1, -1, -1, 1))
    truth = {'cameras': {}, 'board': config, 'poses': {}, 'units': 'meters'}
    for camera in cameras:
        if camera.data.sensor_fit != 'HORIZONTAL' or camera.data.shift_x or camera.data.shift_y:
            raise ValueError('Demo requires horizontal sensor fit and zero lens shift')
        fx = camera.data.lens / camera.data.sensor_width * 1600
        truth['cameras'][camera.name] = {'K': [[fx, 0, 800], [0, fx, 533], [0, 0, 1]],
            'world_to_camera': [list(row) for row in cv_to_blender @ camera.matrix_world.inverted()]}
    rng = random.Random(42)
    target = Vector((3, -8, 5))
    for frame in range(args.frames):
        center = Vector((rng.uniform(-1.1, 1.1), rng.uniform(-0.9, 1.3), rng.uniform(1.1, 2.8)))
        base = (center - target).to_track_quat('-Z', 'Y').to_matrix() @ Matrix.Diagonal((1, -1, -1))
        rotation = base @ Euler((rng.uniform(-0.5, 0.5), rng.uniform(-0.55, 0.55), rng.uniform(-0.3, 0.3))).to_matrix()
        T = rotation.to_4x4()
        T.translation = center - rotation @ Vector((width/2, height/2, 0))
        board.matrix_world = T
        stem = f'{frame:04d}'
        truth['poses'][stem] = [list(row) for row in T]
        for camera in cameras:
            folder = args.output / 'images' / camera.name
            folder.mkdir(parents=True, exist_ok=True)
            scene.camera = camera
            scene.render.filepath = str((folder / (stem + '.png')).resolve())
            bpy.ops.render.render(write_still=True)
        print(f'Calibration capture {frame+1}/{args.frames}', flush=True)
    (args.output / 'ground_truth.json').write_text(json.dumps(truth, indent=2))
    print('Calibration images ready:', args.output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]
    parser.add_argument('--board', type=Path, default=root / 'assets/boards/simulation')
    parser.add_argument('--output', type=Path, default=root / 'data/calibration')
    parser.add_argument('--frames', type=int, default=30)
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.frames < 10:
        parser.error('Render at least 10 poses; 30 or more is recommended')
    main(args)
