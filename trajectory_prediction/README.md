# 瓶子轨迹预测 V1：设计与可运行基线

目标：在一段观测结束时，预测瓶子未来的世界坐标、速度，并与 Blender 逐帧真值对比。
本版仅预测几何中心 XYZ，不预测姿态或碰撞后的轨迹。

## 运行与查看

在项目根目录执行：

```bash
.venv/bin/python -m pip install -r trajectory_prediction/requirements.txt
.venv/bin/python -m trajectory_prediction.run
xdg-open results/trajectory_prediction/index.html
```

默认使用前 15 帧观测，在第 15 帧时一次性预测第 16–60 帧；观测时间是 0–0.2333 秒，最大预测时距 0.75 秒。
预测结果不会随未来真值更新。可调整 `--observe-frames 10`、`--noise-px 2`、`--seed 43`。

```bash
# 理想历史观测：检查算法上限，单独输出，避免覆盖默认结果
.venv/bin/python -m trajectory_prediction.run --mode oracle_history \
  --output results/trajectory_prediction/oracle
```

| 文件 | 用途 |
| --- | --- |
| `models.py` | 仅接收历史观测和未来时间的预测器 |
| `observations.py` | 几何中心投影、像素噪声、双目 DLT 三角化 |
| `run.py` | 切分历史/未来、运行、评估和报告生成 |
| `requirements.txt` | 独立 Python 依赖；无需 Blender、GPU 或下载模型 |
| `../results/trajectory_prediction/index.html` | 可离线打开的图表与指标页面 |
| `../results/trajectory_prediction/comparison.png` / `.svg` | 三维轨迹、Y-Z 投影、误差曲线、高度曲线 |
| `../results/trajectory_prediction/observations.csv` | 历史三维观测及左右图像坐标 |
| `../results/trajectory_prediction/predictions.csv` | 未来逐帧预测、真值、预测速度及误差 |
| `../results/trajectory_prediction/metrics.json` | 参数、观测误差、各模型指标及估计状态 |

## 从三个视频视角查看预测

直接用 Python 桌面窗口查看（不用浏览器）：

```bash
.venv/bin/python -m trajectory_prediction.view
```

窗口支持相机切换、进度拖动、0.1/0.25/0.5/1 倍速播放。
空格播放/暂停，左右方向键逐帧，数字 0/1/2/3 切换合成/左目/右目/侧面，Esc 退出。
默认暂停在第一帧；点击播放后即可查看预测阶段。放大窗口或选择单相机能更清晰地看坐标。
`--folder results/trajectory_prediction/views/constant_acceleration` 可查看其他方法生成的视频。
查看器用 Tkinter 显示、OpenCV 解码，兼容没有 GUI 功能的 OpenCV 构建；需在有图形桌面的终端运行。
Ubuntu 若提示缺少 tkinter，安装系统包 `python3-tk`。无需重新运行 Blender。

```bash
.venv/bin/python -m trajectory_prediction.render_views
xdg-open results/trajectory_prediction/views/gravity/index.html
```

该命令读取已生成的 `predictions.csv`，默认展示 `gravity` 方法；修改预测后需重新运行此命令。
可用 `--method constant_acceleration` 或 `--method constant_velocity` 查看其他基线，输出放在各自方法目录。
需要系统安装 `ffmpeg` 和中文字体；默认使用 NotoSansCJK-Bold，可通过 `--font /path/to/font.ttf` 指定。

每个相机输出保持原始 4K、60 FPS、60 帧的 MP4，另有 1920×1080 三视角合成预览和逐帧/慢放页面。
左上角显示真实 XYZ、预测 XYZ、每轴偏差（预测减真实，米）、三维误差（厘米）及预测时距。
这些是统一的世界坐标，所以三个相机的数字一致，投影位置不同。
青色实线只累积至当前帧的真实轨迹；橙色虚线在历史观测结束时显示预测的完整未来段；圆为当前真值，十字为当前预测，红线连接两者。
前 15 帧属于观测期，预测值和误差显示 `--`。仅叠加预测结果，不从视频识别物体。
`verification.json` 记录每路输出分辨率、帧率和帧数；原视频不被覆盖。

## 2026 年论文启发

按“2026 年以来”理解时间范围；检索截止 2026-09-12，不引用未来尚未发表的论文。以下是方法设计依据，不代表实现了论文模型或复现了论文精度。

