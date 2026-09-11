"""Run with: blender -b --python blender/create_scene.py -- --output assets/scenes/environment.blend"""
import argparse
import os
import sys
from pathlib import Path
import bpy
from mathutils import Vector


def material(name, color, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1)
    mat.use_nodes = True
    bsdf = next(node for node in mat.node_tree.nodes if node.type == 'BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value = (*color, 1)
    bsdf.inputs['Roughness'].default_value = 0.38
    bsdf.inputs['Metallic'].default_value = metallic
    return mat


def cube(name, location, scale, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if bevel:
        mod = obj.modifiers.new('Soft edges', 'BEVEL')
        mod.width, mod.segments = bevel, 3
        obj.modifiers.new('Weighted normals', 'WEIGHTED_NORMAL')
    return obj


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


def camera(name, location, target, lens):
    data = bpy.data.cameras.new(name)
    data.lens, data.sensor_width, data.sensor_fit = lens, 36, 'HORIZONTAL'
    data.clip_start, data.clip_end = 0.05, 100
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    aim(obj, target)
    return obj


def build(path, baseline):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.unit_settings.system = 'METRIC'
    scene.unit_settings.scale_length = 1
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 960, 640
    scene.render.resolution_percentage = 100
    if scene.world is None:
        scene.world = bpy.data.worlds.new('Simulation World')
    scene.world.use_nodes = True
    background = next(node for node in scene.world.node_tree.nodes if node.type == 'BACKGROUND')
    background.inputs[0].default_value = (0.16, 0.20, 0.28, 1)
    background.inputs[1].default_value = 0.45
    scene.view_settings.view_transform = 'AgX'
    floor = material('Slate platform', (0.075, 0.105, 0.15))
    grid = material('Grid lines', (0.23, 0.32, 0.4))
    dark = material('Camera body', (0.025, 0.035, 0.055), 0.6)
    glass = material('Lens blue', (0.035, 0.23, 0.38), 0.7)
    cube('Experiment platform', (0, 0, -0.15), (9, 7, 0.3), floor, 0.08)
    for x in range(-4, 5):
        cube('Grid X', (x, 0, 0.002), (0.012, 7, 0.003), grid)
    for y in range(-3, 4):
        cube('Grid Y', (0, y, 0.002), (9, 0.012, 0.003), grid)
    colors = [(0.85, 0.13, 0.08), (0.04, 0.40, 0.82), (0.95, 0.55, 0.055),
              (0.06, 0.62, 0.37), (0.60, 0.19, 0.72), (0.03, 0.65, 0.73)]
    mats = [material('Target %d' % i, c) for i, c in enumerate(colors)]
    specs = [('cube', (-1.65, -0.9, 0.5)), ('cylinder', (0.05, -0.3, 0.65)),
             ('sphere', (1.65, -0.8, 0.55)), ('cone', (-1.7, 1.5, 0.8)),
             ('cube', (0, 1.65, 0.65)), ('cylinder', (1.8, 1.5, 0.85))]
    for idx, (kind, loc) in enumerate(specs, 1):
        if kind == 'cube':
            obj = cube('Target', loc, (1, 1, 2 * loc[2]), mats[idx - 1], 0.045)
            obj.rotation_euler.z = 0.18 * idx
        else:
            if kind == 'sphere':
                bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=loc[2], location=loc)
            elif kind == 'cylinder':
                bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.48, depth=2 * loc[2], location=loc)
            else:
                bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.6, radius2=0, depth=2 * loc[2], location=loc)
            obj = bpy.context.object
            obj.data.materials.append(mats[idx - 1])
        obj.name = '%02d_%s' % (idx, kind)
        obj.pass_index = idx
        obj['category'] = kind
        obj['instance_id'] = idx
    left = camera('Stereo_Left', (-baseline / 2, -6, 2.6), (-baseline / 2, 0, 0.8), 28)
    right = camera('Stereo_Right', (baseline / 2, -6, 2.6), (baseline / 2, 0, 0.8), 28)
    right.rotation_euler = left.rotation_euler.copy()
    side = camera('Side_Overview', (11, -12, 10), (0, -0.7, 0), 36)
    # Physical housings are behind the optical centers, so stereo images stay clear.
    for cam in (left, right):
        body = cube(cam.name + '_Housing', (0, 0, 0), (0.16, 0.13, 0.18), dark, 0.015)
        body.parent = cam
        body.location = (0, 0, 0.13)
        lens = cube(cam.name + '_Lens', (0, 0, 0), (0.1, 0.085, 0.015), glass, 0.005)
        lens.parent = cam
        lens.location = (0, 0, 0.03)
    cube('Stereo mounting rail', (0, -6.02, 2.4), (baseline + 0.35, 0.13, 0.08), dark, 0.02)
    cube('Stereo stand', (0, -6.02, 1.18), (0.07, 0.07, 2.36), dark, 0.01)
    cube('Stereo foot', (0, -6.02, -0.035), (0.8, 0.6, 0.07), dark, 0.02)
    for name, loc, power, size in [('Key', (1, -3, 8), 1700, 7), ('Fill', (-5, 1, 5), 1100, 5)]:
        data = bpy.data.lights.new(name, 'AREA')
        data.energy, data.shape, data.size = power, 'DISK', size
        obj = bpy.data.objects.new(name, data)
        scene.collection.objects.link(obj)
        obj.location = loc
        aim(obj, (0, 0, 0))
    scene.camera = side
    scene['stereo_baseline_m'] = baseline
    scene['annotation_note'] = 'Only meshes with instance_id and category are targets; others are background.'
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.spaces.active.region_3d.view_perspective = 'CAMERA'
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(path))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(Path(__file__).resolve().parents[1] / 'assets/scenes/environment.blend'))
    parser.add_argument('--baseline', type=float, default=0.24)
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    if args.baseline <= 0:
        parser.error('--baseline must be positive')
    build(args.output, args.baseline)
