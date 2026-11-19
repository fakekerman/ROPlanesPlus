#!/usr/bin/env python3
"""
Builds the ROPlanes+ cockpits (models, textures, icons, preview sheet) by running
blender/build_cockpits.py inside Blender in background mode.

    python generate_cockpits.py                 # all cockpits + cockpits_preview_sheet.png
    python generate_cockpits.py f16 su27        # only these
    python generate_cockpits.py --no-preview    # skip the preview renders (icons are still made)

Blender is looked up in $BLENDER, then on PATH, then in the usual install folders.
Run generate_configs.py afterwards (the part .cfg files read cockpit_specs.py too).
"""

import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def find_blender():
    env = os.environ.get('BLENDER')
    if env and os.path.isfile(env):
        return env
    exe = shutil.which('blender')
    if exe:
        return exe
    candidates = sorted(glob.glob(r'C:\Program Files\Blender Foundation\Blender *\blender.exe'), reverse=True)
    candidates += glob.glob(r'C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe')
    candidates += glob.glob('/Applications/Blender.app/Contents/MacOS/Blender')
    for c in candidates:
        if os.path.isfile(c):
            return c
    sys.exit('Blender not found: install it or set the BLENDER environment variable to blender.exe')


def main():
    blender = find_blender()
    script = os.path.join(HERE, 'blender', 'build_cockpits.py')
    cmd = [blender, '-b', '--factory-startup', '--python-exit-code', '1', '--python', script, '--'] + sys.argv[1:]
    print('Running:', ' '.join(f'"{c}"' if ' ' in c else c for c in cmd), flush=True)
    sys.exit(subprocess.call(cmd, cwd=HERE))


if __name__ == '__main__':
    main()
