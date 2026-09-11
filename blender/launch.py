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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', default=os.environ.get('BLENDER_EXECUTABLE', 'blender'),
                        help='Blender executable path, or set BLENDER_EXECUTABLE')
    parser.add_argument('--dry-run', action='store_true', help='Print command without launching')
    sub = parser.add_subparsers(dest='action', required=True)
    view = sub.add_parser('open', help='Open the existing scene in the Blender GUI')
    view.add_argument('--scene', type=Path, default=SCENE)
    create = sub.add_parser('create', help='Build the three-camera environment in background mode')
    create.add_argument('--output', type=Path, default=SCENE)
    create.add_argument('--baseline', type=float, default=0.24)
    capture = sub.add_parser('capture', help='Render synchronized ChArUco images in background mode')
    capture.add_argument('--scene', type=Path, default=SCENE)
    capture.add_argument('--board', type=Path, default=ROOT / 'assets/boards/simulation')
    capture.add_argument('--output', type=Path, default=ROOT / 'data/calibration')
    capture.add_argument('--frames', type=int, default=30)
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
    else:
        if not args.scene.is_file() or not (args.board / 'board.json').is_file() or not (args.board / 'board.png').is_file():
            parser.error('Capture requires an existing scene and a board directory with board.json and board.png')
        if args.frames < 10:
            parser.error('At least 10 poses are required')
        cmd = [executable, '-b', str(args.scene.resolve()), '--python-exit-code', '1',
               '--python', str(ROOT / 'blender/render_calibration.py'), '--',
               '--board', str(args.board.resolve()), '--output', str(args.output.resolve()), '--frames', str(args.frames)]
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
