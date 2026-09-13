"""Build a single YCB object thrown toward the stereo rig on a gravity-driven arc."""
import argparse
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector, Euler, Quaternion

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_scene import material, cube, camera, aim
from download_ycb import MODELS

ROOT = Path(__file__).resolve().parents[1]


def frame_side_view(scene, side, target, margin=0.10):
    """Look perpendicular to the flight plane and fit the complete flight and lab."""
    v = Vector(scene['launch_velocity_m_s'])
    normal = Vector((-v.y, v.x, 0)).normalized()
    side.rotation_euler = (-normal).to_track_quat('-Z', 'Y').to_euler()
    rotation = side.rotation_euler.to_matrix()
    right, up = rotation @ Vector((1, 0, 0)), rotation @ Vector((0, 1, 0))
    points = []
    original_frame = scene.frame_current
    scene.frame_set(scene.frame_start)
    for obj in scene.objects:
        if obj.type == 'MESH' and obj != target:
            points.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    for frame in range(scene.frame_start, scene.frame_end+1):
        scene.frame_set(frame)
        points.extend(target.matrix_world @ Vector(corner) for corner in target.bound_box)
    axes = (right, up, normal)
    midpoint = [(min(p.dot(axis) for p in points)+max(p.dot(axis) for p in points))/2 for axis in axes]
    focus = sum((axis*value for axis, value in zip(axes, midpoint)), Vector())
    tan_h = side.data.sensor_width / (2*side.data.lens)
    tan_v = tan_h * scene.render.resolution_y / scene.render.resolution_x
    usable = 1-2*margin
    distance = max((p-focus).dot(normal) + max(abs((p-focus).dot(right))/(tan_h*usable),
                  abs((p-focus).dot(up))/(tan_v*usable)) for p in points) + 0.05
    side.location = focus + normal*distance
    side['view_purpose'] = 'Perpendicular side view of the entire ballistic flight, with environment in frame'
    side['frame_margin_fraction'] = margin
    scene.frame_set(original_frame)


def pose(t, duration, speed, start=None, velocity=None, spin_deg_s=None, spin_axis=None):
    # One throw from the rear of the table toward the stereo cameras, in meters.
    # Horizontal velocity is constant; vertical acceleration is -9.81 m/s^2.
    velocity = Vector(velocity if velocity is not None else (-0.6*speed/duration, -2.3*speed/duration, 0.5*9.81*duration))
    center = Vector(start if start is not None else (0.42, 1.05, 0.65)) + velocity*t + Vector((0, 0, -0.5*9.81*t*t))
    axis = Vector(spin_axis if spin_axis is not None else (0.85, 0.2, 0.35)).normalized()
    rotation = Quaternion(axis, math.radians(spin_deg_s if spin_deg_s is not None else 260*speed)*t) @ Euler((0.1, -0.3, 0.5)).to_quaternion()
    return center, rotation


def fit_stereo(scene, cameras, target, margin=0.08):
    """Keep the baseline and poses; widen both lenses equally if the flight needs it."""
    max_tan_h = 0.
    aspect = scene.render.resolution_x / scene.render.resolution_y
    for frame in range(scene.frame_start, scene.frame_end+1):
        scene.frame_set(frame)
        bpy.context.view_layer.update()
        for cam in cameras:
            inverse = cam.matrix_world.inverted()
            for corner in target.bound_box:
                p = inverse @ target.matrix_world @ Vector(corner)
                if p.z >= -0.01:
                    raise ValueError('Throw crosses/approaches the stereo camera plane')
                max_tan_h = max(max_tan_h, abs(p.x/-p.z), aspect*abs(p.y/-p.z))
    lens = min(cameras[0].data.lens, cameras[0].data.sensor_width*(1-2*margin)/(2*max_tan_h))
    for cam in cameras:
        cam.data.lens = lens
    scene.frame_set(scene.frame_start)


