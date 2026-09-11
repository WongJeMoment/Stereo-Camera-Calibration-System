# YCB mesh attribution

The six textured meshes in `ycb/` are original Google 16k scans from the **YCB Object and Model Set** by Berk Calli, Arjun Singh, Aaron Walsman, Siddhartha Srinivasa, Pieter Abbeel, and Aaron M. Dollar.

- Official download and license statement: https://ycb-benchmarks.s3.amazonaws.com/index.html
- License: Creative Commons Attribution 4.0 International (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/
- Related project: https://www.ycbbenchmarks.com/object-models/
- Download utility: `python3 blender/download_ycb.py` from the repository root.

Objects: `003_cracker_box`, `004_sugar_box`, `005_tomato_soup_can`, `006_mustard_bottle`, `007_tuna_fish_can`, `011_banana`.

Each model has a `source.json` recording its exact source URL and archive SHA-256. Mesh files and texture images are retained without editing. The Blender scene applies rigid animated transforms and packs the six texture images. No model-scale normalization or vertex recentering is applied.

These are **Google scan coordinate frames**, not necessarily the coordinate frames used by the separate YCB-Video or BOP YCB-V model distributions. Exported poses refer to the exact OBJ files included here. A known model-to-model rigid transform is required before comparing poses against a different model distribution.
