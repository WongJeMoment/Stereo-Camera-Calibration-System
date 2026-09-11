# Stereo-Camera-Calibration-System

三相机 Blender 仿真、基于 ChArUco 的多相机标定，以及物体自动标注。双目相机基线为 24 厘米，第三台相机从侧面观察整体环境。

![侧面标注预览](results/annotation/previews/Side_Overview.png)

## 目录结构

```text
Camera/
├── calibration/              # 相机标定：普通 Python / OpenCV
│   ├── calibrate.py          # 标定板生成、内外参求解和误差报告
│   └── requirements.txt      # 标定依赖
├── blender/                  # Blender 启动与场景操作
│   ├── launch.py             # 统一入口：open / create / capture
│   ├── create_scene.py       # 创建三相机场景（Blender Python）
│   └── render_calibration.py # 渲染同步标定图像（Blender Python）
├── annotation/               # 物体检测框、实例掩码等标注工具
│   └── annotate.py
├── assets/                   # 场景与标定板资源
│   ├── scenes/environment.blend
│   └── boards/               # real：4 cm 格子；simulation：60 cm 格子
├── data/calibration/         # 标定输入：images/ 和独立 ground_truth.json
├── results/                  # 输出，与输入数据分开
│   ├── calibration/          # 标定参数、验证图、report.html
│   └── annotation/           # RGB、COCO/YOLO、掩码和预览
├── tests/                    # 数值测试、标定真值核验、标注核验
└── docs/                     # 分功能使用说明
```

`.venv/` 是本地 Python 依赖环境，不提交 Git。`data/calibration/` 中的原始采集数据和批量角点检测预览也不提交，可通过采集命令重建。场景、标定板、代码和示例结果各自独立存放。

## 快速使用

以下命令在项目根目录执行。`launch.py` 只需要系统 Python；OpenCV 标定使用 `.venv/bin/python`；标注和场景脚本由 Blender 执行。

```bash
# 1. 打开现有 Blender 场景
python3 blender/launch.py open

# 2. 安装标定依赖（已有 .venv 时可跳过）
python3 -m venv .venv
.venv/bin/python -m pip install -r calibration/requirements.txt

# 3. 从现有标定图像估计相机参数
.venv/bin/python calibration/calibrate.py calibrate \
  --images data/calibration/images \
  --board assets/boards/simulation/board.json \
  --reference Stereo_Left \
  --zero-distortion
```

标定完成后，用浏览器打开 [results/calibration/report.html](results/calibration/report.html)。完整参数见 [calibration.json](results/calibration/calibration.json)。真实相机通常应去掉 `--zero-distortion`，并使用实测尺寸的真实标定板配置。

## 重建数据与检查

```bash
# 重新创建场景（会覆盖同名场景）
python3 blender/launch.py create --baseline 0.24

# 重新渲染 30 组同步标定图像（会覆盖同名图像）
python3 blender/launch.py capture --frames 30

# 渲染目标物体图像并自动标注
blender -b assets/scenes/environment.blend --python-exit-code 1 \
  --python annotation/annotate.py

# 数值测试与标定真值检查
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python tests/verify_calibration.py

# 标注数据检查
blender -b assets/scenes/environment.blend --python-exit-code 1 \
  --python tests/verify_dataset.py
```

Blender 不在 PATH 中时：`python3 blender/launch.py --blender /path/to/blender open`。可以在子命令前加 `--dry-run` 只查看将执行的命令。启动器可从其他工作目录调用；显式传入的相对路径以调用者当前目录为准，默认路径定位到本项目。

## 详细说明

- [相机标定、真实采集要求和误差评估](docs/CALIBRATION.md)
- [Blender 场景与物体标注](docs/ANNOTATION.md)
- [目录职责与旧路径对应关系](docs/STRUCTURE.md)
