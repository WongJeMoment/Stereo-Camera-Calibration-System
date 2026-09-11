# 目录职责

代码、资源、输入数据、输出结果分开放置：

| 目录 | 职责与依赖 |
| --- | --- |
| `calibration/` | 从图像估计相机参数；普通 Python、OpenCV、NumPy、SciPy；不依赖 Blender |
| `blender/` | 启动 Blender、构建场景、模拟采集；启动器只用标准库，场景脚本使用 bpy |
| `annotation/` | 从 Blender 场景生成目标物体的检测和分割标注；使用 bpy |
| `assets/boards/` | 标定板图案与对应物理尺寸配置，real 和 simulation 分开 |
| `assets/scenes/` | 可直接打开的 Blender 场景 |
| `data/calibration/` | 按相机和帧号组织的标定输入图像；仿真真值只供测试读取 |
| `results/calibration/` | 图像估计出的参数、角点检测预览、独立验证图与报告 |
| `results/annotation/` | 物体标注数据集；其中 calibration.json 是 Blender 直接导出的真值 |
| `tests/` | 数值回归测试与实际产物核验，不参与正式标定流程 |
| `docs/` | 使用教程和目录说明 |

## 旧路径对应关系

| 旧路径 | 新路径 |
| --- | --- |
| `scripts/calibrate_multicamera.py` | `calibration/calibrate.py` |
| `scripts/create_scene.py` | `blender/create_scene.py` |
| `scripts/render_calibration.py` | `blender/render_calibration.py` |
| `scripts/annotate.py` | `annotation/annotate.py` |
| `scripts/test_multicamera.py` | `tests/test_multicamera.py` |
| `scripts/verify_calibration.py` | `tests/verify_calibration.py` |
| `scripts/verify_dataset.py` | `tests/verify_dataset.py` |
| `requirements-calibration.txt` | `calibration/requirements.txt` |
| `calibration/board_real/` | `assets/boards/real/` |
| `calibration/board_sim/` | `assets/boards/simulation/` |
| `output/environment.blend` | `assets/scenes/environment.blend` |
| `output/calibration_capture/` | `data/calibration/` |
| `output/multicam_calibration/` | `results/calibration/` |
| `output/dataset/` | `results/annotation/` |

旧 `scripts/` 和 `output/` 已移除；请使用新命令。清理了旧运行日志和旧脚本字节码缓存。保留现有虚拟环境、原始标定图像、验证图及 Object Index EXR，因为它们仍用于运行或核验，不属于无用文件。Git 忽略日志、缓存、Blender 备份、本地依赖和可重建的大批量输入数据。

## 数据流

```text
assets/boards + assets/scenes
              │
              ▼ blender/launch.py capture
       data/calibration/images
              │
              ▼ calibration/calibrate.py
       results/calibration

assets/scenes ── annotation/annotate.py ── results/annotation
```

`data/calibration/ground_truth.json` 不传入标定求解器。只有 `tests/verify_calibration.py` 使用它比较估计值与真实值。
