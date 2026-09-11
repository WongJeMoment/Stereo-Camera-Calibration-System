"""Download selected original textured YCB Google 16k scans (standard Python)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODELS = ['003_cracker_box', '004_sugar_box', '005_tomato_soup_can',
          '006_mustard_bottle', '007_tuna_fish_can', '011_banana']
BASE = 'https://ycb-benchmarks.s3.us-east-1.amazonaws.com/data/google/'


def download(name, destination):
    target = destination / name / 'google_16k'
    manifest = destination / name / 'source.json'
    if (target / 'textured.obj').is_file() and manifest.is_file():
        print('Already available:', name, flush=True)
        return
    url = BASE + name + '_google_16k.tgz'
    print('Downloading:', name, flush=True)
    with tempfile.TemporaryDirectory(prefix='ycb_') as temp:
        archive = Path(temp) / 'model.tgz'
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=40) as response, archive.open('wb') as output:
                    shutil.copyfileobj(response, output)
                break
            except (OSError, TimeoutError):
                if attempt == 2:
                    raise
                print(f'Retrying {name}: attempt {attempt+2}/3', flush=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        with tarfile.open(archive, 'r:gz') as tar:
            # Extract only regular model/texture files into a fixed directory.
            for member in tar.getmembers():
                path = Path(member.name)
                if not member.isfile() or path.parent.as_posix() != name + '/google_16k':
                    continue
                if path.suffix.lower() not in ('.obj', '.mtl', '.png', '.jpg', '.jpeg'):
                    continue
                target.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as source, (target / path.name).open('wb') as output:
                    shutil.copyfileobj(source, output)
        if not (target / 'textured.obj').exists():
            raise RuntimeError('Archive did not contain expected mesh: ' + name)
        manifest.write_text(json.dumps({'name': name, 'source_url': url, 'archive_sha256': digest,
            'license': 'CC BY 4.0', 'license_url': 'https://creativecommons.org/licenses/by/4.0/',
            'attribution': 'YCB Object and Model Set, Berk Calli, Arjun Singh, Aaron Walsman, Siddhartha Srinivasa, Pieter Abbeel, Aaron M. Dollar',
            'model_variant': 'Google 16k; original coordinates and metric scale retained'}, indent=2))
    print('Ready:', name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'assets/models/ycb')
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda name: download(name, args.output), MODELS))