1. **Residual Kalman Dynamics for Event-Based UAV Forecasting**，Nyblom 等，2026-09-01 提交，ECCV 2026 NEVi workshop，
   [arXiv 原文](https://arxiv.org/abs/2609.00839)。论文在匀速 Kalman 基线上学习加速度形式的残差，并检查数据集运动先验导致的捷径。
   对本项目的启发：保留强物理基线，后续学习残差；评估时按完整抛掷分组，避免相邻帧泄漏。
   区别：原论文处理事件相机的 UAV 二维框预测，本项目是 RGB 双目下瓶子三维中心；V1 尚未实现 Kalman 或神经残差网络。
2. **Physics-guided residual learning for phase-aware UAV trajectory prediction in urban environments**，Islam 等，Scientific Reports，2026-08-28，
   [期刊原文](https://www.nature.com/articles/s41598-026-67222-5)。论文结合物理引导、序列模型与残差修正，并使用物理可行性约束。
   对本项目的启发：有足够独立轨迹后，让小网络学习重力模型未解释的扰动，并增加加速度/平滑性约束。
   区别：UAV 有主动控制，瓶子是自由飞行，不能照搬其动力学、参数或误差数值。

基于上述思路，本项目采用“先建立可验证物理基线，再增加视觉与残差”的工程路线，这是项目设计选择。

## V1 数据流与模型

```text
历史几何中心 → 左右相机投影 + 像素噪声 → 双目三角化 → 历史 XYZ
                                                          ↓
                                      匀速 / 自由加速度 / 已知重力
                                                          ↓
                                                 未来 XYZ、速度
                                                          ↓
未来 Blender 真值 ──────────────────────────────────────→ 评估与图表
```

默认 `synthetic_stereo` 是受控仿真：仅把历史中心投影到左右相机，分别添加独立 1 px 标准差的高斯噪声，再三角化。
没有读取视频像素，也没有运行检测器。`oracle_history` 则直接使用无噪声历史中心，是理想观测基线。
这两种模式都不代表实际视觉精度；噪声模型未覆盖模糊、遮挡、错配或系统偏差。

使用 `results/motion/calibration.json` 的当前相机参数，**不使用**旧场景的 `results/calibration/calibration.json`。
真值取 `poses/Stereo_Left.jsonl` 中 `geometry_center_world_m`，世界坐标单位米，Z 轴向上。
几何中心不是实测质心；当前动画恰好使这个点沿理想抛物线运行。翻滚中的模型原点不等于中心，不能直接使用位姿矩阵的平移列。
第三台相机在此版保留作独立观察；不参与三角化或预测输入。

以最后一次观测为时间原点，已知重力方法求解最小二乘：

```text
历史观测 p(t) - 0.5*g*t² ≈ p_anchor + v_anchor*t
未来预测 p(h) = p_anchor + v_anchor*h + 0.5*g*h²
g = [0, 0, -9.81] m/s²
```

匀速基线令 g=0；自由加速度基线从历史数据拟合全部三个方向的恒定加速度。
不读取场景保存的发射位置、初速度、运动公式参数；9.81 是显式可调整物理先验。
目前仿真也采用相同重力假设，因此重力模型误差很小是预期现象，不能据此声称复杂真实运动预测已解决。

## 如何看好坏

仅对未来帧评分，数值越小越好：

- ADE：每帧三维欧氏误差的平均值。
- FDE：最后一个预测帧的三维欧氏误差；不是落地点误差，当前记录不包含碰撞着地。
- RMSE_3D：三维欧氏距离平方的均值再开方，不是每坐标维度的 RMSE。
- 0.1 / 0.25 / 0.5 / 0.75 秒误差：用最近的未来采样帧，报告实际时距。

图中黑线是真值；预测曲线从观测截止后开始；误差曲线显示提前预测越远是否越不稳定。
数据目前只有一次抛掷。V1 数字是这一条轨迹、一个随机种子的示例，没有跨轨迹训练/测试或泛化结论。

当前运行结果（15 帧历史、1 px 噪声、seed=42，单位厘米）：

| 方法 | ADE | FDE | RMSE_3D |
| --- | ---: | ---: | ---: |
| 匀速 | 143.31 | 366.11 | 179.52 |
| 自由加速度 | 16.07 | 46.57 | 21.36 |
| 已知重力 | 8.54 | 14.59 | 9.26 |

理想历史观测下，已知重力模型 ADE 约 `1.40e-7 m`，与当前理想弹道生成机制相符。
有噪声时，短观测窗口中的初速度误差会在外推时累积，不能套用无噪声精度。

数值测试：`.venv/bin/python -m unittest discover -s tests -p test_trajectory_prediction.py`。

## 后续版本设计

1. **V2 真实视频观测**：同步双目 RGB → 同一个三维几何点的关键点/6D 位姿检测 → 三角化和异常值拒绝 → 带重力状态滤波 → 未来轨迹。
   翻滚物体的左右 2D 检测框中心通常不是同一物理点，不能直接当成可靠立体匹配。第三相机用于独立重投影可视化。
2. **V3 残差学习**：采集数百至数千次不同初速度、方向、旋转、视角的抛掷，并真正加入阻力、风扰动等动力学变化。
   按整次抛掷拆分训练/验证/测试；只用训练集统计量。用历史位置、速度、视觉置信度预测加速度残差，再积分得到未来位置。
   网络候选为小型 GRU/MLP；损失包含未来位置误差与残差幅度、平滑性约束。具体模型由独立验证集选择。
3. **评估扩展**：固定历史时长、多个预测时距、多随机种子、不同速度/遮挡/像素噪声；比较三种 V1 基线、Kalman、物理加残差。
   单独报告观测重建误差与未来预测误差；加入置信区间覆盖率，记录推理延迟；不能只报告最优一次。
4. **姿态预测另作模块**：使用四元数与角速度，单独评估旋转测地误差。需要接物时再加入碰撞与接触阶段的模型。

本版不自动改动 Blender 场景或视频，也不自动上传 GitHub。
