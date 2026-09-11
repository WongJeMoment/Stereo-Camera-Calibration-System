# 多相机标定

`calibration/calibrate.py` 从拍摄图像估计每台相机的内参 K、畸变系数，以及所有相机相对于参考相机的旋转和平移。支持两台或更多相机、各相机不同分辨率、部分角点可见以及通过中间相机连接的布局。

采用 ChArUco 编码棋盘格：角点 ID 确定不同相机观察到的对应位置。算法遵循 [OpenCV ChArUco 标定流程](https://docs.opencv.org/4.x/da/d13/tutorial_aruco_calibration.html)，使用 [`calibrateCamera` 和 `stereoCalibrate`](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html) 初始化，再固定内参、联合优化所有相机外参和每帧标定板位姿，使用 soft-L1 损失减小异常点的影响。这不是鱼眼相机模型。

## 1. 安装与运行已生成的示例

在项目根目录执行。OpenCV 标定脚本使用普通 Python，Blender 渲染脚本使用 Blender Python。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r calibration/requirements.txt

# 本地已生成的 90 张图像可以直接用于标定
.venv/bin/python calibration/calibrate.py calibrate \
  --images data/calibration/images \
  --board assets/boards/simulation/board.json \
  --reference Stereo_Left \
  --output results/calibration \
  --zero-distortion
```

然后用浏览器打开 `results/calibration/report.html`。绿色圆圈是检测角点，红色十字是从另一相机推算出的角点，黄线连接二者。点击缩略图可查看原图。

`--zero-distortion` 仅用于已知无畸变的 Blender 针孔图像。真实相机通常应去掉该参数；默认估计 k1、k2、p1、p2，固定 k3=0。不同镜头可能需要扩展模型。

## 2. 从头生成 Blender 标定图像

```bash
.venv/bin/python calibration/calibrate.py board \
  --output assets/boards/simulation --square 0.6

blender -b assets/scenes/environment.blend --python-exit-code 1 \
  --python blender/render_calibration.py -- \
  --board assets/boards/simulation \
  --output data/calibration --frames 30
```

示例保持原场景的三台相机位置与镜头不动，将标定板移动到 30 个位置和姿态，逐姿态同步渲染三路 1600 × 1066 图像。为满足远处侧面相机的角点分辨率，模拟板使用 60 厘米格子，整体 4.2 × 3 米。标定时临时隐藏原场景目标物体，不会修改或保存原始 `.blend` 文件。

渲染器会写出独立的 `ground_truth.json`。标定求解脚本不读取它，只在求解后用于误差比较。90 张原始图像较大，已加入 `.gitignore`，可以通过以上命令重建。

**注意分辨率**：这里估计的像素内参对应 1600 × 1066，不能直接套用到原目标检测数据集的 960 × 640 图像。相机固定时外参可复用，内参需要按实际缩放与裁剪规则调整，或者用目标分辨率重新采集标定图像。

## 3. 使用真实相机

生成适合打印的板，示例格子边长 4 厘米：

```bash
.venv/bin/python calibration/calibrate.py board \
  --output assets/boards/real --square 0.04
```

打印 `board_print.png`，粘在平整、刚性的板上。PNG 不保证打印机输出的实际尺寸，必须测量印刷后格子边长，并将 `board.json` 中 `square_length_m` 改为实测值，`marker_length_m` 也应对应实际尺寸（本图比例为 0.7）。尺寸单位是米；尺寸错误会直接影响平移和基线的尺度。

固定所有相机，保持焦距、对焦和分辨率不变，移动同一块标定板。建议采集 25–40 组以上，改变位置、距离与倾角，覆盖画面中间和边缘。仅重复拍摄正对相机、同一位置的板容易产生退化解。真实拍摄需要你自行同步采集；本项目没有实现硬件触发或摄像头采集驱动。

目录按相机分组，文件名主干相同表示同一时刻、同一标定板姿态：

```text
my_capture/
  cam0/
    0000.png
    0001.png
    ...
  cam1/
    0000.png
    0001.png
    ...
  cam2/
    0000.png
    0001.png
    ...
```

不能把不同时间或不同板姿态的图片仅靠改名配对。相机间必须有足够的共同观测：默认每条相机连接边至少需要 8 个训练姿态，每个姿态至少 8 个共同、非共线角点。所有相机不必两两重叠，但必须能沿连接路径到达参考相机。例如 cam0 与 cam1 共视、cam1 与 cam2 共视也可以。

```bash
.venv/bin/python calibration/calibrate.py calibrate \
  --images my_capture \
  --board assets/boards/real/board.json \
  --reference cam0 \
  --output results/real_calibration
```

## 4. 查看质量和使用参数

| 输出 | 用途 |
| --- | --- |
| `report.html` | 本地浏览器查看误差表、相机距离和验证图 |
| `calibration.json` | 每台相机 K、畸变、外参；任意相机对的变换和基线 |
| `detections/相机名/` | 所有输入图的角点 ID 预览，检测失败的图会注明 REJECTED |
| `detection_report.json` | 每张图角点数量及是否用于后续标定 |
| `validation/相机名/` | 留出图像的跨相机预测与实测角点叠加 |
| `report.txt` | 纯文本误差摘要和提示 |

默认每 5 个排序后的帧编号保留 1 个用于验证，留出帧不会参与内外参求解。验证时只用来源相机估计该帧标定板姿态，再通过外参预测其他相机的角点，不重新拟合目标相机的板姿态。参考相机优先作为来源，因此它通常没有“被预测相机”的验证统计。`--holdout-every 0` 可以关闭留出，但这时训练误差不能当作独立验证。

训练 RMS 和留出 RMS 越低通常越好，但阈值与分辨率、测量任务有关。程序在 RMS 超过 1 像素时给出检查提示，这不是通用验收标准。即使 RMS 很低，也应检查实际测距误差、角点在画面中的覆盖和采集姿态多样性。当前版本不自动剔除整帧异常观测，也不保证仅凭帧数判断可观测性。

变换使用 OpenCV 相机坐标系：X 向右、Y 向下、Z 向前。`reference_to_camera` 满足 `P_camera = T @ P_reference`，参考相机本身是单位矩阵。相机位置应读取 `camera_center_in_reference_m` 或逆变换的平移列，不能把正向变换中的 t 直接当成相机位置。

```python
import json
import numpy as np

with open('results/calibration/calibration.json') as f:
    result = json.load(f)
cam = result['cameras']['Stereo_Right']
K = np.array(cam['K'])
dist = np.array(cam['distortion_coefficients'])  # k1, k2, p1, p2, k3
T = np.array(cam['reference_to_camera'])
point_in_camera = T @ np.array([0.0, 0.0, 3.0, 1.0])
```

## 5. 验证代码

```bash
# 带噪声和非零畸变的三相机数值测试：不同分辨率、链式连接、断连拒绝、帧数不足拒绝
.venv/bin/python -m unittest discover -s tests -p 'test_multicamera.py'

# 图像求解后，与 Blender 真值进行独立比较
.venv/bin/python tests/verify_calibration.py
```

真值验证的容差针对本项目演示场景，不是工业标定精度承诺。脚本将误差保存到 `ground_truth_comparison.json`。