def build(args):
    for name in [args.moving_object]:
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
    scene.render.resolution_x, scene.render.resolution_y = 3840, 2160
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
    label.data.body = 'YCB / 6D THROW LAB'
    label.data.size = 0.085
    label.data.extrude = 0.001
    label.data.materials.append(steel)
    duration = (args.frames-1)/args.fps
    for name in [args.moving_object]:
        index = MODELS.index(name)
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
        obj['is_moving'] = True
        for frame in range(0, args.frames+2):
            center, rotation = pose((frame-1)/args.fps, duration, args.speed,
                                    args.launch_position, args.launch_velocity, args.spin_deg_s, args.spin_axis)
            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = rotation
            obj.location = center - rotation.to_matrix() @ center_local
            obj.keyframe_insert(data_path='location', frame=frame)
            obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)
        # Per-frame linear interpolation also gives deterministic exposure subframes.
        action = obj.animation_data.action
        for layer in action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for key in curve.keyframe_points:
                            key.interpolation = 'LINEAR'
    left = camera('Stereo_Left', (-0.12, -2.8, 1.2), (-0.12, -0.1, 0.95), 24)
    right = camera('Stereo_Right', (0.12, -2.8, 1.2), (0.12, -0.1, 0.95), 24)
    right.rotation_euler = left.rotation_euler.copy()
    side = camera('Side_Overview', (5, 0, 1), (0, 0, 1), 32)
    for cam in (left, right):
        body = cube(cam.name+'_Body', (0, 0, 0), (0.085, 0.065, 0.09), floor, 0.006)
        body.parent = cam
        body.location = (0, 0, 0.075)
    cube('Stereo rail', (0, -2.83, 1.10), (0.42, 0.055, 0.04), steel, 0.006)
    cube('Stereo support', (0, -2.83, 0.51), (0.035, 0.035, 1.16), steel, 0.004)
    cube('Stereo base', (0, -2.83, -0.07), (0.35, 0.22, 0.035), floor, 0.01)
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
    scene['motion_type'] = 'single ballistic throw under gravity with prescribed free-flight tumble; no collision simulation'
    scene['trajectory_start_m'] = args.launch_position if args.launch_position is not None else (0.42, 1.05, 0.65)
    scene['launch_velocity_m_s'] = args.launch_velocity if args.launch_velocity is not None else (-0.6*args.speed/duration, -2.3*args.speed/duration, 0.5*9.81*duration)
    scene['spin_deg_s'] = args.spin_deg_s if args.spin_deg_s is not None else 260*args.speed
    scene['spin_axis'] = args.spin_axis
    scene['gravity_m_s2'] = 9.81
    scene['flight_duration_s'] = duration
    scene['stereo_baseline_m'] = 0.24
    target = next(obj for obj in scene.objects if obj.get('ycb_model') == args.moving_object)
    if args.fit_stereo:
        fit_stereo(scene, (left, right), target)
    frame_side_view(scene, side, target)
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
    parser.add_argument('--frames', type=int, default=60)
    parser.add_argument('--fps', type=int, default=60)
    parser.add_argument('--speed', type=float, default=1.0, help='Trajectory speed multiplier')
    parser.add_argument('--moving-object', choices=MODELS, default='006_mustard_bottle')
    parser.add_argument('--launch-position', type=float, nargs=3, metavar=('X', 'Y', 'Z'))
    parser.add_argument('--launch-velocity', type=float, nargs=3, metavar=('VX', 'VY', 'VZ'))
    parser.add_argument('--spin-deg-s', type=float)
    parser.add_argument('--spin-axis', type=float, nargs=3, default=(0.85, 0.2, 0.35))
    parser.add_argument('--fit-stereo', action='store_true')
    args = parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    if args.frames < 2 or args.fps < 1 or args.speed <= 0:
        parser.error('frames >= 2, fps >= 1, speed > 0 required')
    if (not all(math.isfinite(v) for values in (args.launch_position or [], args.launch_velocity or [], args.spin_axis,
                                               [args.spin_deg_s] if args.spin_deg_s is not None else []) for v in values)
            or Vector(args.spin_axis).length < 1e-8
            or (args.launch_velocity is not None and math.hypot(*args.launch_velocity[:2]) < 1e-8)):
        parser.error('Finite motion parameters and nonzero spin/horizontal axes required')
    build(args)
