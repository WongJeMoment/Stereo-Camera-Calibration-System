"""Launch Blender, build the environment, or render calibration captures.

Uses only Python's standard library. Run `python3 blender/launch.py --help`.
"""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / 'assets/scenes/environment.blend'
MOTION_SCENE = ROOT / 'assets/scenes/ycb_motion.blend'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', default=os.environ.get('BLENDER_EXECUTABLE', 'blender'),
                        help='Blender executable path, or set BLENDER_EXECUTABLE')
    parser.add_argument('--dry-run', action='store_true', help='Print command without launching')
    sub = parser.add_subparsers(dest='action', required=True)
    view = sub.add_parser('open', help='Open the existing scene in the Blender GUI')
    view.add_argument('--scene', type=Path, default=MOTION_SCENE)
    create = sub.add_parser('create', help='Build the three-camera environment in background mode')
    create.add_argument('--output', type=Path, default=SCENE)
    create.add_argument('--baseline', type=float, default=0.24)
    capture = sub.add_parser('capture', help='Render synchronized ChArUco images in background mode')
    capture.add_argument('--scene', type=Path, default=SCENE)
    capture.add_argument('--board', type=Path, default=ROOT / 'assets/boards/simulation')
    capture.add_argument('--output', type=Path, default=ROOT / 'data/calibration')
    capture.add_argument('--frames', type=int, default=30)
    motion = sub.add_parser('create-motion', help='Build the high-dynamic YCB scene (download models first)')
    motion.add_argument('--output', type=Path, default=MOTION_SCENE)
    motion.add_argument('--models', type=Path, default=ROOT / 'assets/models/ycb')
    motion.add_argument('--frames', type=int, default=60)
    motion.add_argument('--fps', type=int, default=60)
    motion.add_argument('--speed', type=float, default=1.0)
    motion.add_argument('--moving-object', default='006_mustard_bottle', help='YCB model name of the only moving object')
    motion.add_argument('--launch-position', type=float, nargs=3)
    motion.add_argument('--launch-velocity', type=float, nargs=3)
    motion.add_argument('--spin-deg-s', type=float)
    motion.add_argument('--spin-axis', type=float, nargs=3)
    motion.add_argument('--fit-stereo', action='store_true')
    record = sub.add_parser('record', help='Record synchronized videos and per-frame 6D object poses')
    record.add_argument('--scene', type=Path, default=MOTION_SCENE)
    record.add_argument('--output', type=Path, default=ROOT / 'results/motion')
    record.add_argument('--width', type=int, default=3840)
    record.add_argument('--height', type=int, default=2160)
    record.add_argument('--samples', type=int, default=16)
    record.add_argument('--engine', choices=['EEVEE', 'CYCLES'], default='EEVEE')
    record.add_argument('--device', choices=['AUTO', 'CPU', 'OPTIX', 'CUDA'], default='AUTO')
    record.add_argument('--shutter', type=float, default=0.25)
    record.add_argument('--cameras', nargs='+', choices=['Stereo_Left', 'Stereo_Right', 'Side_Overview'],
                        default=['Stereo_Left', 'Stereo_Right', 'Side_Overview'])
    args = parser.parse_args()
    executable = shutil.which(args.blender)
    if not executable:
        parser.error('Blender not found. Use --blender /path/to/blender or set BLENDER_EXECUTABLE.')
    # Resolve user-supplied relative paths before changing the subprocess directory.
    if args.action == 'open':
        if not args.scene.is_file():
            parser.error(f'Scene not found: {args.scene}. Run the create command first.')
        cmd = [executable, str(args.scene.resolve())]
    elif args.action == 'create':
        if args.baseline <= 0:
            parser.error('Baseline must be positive')
        cmd = [executable, '-b', '--python-exit-code', '1', '--python', str(ROOT / 'blender/create_scene.py'),
               '--', '--output', str(args.output.resolve()), '--baseline', str(args.baseline)]
    elif args.action == 'capture':
        if not args.scene.is_file() or not (args.board / 'board.json').is_file() or not (args.board / 'board.png').is_file():
            parser.error('Capture requires an existing scene and a board directory with board.json and board.png')
        if args.frames < 10:
            parser.error('At least 10 poses are required')
        cmd = [executable, '-b', str(args.scene.resolve()), '--python-exit-code', '1',
               '--python', str(ROOT / 'blender/render_calibration.py'), '--',
               '--board', str(args.board.resolve()), '--output', str(args.output.resolve()), '--frames', str(args.frames)]
    elif args.action == 'create-motion':
        if args.frames < 2 or args.fps < 1 or args.speed <= 0:
            parser.error('Need frames >= 2, fps >= 1, speed > 0')
        cmd = [executable, '-b', '--python-exit-code', '1', '--python', str(ROOT / 'blender/create_motion_scene.py'),
               '--', '--output', str(args.output.resolve()), '--models', str(args.models.resolve()),
               '--frames', str(args.frames), '--fps', str(args.fps), '--speed', str(args.speed),
               '--moving-object', args.moving_object]
        for flag, value in (('--launch-position', args.launch_position), ('--launch-velocity', args.launch_velocity),
                            ('--spin-deg-s', args.spin_deg_s), ('--spin-axis', args.spin_axis)):
            if value is not None:
                cmd.extend([flag, *map(str, value if isinstance(value, list) else [value])])
        if args.fit_stereo:
            cmd.append('--fit-stereo')
    else:
        if not args.scene.is_file():
            parser.error('Motion scene not found. Run create-motion first.')
        if not shutil.which('ffmpeg'):
            parser.error('Install ffmpeg before recording videos.')
        cmd = [executable, '-b', str(args.scene.resolve()), '--python-exit-code', '1', '--python',
               str(ROOT / 'blender/record_motion.py'), '--', '--output', str(args.output.resolve()),
               '--width', str(args.width), '--height', str(args.height), '--samples', str(args.samples),
               '--shutter', str(args.shutter), '--device', args.device, '--engine', args.engine,
               '--cameras', *args.cameras]
    print(shlex.join(cmd), flush=True)
    if not args.dry_run:
        return subprocess.run(cmd, cwd=ROOT).returncode
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nBlender launch interrupted.', file=sys.stderr)
        sys.exit(130)
