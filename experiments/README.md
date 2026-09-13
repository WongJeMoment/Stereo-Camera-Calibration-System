# 六物体 × 六轨迹批量实验

每次场景只有一个运动物体。六个原始 YCB Google 16k 扫描模型为饼干盒、糖盒、番茄汤罐、芥末瓶、金枪鱼罐和香蕉。
六组条件包括慢速直抛、中速左斜抛、快速右斜抛、高弧线、大横移左抛、高速高抛，参数在 `throw_suite.json`。
各物体重复相同的六组初始条件，便于控制变量；一共 36 次抛掷。

## 运行

在项目根目录运行，需要现有 Blender、FFmpeg、原始 YCB 模型及中文字体：

```bash
.venv/bin/python -m pip install -r experiments/requirements.txt
.venv/bin/python -m experiments.throw_suite --workers 3
```

默认两个独立任务并发，可通过 `--workers 1/2/3` 调整。每组场景独立创建，避免覆盖原来的单瓶实验。
`--limit 1` 可先试跑第一组；去掉该参数后继续全部实验。
每组通过视频、位姿、视野验证后保存检查点，已完成的组会跳过。配置变化时必须换一个 `--output`，避免混用不同实验。
只有录像通过验证后才复用该组原视频；预测或叠加阶段失败后可以重新运行命令接续。

## 保存位置

```text
results/throw_suite/
├── summary.xlsx                     # Excel：36组主表、108行方法对比、1440行逐帧坐标、评估说明
├── summary.csv                      # 默认重力预测，一组一行
├── all_methods.csv                  # gravity / constant_velocity / constant_acceleration
├── index.html                       # 总表和每组视频链接
├── manifest.json                    # 本次配置快照
└── 003_cracker_box/01_slow_straight/ # 其余5物体、5组按同样结构保存
    ├── scene.blend                  # 打开即可在 Blender 查看该组动画
    ├── motion/                      # 3路4K原视频、预览、相机参数、位姿、原始PNG
    ├── prediction/                  # 指标、每帧预测XYZ/速度/真值/误差、图表
    │   └── views/gravity/           # 3路4K预测叠加视频及合成预览
    ├── complete.json               # 该组完成标记
    └── logs/                       # 创建、录制、预测、叠加日志
```

单相机视频均为 3840×2160、60 FPS、60 帧（1 秒）。共 108 路原始视频和 108 路重力预测叠加视频，另有每组的合成预览。
PNG 可用于精确逐帧分析。整个 `results/throw_suite/` 为可重新生成的本地实验产物，已由 Git 忽略；视频、场景、位姿和表格均保留在本机，不随源码上传 GitHub。

```bash
# 查看表格/视频入口
xdg-open results/throw_suite/summary.xlsx
xdg-open results/throw_suite/index.html

# 用 Python 查看任意一组预测视频
.venv/bin/python -m trajectory_prediction.view \
  --folder results/throw_suite/011_banana/06_fast_high/prediction/views/gravity

# 在 Blender 中打开任意一组
python3 blender/launch.py open \
  --scene results/throw_suite/003_cracker_box/01_slow_straight/scene.blend

# 只重新汇总已完成组
.venv/bin/python -m experiments.throw_suite --summarize-only
```

## 评估与解释

使用已有算法：前 20 帧历史，固定在 t=19/60 秒预测后 40 帧，最大预测时距为 40/60 秒。
各相机展示的是同一三维预测；不会把三台相机误当成三个独立预测样本。
同组跨物体使用相同噪声种子，每个条件一个种子；不同组采用不同种子，保存在表格中。

输入仍为 `synthetic_stereo`：只投影历史几何中心，加 1 px 标准差的独立高斯噪声后双目三角化。
没有从 RGB 视频检测物体，也没有把未来位置或场景初速度传入预测器。未来 JSONL 真值只用于评分。
物体形状、质量、纹理未作为预测输入，且仿真无空气阻力/碰撞。因此不能把这些结果解释成真实视觉检测精度或模型识别不同物体后的泛化性能。
同初始条件、同相机参数、同种子的物体可能有相同误差，这是受控实验的预期结果。

表格含物体、组别、初位置、XYZ初速度、速度大小、翻滚速度、观测设置、观测误差、预测 ADE、FDE、RMSE3D、最大误差及视频路径。
误差单位厘米；FDE 是最后一帧误差，不是碰撞落地点误差。三种方法都只对未来帧评分。

双目位置、方向和 24 cm 基线保持不变；必要时同时降低两相机焦距以保证每个模型的全部包围盒至少有 8% 边缘余量。
侧面相机按每组完整轨迹和实验台自动取景，保证至少 10% 边缘余量。每组真实相机内外参独立保存在 `motion/calibration.json`。
校验包括全部帧的视频解码计数、三相机帧率/分辨率、位姿同步、弹道真值、双目基线及全程视野覆盖。

## 单独创建新抛掷条件

```bash
python3 blender/launch.py create-motion --moving-object 011_banana \
  --launch-position -0.35 1.3 0.8 --launch-velocity 0.35 -2.65 5.8 \
  --spin-deg-s 420 --spin-axis 0.4 0.3 0.85 --fit-stereo \
  --output assets/scenes/banana_throw.blend
```

位置为米，速度为米/秒，翻滚角速度为度/秒。保持自由飞行期间物体在地面上方且位于双目相机前方。
