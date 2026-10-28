# 海外智驾本地化可行性分析：欧盟、英国、澳大利亚与东盟（马来西亚、泰国、印尼）

> 文中的 P2 / P5 / P7 指作者的其他公开仓库：P2 = [malaysia-smart-feature-benchmark](https://github.com/LUOaini1213/malaysia-smart-feature-benchmark)，P5 = [r152-aeb-scenario-tests](https://github.com/LUOaini1213/r152-aeb-scenario-tests)，P7 = [dms-distraction-warning-tests](https://github.com/LUOaini1213/dms-distraction-warning-tests)。

回答一个工程问题：一套已有的 ADAS / L2 功能（AEB、车道支持、ISA、DMS、EDR、ACC、L2 车道居中与变道）要在这 6 个市场上市，各要改什么，现有传感器方案够不够。做法分四步：

1. 把各市场的法规与评级要求整理成矩阵，每行写明文件和条款；
2. 列出左行 / 右舵和本地环境带来的功能差异；
3. 用传感器可行性计算器推导探测距离、视场和时延需求，比较 3 套参考方案；
4. 在 esmini 里跑一组左行 / 右行镜像场景，检查哪些逻辑必须镜像。

最后汇总成一页 SOR 式的需求差异表。

> 本项目在 AI 编码助手（Claude）辅助下完成。法规内容只取官方文本，查不到的标「未核实」。计算器中的传感器规格，除标明来源的以外都是假设（A-xx）；仿真结论只在本模型内成立。本项目**不声称**任何车辆或功能符合任何法规或评级规程。完整说明见 [report.md](report.md)。

## 结果一览

| 问题 | 结果 | 出处 |
|---|---|---|
| 英国是否适用欧盟 GSR2 | 不适用。DfT 2026-07-16 决定强制 18 项安全技术（AEB、ELKS、ISA、DDAW/ADDW、EDR、倒车检测等），新车型在生效日后 12 个月、新注册在 24 个月后执行（EDR 36 个月）。SI 尚未提交；北爱尔兰按欧盟规则 | GB-01、GB-02、GB-11 |
| 澳大利亚 | ADR 98/01（AEB 车对车 + 行人）自 2026-08-01 对所有新车强制；ADR 98/02（加骑行者）与 ADR 107/00（ELKS，UN R178）新车型 2028-03-01 起。ANCAP 限速辅助用澳新路牌，复用 Euro NCAP 结果时也要重做本地限速试验 | AU-01、AU-02、AU-04、AU-15、AU-17 |
| 东盟三国 | 型式认证都不强制 AEB（马来西亚列为未来实施，泰国接受 R152 认证，印尼不是 1958 协定缔约方）；推动力是 ASEAN NCAP（AEB 车对车 7.5 分、车对摩托车 6 分、盲区 8 分）。泰国不在 UN R79 的适用方名单中，但适用 R171 | MY-01、TH-02、TH-04、ID-01、AN-01、AN-03、AN-05 |
| UN R171 与本地化 | 系统发起的操作须按各国交通规则设计（Introduction ¶8）；不得变入对向车道（§6.2.2）；变道后向间隙：来车减速度不超过 3 m/s²、A = 0.4 / 1.4 s、间距不小于本车 1 s 行程（§6.2.4.1） | UN-06、UN-09、UN-10 |
| 法规矩阵 | 88 行（已核实 71、部分核实 11、未核实 6），覆盖 6 个市场与 UNECE 技术条款，来源 67 条 | regulation_matrix.csv |
| 左行 / 右舵差异 | 10 项：超车侧、环岛、路口转弯方向、ISA 路牌与单位、车道线、摩托车、热带降雨、右舵 HMI、限速与车距、让行通道 | lht_deltas.csv |
| 传感器方案满足的需求数（共 25 条） | 1V1R：晴天 13；5R1V：晴天 23、暴雨 50 mm/h 22；11V5R1L：晴天 24、暴雨 22 | results/tables.md 表 6 |
| 1V1R 的缺口 | 没有后向传感器：6 条变道后向需求和 4 条盲区（摩托车）需求都不覆盖 | 表 6 |
| 暴雨下先失效的需求 | 本车 80 km/h、来车未持续跟踪（A = 1.4 s）的变道需要后向 73.8 m；角雷达 80 m 在 50 mm/h 时降到 68.9 m | 表 6、表 8 |
| ACC 对高速静止车 | 130 km/h 以 2.0 m/s² 停住需要 349.1 m，三套方案都不够；3.5 m/s² 需要 209.3 m，只有长焦摄像头够到 | 表 6 |
| 镜像仿真（esmini，模型内） | 规则集与世界匹配时，8 组右行 / 左行运行的轨迹逐点一致（偏差 0.0 m）；左行世界用右行规则时，系统发起的超车变道变到路缘侧，并从内侧超越前车；超车道有慢车时也会从内侧超越 | 表 10、表 11 |
| 切入检测必须两侧对称 | 只看超车侧的检测，对路缘侧切入晚 0.98 s 才响应：最小间距从 14.21 m 降到 5.77 m，制动从 3.5 m/s² 升到 7.62 m/s² | 表 10 F1 |
| 仿真可信度 | esmini 与纯 Python 后端 26 次运行的离散结果全部一致，自车位置最大差 0.12 m | 表 11 |

## 主要发现

- **英国的问题是时间，不是内容。**
  - DfT 决定采用的技术依据就是欧盟文件：R152.02、(EU) 2021/646、2021/1958、2021/1341、2023/2590、R160.01、R158.00。
  - 因此功能内容可以沿用欧盟版本，避免维护两套软件。
  - 需要单独准备的是：ISA 对英国 mph 路牌与国家限速牌的识别（Euro NCAP 2026 的条件、隐含、动态限速要求也把英国列入 10 国，EU-14、GB-13）；车速表标 mph（UN R39 §5.2.2）；2026-02-01 起 M、N 类车型须持完整 GB 认证。
- **澳大利亚已经立法，但不全。**
  - AEB（车对车 + 行人）已对所有新车强制，ELKS 与骑行者 AEB 2028 年起对新车型强制。
  - 没有查到 ISA、DMS、EDR、L2 的 ADR（标「未核实」，无法证明不存在）。
  - ANCAP 是本地化要求最具体的来源：路牌按澳新调校，规程布置按右舵调整。
- **东盟靠评级驱动，而且摩托车权重大。**
  - WHO 2023 国家概况：二/三轮机动车占道路死亡的 63 %（马来西亚）、51 %（泰国，另有 46 % 为其他或未知）、80 %（印尼）。
  - ASEAN NCAP 规程指出，摩托车在左右车道行驶并自由并线、超车。所以盲区监测和两侧对称的切入检测，是东盟版本的硬需求。
- **左行市场真正要镜像的是「超车侧」这一个语义。**
  - 纵向跟车、切入响应这类按车道相对位置写的逻辑不用改，镜像仿真中结果逐点一致。
  - 硬编码左/右的逻辑会出错：系统发起的超车变道、「不得内侧超车」、超车后回到路缘侧车道。
  - 「能否从内侧超越」各左行市场还不一样：英国高速禁止，澳大利亚多车道标线车道允许，印尼只限特定情形。所以要做成市场配置，不能只做左右镜像。
- **传感器：5R1V 是覆盖东盟评级和变道功能的最低方案。**
  - 1V1R 满足全部 AEB 距离需求（暴雨下最小余量 58.0 m），但没有后向覆盖。
  - 暴雨使角雷达余量变薄：按 ITU-R P.838-3 计算，77 GHz 路径衰减使 80 m 量程在 50 mm/h 时降到 68.9 m。
  - 摩托车穿行切入只有 0.43 s 进入本车路径，扣掉 0.35 s 感知与确认后只剩 0.08 s：靠横向运动触发来不及，需要提前跟踪路缘侧和车道间的摩托车。

## 怎么做的

- **法规**
  - 只用官方文本：EUR-Lex 或欧盟出版局 Cellar 转载的 UNECE 法规、UN 条约库、legislation.gov.au、gov.uk 与 VCA、各国政府公报与法律数据库，以及 ASEAN NCAP、ANCAP、Euro NCAP 规程。
  - P2 已核实的欧盟、马来西亚、ASEAN NCAP 条目直接引用（「复用」列），不重复整理。
  - 部分来源由检索子任务读取并记录条款与原文摘录。三条关键结论由本项目再次打开官方页面复核：DfT 的决定与时间表、泰国不在 R79 适用方名单、R178 的生效日期。
- **计算器（`feasib/`）**
  - 需求按公式推导：AEB 为时延加制动距离，ACC 为舒适减速度加终端时距，变道后向间隙用 R171 §6.2.4.1 与 R79 §5.6.4.7 的同一结构，切入视场按几何关系算。
  - 传感器用「波瓣」模型（距离 × 半角）。
  - 降雨：雷达按 ITU-R P.838-3 的 77 GHz 系数计算路径衰减，摄像头与激光雷达为标明的假设。
  - 成本只给相对档位，不给价格。
- **仿真（`sim/`）**
  - 同一份与交通侧无关的场景描述，生成右行（`rule="RHT"`，车道 −1/−2/−3）和左行（`rule="LHT"`，车道 +1/+2/+3）两套 OpenDRIVE / OpenSCENARIO 文件。
  - esmini v3.10.2 通过 esminiLib（ctypes，沿用 P5 的接法）无界面运行，目标车由 storyboard 驱动，自车交给 ExternalController。
  - 控制器所有与侧别有关的逻辑都只经过一个参数「超车侧」。
  - 另写纯 Python 后端交叉验证。

## 复现

在仓库根目录下运行（需要 esmini v3.10.2 官方发布包，把 `$L` 指向其中的 `bin\esminiLib.dll`）：

```powershell
$L = "<esmini 目录>\bin\esminiLib.dll"
python -X utf8 -B -I scripts/make_scenarios.py
python -X utf8 -B -I scripts/run_feasibility.py
python -X utf8 -B -I scripts/run_sim.py --esmini-lib $L      # 26 次运行 × 2 个后端，单进程，约 3 s
python -X utf8 -B -I scripts/make_tables.py                   # results/tables.md、results/sor_summary.csv
python -X utf8 -B -I scripts/sync_report.py                   # 把 tables.md 的表同步进 report.md
python -X utf8 -B -I scripts/make_plots.py                    # results/fig_mirror.png
$env:ESMINI_LIB = $L; python -X utf8 -B -I -m pytest -q -p no:cacheprovider tests   # 30 项
```

- 没有 esmini 时用 `run_sim.py --backend python`，pytest 为 29 项通过、1 项跳过。
- esmini 打不开含中文的绝对路径，脚本以 `scenarios/` 为工作目录、用相对路径调用（与 P5 相同）。
- 依赖：Python 3.13、matplotlib（只用于画图）、pytest。

## 文件

```
regulation_matrix.csv   法规与评级矩阵：市场 × 功能 × 体系，每行有文件、条款、来源编号、核实状态（88 行）
lht_deltas.csv          左行 / 右舵与本地环境差异：受影响功能、改动类型、需要改什么、验证方法（10 项）
data/sources.csv        来源清单（67 条，含 URL 与核实方式）
data/sor_template.csv   SOR 表模板，数字用 {..} 占位，由 make_tables.py 从结果文件填入
feasib/                 计算器：requirements.py（需求推导）、sensors.py（波瓣与降雨）、suites.py（参考方案）、feasibility.py
sim/                    scenario.py（镜像场景）、esmini_backend.py、python_backend.py、controller.py、runner.py
scenarios/              road_RHT.xodr、road_LHT.xodr 与 10 个 .xosc（5 个场景 × 2 个交通侧，脚本生成）
scripts/                make_scenarios、run_feasibility、run_sim、make_tables、sync_report、make_plots
tests/                  30 项 pytest（计算器 13、仿真 11、矩阵与表格 6）
results/                tables.md（全部表格）、sor_summary.csv、feasibility.csv、requirements.csv、rain_sweep.csv、
                        lc_rear_curve.csv、r79_vsmin.csv、suites.csv、sim_runs.csv、sim_mirror_check.csv、
                        sim_backend_check.csv、sim_summary.json、sim_timeseries/、esmini_logs/、fig_mirror.png
report.md               完整报告
```

CSV 都是 UTF-8 带 BOM，Excel 可以直接打开。

## 局限

- **法规只做到条款层面。**
  - 没有做认证判定。
  - 东盟三国的国内实施细则（泰国 TISI/DLT、印尼 PM 33/2018）读得很浅。
  - 「未见要求」只代表所查文件中没有。
- **计算器是一阶估算。**
  - 波瓣模型忽略了雷达天线方向图、遮挡、多径、目标反射率分布、虚警与漏检。
  - 传感器规格大多是假设，结论应读成「需求是多少、哪条先失效」，而不是「某型号够不够」。
  - 摄像头与激光雷达的降雨系数没有引用来源。
- **仿真是逻辑层检查。**
  - 感知用真值，控制器是演示用的简化版本。
  - 场景只有直道上的切入、内侧超越和超车变道，没有环岛和路口。
  - 结论是「哪类逻辑必须镜像、不镜像会怎样」，不是性能指标。

## 未核实（摘要）

- 欧盟 ISA (EU) 2021/1958 附件中的路测验证细则；GSR 是否改为引用 UN R178。
- 英国：DfT 对 ISA 的 mph 处理、TSRGD 原文、GB 对 R79/R171 的处理、Euro NCAP 是否单独测试右舵版本。
- 澳大利亚：ISA、DDAW/ADDW、EDR、L2 是否有 ADR（未查到，不能证明不存在）；ANCAP DMS 规程内容。
- 泰国：2026 年消费税低税率档的厅长条件原文（新闻称 6 项 ADAS 至少装 2 项）、TISI/DLT 是否强制 ADAS、超车与环岛法条。
- 印尼：PM 33/2018 正文；马来西亚：超车法条与登记车辆中的摩托车占比。
- ASEAN NCAP：CMFtap 的转弯方向、盲区测试横向距离的量取口径。
- 计算器的全部假设 A-01…A-20 与仿真假设 A-21…A-26。

完整清单见 report.md 第 10 节与 results/tables.md 表 14。
