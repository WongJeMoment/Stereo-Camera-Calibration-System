# YCB 物体高速运动与三相机同步录制

新场景 `assets/scenes/ycb_motion.blend` 使用 YCB 原始 Google 16k 带纹理扫描模型，物体包括饼干盒、糖盒、番茄汤罐、芥末瓶、金枪鱼罐和香蕉。模型来源、CC BY 4.0 署名和坐标系说明见 [YCB_SOURCE.md](../assets/models/YCB_SOURCE.md)。

当前仅 `006_mustard_bottle`（芥末瓶）进行运动，其余五个物体静止放在台面上。视频是保存在本机 `results/motion/` 中的 MP4 文件，HTML 只是本地播放页面，不需要上传到网站才能观看或复制。

## 查看

```bash
python3 blender/launch.py open
```

默认打开新的运动场景，按空格播放时间轴，数字小键盘 0 切换相机视图。右上角选择 `Stereo_Left`、`Stereo_Right` 或 `Side_Overview`，将鼠标放在三维视图，按 `Ctrl + 数字小键盘 0` 切换当前相机。Blender 视口可能因为机器负载不能实时达到 60 FPS，导出的视频帧率固定为 60 FPS。

已生成的视频页面：[results/motion/index.html](../results/motion/index.html)，用本地浏览器打开。并排画面从左到右为左目、右目、侧面全景。支持正常速度和 0.25 倍慢放。

## 录制与速度设置

```bash
# 依赖：本机已安装 Blender 和 ffmpeg
python3 blender/launch.py record --samples 16

# 更高分辨率
python3 blender/launch.py record --width 1440 --height 960 --samples 32 --output results/motion_hd

# 重新生成 5 秒动画；速度为默认的 1.5 倍
python3 blender/launch.py create-motion --fps 60 --frames 300 --speed 1.5 --moving-object 006_mustard_bottle
python3 blender/launch.py record --samples 16

# 需要清晰的瞬时姿态训练图像时关闭运动模糊
python3 blender/launch.py record --shutter 0 --output results/motion_sharp
```

`--speed` 改变平移和旋转随时间变化的速度，`--fps` 改变采样帧率，`--frames` 改变动画长度。默认 180 帧、60 FPS，对应 3 秒视频。修改 fps 后需重新生成场景，以便关键帧和时间定义一致。录制范围默认为场景完整时间轴；高级用法可直接运行 `blender/record_motion.py -- --start 1 --end 60` 录制部分帧。

当前芥末瓶轨迹的峰值中心速度约 2.08 m/s，角速度约 721°/s。运动是**指定的三维平移和旋转轨迹**，芥末瓶在台面上方运动，其他物体静止；没有模拟重力、碰撞或真实输送带接触。这里“高动态”指快速运动，并非 HDR 成像。可用 `--moving-object` 指定其他已有 YCB 模型，例如 `011_banana`；任意一次生成都只动画化该物体。

默认快门为帧间隔的 0.25，60 FPS 下曝光约 1/240 秒，中心快门。RGB 包含曝光时段内的运动模糊，位姿标注对应曝光中心时刻；不能把模糊边缘当成瞬时几何边缘。采样数影响渲染噪声，不改变运动速度或视频时间。

录制自动优先使用 OptiX，其次 CUDA，否则使用 CPU。可通过 `--device CPU`、`--device OPTIX` 或 `--device CUDA` 指定。当前机器使用 RTX 5060 Ti 的 OptiX 渲染和降噪。

## 输出和 6D 位姿

| 路径（相对于 results/motion） | 内容 |
| --- | --- |
| `Stereo_Left.mp4`、`Stereo_Right.mp4`、`Side_Overview.mp4` | 三路相同帧率、帧数的视频 |
| `multiview.mp4`、`index.html` | 三路并排播放及浏览器页面 |
| `preview.jpg` | 视频首帧并排预览 |
| `frames/相机名/000001.png` | 无损 RGB 逐帧图像 |
| `poses/相机名.jsonl` | 每行一帧，包含全部物体的 6D 位姿 |
| `calibration.json` | 本场景的相机真值、模型信息、曝光、FPS 与坐标定义 |
| `verification.json` | 视频同步、位姿矩阵、视野范围与运动速度核验结果 |

Blender 实际上顺序渲染各相机，但每次先固定同一时间步的场景状态，三路因此具有相同帧号、时间戳和世界位姿。视频不添加人工时间偏移或丢帧。程序没有模拟真实硬件触发误差、滚动快门或时钟漂移。

`object_to_camera` 是 4×4 刚体变换，满足 `P_camera = object_to_camera @ P_model`。相机使用 OpenCV 坐标：X 向右、Y 向下、Z 向前。平移单位是米，`R_model_to_camera` 是 3×3 旋转矩阵，`t_model_to_camera_m` 是 3 维平移。

模型点 `P_model` 必须来自 `assets/models/ycb/对象名/google_16k/textured.obj`。没有缩放或对顶点重新居中。轨迹绕模型包围盒中心旋转，但导出的矩阵仍将原始 OBJ 坐标变换到相机坐标。实例 ID 1–6 仅为本项目编号，不是 BOP 对象编号。Google 扫描模型与 YCB-V/BOP 发布模型的坐标轴和原点可能不同，不能未经模型坐标转换直接混用位姿。

**相机参数已改变。** 新场景是米制小型台面，双目位置为 `(±0.12, -1.9, 1.05)`、焦距 30 mm；侧面相机位置为 `(2.65, -2.9, 2.5)`、焦距 38 mm。双目基线仍为 0.24 m。应使用 `results/motion/calibration.json`；原 `results/calibration/calibration.json` 是旧静态场景的图像标定结果，不适用于这些新视频。本次导出的是仿真真值，未对新场景重新进行 ChArUco 图像标定。

本次运动录制输出逐帧位姿与 RGB，不输出逐帧分割掩码。原 `annotation/annotate.py` 仍用于单帧检测框/掩码导出。

## 从头重建与核验

```bash
python3 blender/download_ycb.py
python3 blender/launch.py create-motion --frames 180 --fps 60 --speed 1
python3 blender/launch.py record --samples 16
.venv/bin/python tests/verify_motion.py
```

下载器记录官方 URL、许可和压缩包 SHA-256，已有完整模型时跳过下载。原始模型和大量 PNG 帧不提交 Git，可通过脚本重建。动态 `.blend` 已打包纹理，单独打开不依赖外部纹理路径；若要用原始网格开展姿态评估，仍需下载对应 OBJ。

核验脚本检查恰好一个物体运动、其他物体世界位姿不变，以及三路 MP4 帧数与 FPS、共享时间戳、位姿变换、无尺度变化、所有物体三维包围盒在各相机视野内和 24 厘米平行双目关系。其速度检查针对默认高动态演示；刻意设置低速后需相应调整测试阈值。
