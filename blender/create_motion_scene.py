"""Build a real-scale YCB food-object scene with fast, deterministic 6D motion."""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector, Euler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_scene import material, cube, camera, aim
from download_ycb import MODELS

ROOT = Path(__file__).resolve().parents[1]


def pose(t, index, anchor, speed):
    phase = index * 0.83
    w = 2 * math.pi * (1.6 + 0.1 * index) * speed
    center = Vector(anchor) + Vector((0.14 * math.sin(w*t + phase),
        0.075 * math.cos(1.3*w*t + phase), 0.055 * math.sin(0.8*w*t + 2*phase)))
    rotation = Euler((0.35 * math.sin(w*t + phase), 0.45 * math.cos(0.7*w*t + phase),
                      phase + math.radians(480 + 35*index)*speed*t), 'XYZ')
    return center, rotation


def build(args):
    for name in MODELS:
        if not (args.models / name / 'google_16k/textured.obj').is_file():
            raise ValueError('Missing YCB models. Run python3 blender/download_ycb.py first.')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    scene.frame_start, scene.frame_end = 1, args.frames
    scene.render.fps, scene.render.fps_base = args.fps, 1
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 12
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 960, 640
    scene.render.resolution_percentage = 100
    scene.render.use_motion_blur = True
    scene.render.motion_blur_shutter = 0.25
    scene.render.motion_blur_position = 'CENTER'
    if scene.world is None:
        scene.world = bpy.data.worlds.new('Motion lab world')
    scene.world.use_nodes = True
    background = next(n for n in scene.world.node_tree.nodes if n.type == 'BACKGROUND')
    background.inputs[0].default_value = (0.07, 0.09, 0.14, 1)
    background.inputs[1].default_value = 0.35
    scene.view_settings.view_transform = 'AgX'
    floor = material('Lab blue', (0.027, 0.065, 0.11), 0.2)
    rubber = material('Conveyor graphite', (0.04, 0.055, 0.07))
    yellow = material('Safety yellow', (1, 0.58, 0.045))
    steel = material('Brushed metal', (0.24, 0.3, 0.36), 0.7)
    cube('Lab plinth', (0, -0.15, -0.1), (2.2, 1.95, 0.18), floor, 0.03)
    cube('Tracking table', (0, 0, 0.015), (1.95, 1.35, 0.08), steel, 0.02)
    cube('Tracking surface', (0, 0, 0.06), (1.86, 1.26, 0.015), rubber, 0.012)
    for y in (-0.65, 0.65):
        cube('Safety edge', (0, y, 0.07), (1.9, 0.018, 0.012), yellow, 0.003)
    for x in (-0.3, 0.3):
        cube('Lane divider', (x, 0, 0.07), (0.005, 1.2, 0.002), steel)
    for x in (-0.84, 0.84):
        for y in (-0.54, 0.54):
            cube('Corner marker', (x, y, 0.074), (0.055, 0.055, 0.006), yellow, 0.003)
    bpy.ops.object.text_add(location=(-0.87, -0.94, 0.0))
    label = bpy.context.object
    label.name = 'YCB motion lab label'
    label.data.body = 'YCB / 6D MOTION LAB'
    label.data.size = 0.085
    label.data.extrude = 0.001
    label.data.materials.append(steel)
    for index, name in enumerate(MODELS):
        bpy.ops.object.select_all(action='DESELECT')
        bpy.ops.wm.obj_import(filepath=str(args.models / name / 'google_16k/textured.obj'),
                              forward_axis='Y', up_axis='Z')
        meshes = [o for o in bpy.context.selected_objects if o.type == 'MESH']
        if not meshes:
            raise ValueError('No mesh imported for ' + name)
        bpy.context.view_layer.objects.active = meshes[0]
        if len(meshes) > 1:
            bpy.ops.object.join()
        obj = bpy.context.object
        obj.name = name
        obj['category'], obj['instance_id'] = name, index+1
        obj['ycb_model'] = name
        # These are original Google scan coordinates, not the YCB-V/BOP model frames.
        obj['pose_model_frame'] = 'original YCB Google 16k OBJ coordinates in meters'
        obj.pass_index = index+1
        center_local = sum((Vector(v) for v in obj.bound_box), Vector()) / 8
        obj['model_center_local'] = list(center_local)
        anchor = ((index % 3 - 1)*0.59, (-0.28 if index < 3 else 0.28), 0.29)
        obj['motion_anchor'] = anchor
        obj['is_moving'] = name == args.moving_object
        if not obj['is_moving']:
            # Other objects rest on the table, without animation data.
            rotation = Euler((0, 0, index*0.35), 'XYZ')
            height = max(v[2] for v in obj.bound_box)-min(v[2] for v in obj.bound_box)
            center = Vector((anchor[0], anchor[1], 0.078+height/2))
            obj.rotation_euler = rotation
            obj.location = center-rotation.to_matrix() @ center_local
            continue
        for frame in range(0, args.frames+2):
            center, rotation = pose((frame-1)/args.fps, index, anchor, args.speed)
            obj.rotation_mode = 'XYZ'
            obj.rotation_euler = rotation
            obj.location = center - rotation.to_matrix() @ center_local
            obj.keyframe_insert(data_path='location', frame=frame)
            obj.keyframe_insert(data_path='rotation_euler', frame=frame)
        # Per-frame linear interpolation also gives deterministic exposure subframes.
        action = obj.animation_data.action
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
    left = camera('Stereo_Left', (-0.12, -1.9, 1.05), (-0.12, 0, 0.28), 30)
    right = camera('Stereo_Right', (0.12, -1.9, 1.05), (0.12, 0, 0.28), 30)
    right.rotation_euler = left.rotation_euler.copy()
    side = camera('Side_Overview', (2.65, -2.9, 2.5), (0, -0.35, 0.25), 38)
    for cam in (left, right):
        body = cube(cam.name+'_Body', (0, 0, 0), (0.085, 0.065, 0.09), floor, 0.006)
        body.parent = cam
        body.location = (0, 0, 0.075)
    cube('Stereo rail', (0, -1.93, 0.95), (0.42, 0.055, 0.04), steel, 0.006)
    cube('Stereo support', (0, -1.93, 0.43), (0.035, 0.035, 0.99), steel, 0.004)
    cube('Stereo base', (0, -1.93, -0.07), (0.35, 0.22, 0.035), floor, 0.01)
    for name, loc, energy, size in [('Key', (0.2, -1, 3.3), 220, 2.8), ('Fill', (-2, 0, 2), 110, 2)]:
        data = bpy.data.lights.new(name, 'AREA')
        data.energy, data.shape, data.size = energy, 'DISK', size
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = loc
        aim(obj, (0, 0, 0.2))
    scene.camera = side
    scene['scene_kind'] = 'ycb_high_dynamic'
    scene['motion_speed_multiplier'] = args.speed
    scene['moving_object'] = args.moving_object
    scene['motion_type'] = 'prescribed kinematic 6D trajectories, not gravity/contact dynamics'
    scene['stereo_baseline_m'] = 0.24
    scene.frame_set(1)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
                area.spaces.active.shading.type = 'MATERIAL'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Pack textures so the blend remains portable after moving/downloading it.
    bpy.ops.file.pack_all()
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.resolve()))
    print('Motion scene ready:', args.output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', type=Path, default=ROOT / 'assets/models/ycb')
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/scenes/ycb_motion.blend')
    parser.add_argument('--frames', type=int, default=180)
    parser.add_argument('--fps', type=int, default=60)
    parser.add_argument('--speed', type=float, default=1.0, help='Trajectory speed multiplier')
    parser.add_argument('--moving-object', choices=MODELS, default='006_mustard_bottle')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.frames < 2 or args.fps < 1 or args.speed <= 0:
        parser.error('frames >= 2, fps >= 1, speed > 0 required')
    build(args)
