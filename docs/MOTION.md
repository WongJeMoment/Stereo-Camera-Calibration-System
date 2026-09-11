# 单物体抛掷与三相机 4K 录制

当前 `assets/scenes/ycb_motion.blend` 中只有一个食品目标：YCB 原始扫描模型 `006_mustard_bottle`（芥末瓶）。其他五个食品已从场景中移除，保留实验台、灯光和双目装置。模型使用原始扫描纹理，来源和署名见 [YCB_SOURCE.md](../assets/models/YCB_SOURCE.md)。

## 查看与录制

```bash
python3 blender/launch.py open   # 打开场景；空格播放抛掷动画
python3 blender/launch.py record # 默认原生 3840×2160、60 FPS，三路同步录制
```

视频保存在本机 `results/motion/`：

- `Stereo_Left.mp4`、`Stereo_Right.mp4`、`Side_Overview.mp4`：三份独立的 **4K（3840×2160）** MP4。
- `multiview.mp4`：1920×360 三路并排预览，经过缩小，不是原始 4K。
- [index.html](../results/motion/index.html)：本地播放页面，提供 0.25 倍慢放和各视频的保存链接。
- `frames/相机名/`：原生 4K 无损 PNG 帧；`poses/相机名.jsonl`：每帧 6D 位姿。

默认每路 60 帧、60 FPS，视频长 1 秒，记录一次快速抛掷。物体不是绕原点转圈：其中心从 `(0.42, 1.05, 0.65)` 米出发，沿相机方向前进 2.3 米，同时横移 0.6 米，上升约 1.185 米后下落。重力加速度为 9.81 m/s²，翻滚角速度约 260°/s。

轨迹使用 `p(t) = p0 + v0*t + 0.5*g*t²`。初始竖直速度依据动画时长确定，使末帧与首帧的高度相同。旋转采用固定倾斜轴的四元数翻滚，不是竖直轴上的原地自转。没有模拟抛出者的手、接住动作或落地碰撞，镜头记录的是自由飞行段。

## 参数调整

```bash
# 重新创建默认抛掷
python3 blender/launch.py create-motion --frames 60 --fps 60 --speed 1
python3 blender/launch.py record

# 以 120 FPS 采集约一秒的抛掷，适合慢放分析
python3 blender/launch.py create-motion --frames 120 --fps 120
python3 blender/launch.py record --output results/throw_120fps

# 更高抗锯齿采样；或改用 Cycles 路径追踪
python3 blender/launch.py record --samples 64
python3 blender/launch.py record --engine CYCLES --device AUTO --samples 32

# 关闭运动模糊，生成瞬时姿态训练图像
python3 blender/launch.py record --shutter 0 --output results/throw_sharp
```

默认使用 Blender EEVEE GPU 渲染原生 4K 图像，不是从低分辨率视频放大。`--samples` 影响抗锯齿质量，不改变 FPS；`--width` 和 `--height` 可修改分辨率。每路视频独立编码为 H.264 MP4，逐帧 PNG 保留为无损输入。

`--frames` 与 `--fps` 一起决定抛掷时间，因此也会影响弧线高度。`--speed` 调整水平飞行距离和翻滚速度；改变这些参数后需要重新检查取景，默认相机针对约一秒的单次抛掷设置。`--moving-object` 可以换成下载器支持的其他 YCB 模型，但场景始终只导入所选的一个模型。

默认快门为帧间隔的 0.25，在 60 FPS 时曝光约 1/240 秒，采用中心快门。位姿真值对应曝光中心，RGB 中的模糊边缘对应曝光时段内的运动，不能当作瞬时轮廓。使用真实纹理扫描模型；此流程没有生成式 AI 图像生成步骤。

## 同步、相机参数与位姿

渲染器在每个时间步固定场景状态，再顺序渲染三台相机，因此三路共享帧号、时间戳和世界位姿。没有模拟滚动快门、时钟漂移或硬件触发误差。

`results/motion/calibration.json` 保存本次录制的相机真值、分辨率、FPS、曝光时间、模型信息，以及起点、初速度和重力参数。双目基线仍为 0.24 米；双目位置改为 `(±0.12, -2.8, 1.2)`，焦距 24 mm。侧面相机位于 `(4.8, -4.8, 3.8)`，焦距 28 mm，覆盖抛掷弧线和整个实验台。

**不要复用旧相机参数。** `results/calibration/calibration.json` 对应原静态标定场景，不适用于当前视频。本次 `results/motion/calibration.json` 是 Blender 真值，未对新布局重新执行 ChArUco 图像标定。

每个 JSONL 位姿文件中，每行对应一帧。`object_to_camera` 满足 `P_camera = T @ P_model`，平移单位为米。OpenCV 相机坐标为 X 向右、Y 向下、Z 向前；`R_model_to_camera` 是 3×3 旋转，`t_model_to_camera_m` 是三维平移。

`P_model` 必须来自 `assets/models/ycb/006_mustard_bottle/google_16k/textured.obj`。原始模型坐标和米制尺度未修改，轨迹围绕包围盒中心旋转，导出的变换仍对应原始 OBJ 坐标。Google 扫描坐标不一定与 YCB-V/BOP 模型坐标一致，不能直接混用。物体实例编号保留为 4，并不表示场景还有其他三个目标。

## 重建与核验

```bash
python3 blender/download_ycb.py
python3 blender/launch.py create-motion
python3 blender/launch.py record
.venv/bin/python tests/verify_motion.py
```

验证会检查：仅有一个目标、三路均为 4K、帧数与 FPS 一致、位姿同步且为米制刚体变换、物体在相机视野内、双目基线正确，并检查向前位移和重力抛物线，避免把原地旋转误当作抛掷。改变默认轨迹或输出尺寸后，需要相应调整测试预期。

原始模型和大量 PNG 不提交 Git，可通过脚本重建。`.blend` 已打包目标纹理。重新录制会覆盖同名视频和位姿文件；成功编码后会清理上次较长录制遗留的多余帧。
