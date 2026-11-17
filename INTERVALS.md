# 区间定位告警：公开扩展契约

本题扩展 README.md 的真实设备告警归档，沿用 Python 标准库、Decimal 和 SQLite。原有文件与全部原测试保留；当前实现只接受精确 time，本文件与 examples/interval_cases.py 提供新增契约和有限解析样例，不提供区间求解器。接口仍从 README.md 所列模块导入。

## 观测与冻结

apply_observations 的 put 接受 time 或 interval=[lo,hi]，两者恰有一个非 None。interval 接受两项 list/tuple；端点沿用 number 的非布尔有限数规则，满足 0≤lo<hi。ObservationChange 在原位置参数之后增加可选 interval=None，原调用保持有效；kind 规则不变。withdraw 不得有非 None 的 time、interval 或 kind。非法批次抛 ObservationValidationError，保持整批无变化。

独立身份、较高源版本覆盖、撤回水位、同版重放、历史同版冲突和整批回滚沿用原接口。interval 与 time 是内容的一部分；等值的数值和 list/tuple 区间视为同一内容。允许同一身份在新版本从精确改为区间或反向更正。接纳后复制区间，不保留调用方可变别名。

ObservationRecord 和 SourceVersion 对区间记录提供 time=None、interval=(Decimal(lo),Decimal(hi))；精确记录的 time 保持 Decimal，interval=None。记录按定位起点（精确 time 或区间 lo）、alarm_id 排序；此顺序只用于稳定展示，不表示事件发生次序。历史读取和 load_task_snapshot 保留同样的定位信息及明确修订，旧精确归档、旧任务和旧报告仍可读取。

create_task 接受含区间的观测修订，要求每个区间包含于 [0,T]。含区间任务最多 2 个区间身份、8 个精确事件和 2 个占用窗口；超限或越界抛 SnapshotValidationError，不创建任务。模型、类型匹配、强度时长预算及其余查询和窗口规则沿用原接口；纯精确任务保持全部原能力。

## 条件分析

每个区间身份代表一个独立标记事件，恰发生一次；将原精确记录的路径密度对各身份允许的时刻联合积分，覆盖所有可行先后次序，不除以区间宽度，也不除以同类型身份的排列数；整个 [0,T] 没有其他告警的信息仍参与。告警不改变隐状态。区间端点无额外原子质量，区间事件与其他事件同刻按零测集处理；纯精确同刻规则不变。

analyze_task 仍返回报告 ID，read_report 返回区间积分后的 log_likelihood、原查询顺序的平滑后验、占用均值和完整协方差。证据传播与占用计算必须消费同一身份完成语义，全部结果共同条件化于所有精确及区间记录。窗口重叠、重复、零长度及跨窗相关性保留原语义，查询用完整未来证据。

数值保持 Decimal；后验、均值和协方差绝对误差≤1e-8，log_likelihood 绝对误差≤1e-8。结构零证据抛 ImpossibleEvidence；合法极小正证据不得按固定阈值拒绝。数值失败仍抛 AnalysisExecutionError，不能发布部分结果。

报告 alarms 中精确项的既有字段保持不变；区间项为 {id,source_revision,interval:[Decimal(lo),Decimal(hi)],kind}，不含 time。快照和报告保留区间、身份及明确修订；更正、输入或返回值修改与关闭重开不得改变旧任务。沿用原发布失败回滚及重试边界，保留原接口和全部原测试。

允许全量重算、枚举至多两个区间身份的次序及复用现有矩阵指数，不指定内部表示。不要求参数训练、在线接入、并发工作者或前端。

## 可手算业务样例

examples.interval_cases.cases() 返回全新的嵌套字典，definition 可直接传给 register_model，changes 可直接传给 apply_observations，T、queries、windows 可直接传给 create_task。

switch 样例：T=1，初态(1,0)，Q=[[-1,1],[0,0]]，a 强度(1,0)，b 强度(0,1)，不同身份分别为 a、b，区间均为 [0,1]。联合证据为 exp(-1)*(3/exp(1)-1)>0；两个中点告警则是零证据。唯一隐状态跳变时刻 u 的未归一化密度为 exp(-1-u)*u*(1-u)，0<u<1。因此查询 after 的概率是此密度在 [0,t] 的积分除以总质量。两个 after 窗口 [0,0.5]、[0.5,1] 的时长分别为 max(0,0.5-u) 和 1-max(0.5,u)，可直接积分核对全部一二阶矩。expected('switch') 给出 Decimal 期望值，不调用生产传播或矩阵指数。

static 样例：Q=0，两个同类型不同身份区间宽度分别为 0.5、0.75。状态 s 的证据权重为 initial[s]*exp(-T*sum_rates[s])*a[s]**2*0.5*0.75，无 2! 因子；条件后验是归一化状态权重，窗口时长由固定状态决定。rare 样例把 a 强度设为 1e-300、2e-300，仍须得到有限对数证据和合法后验。完整输入与输出在样例模块中，运行 python3 -B -m examples.interval_cases 可打印。

## 交付与联动验证

交付区间观测修订及冻结表示、条件分析与联合占用的联动实现，并说明身份完成、次序合并和共同分母的不变量。独立核账不得仅让两个调用同一目标传播器的结果互相比对；可用解析积分、独立标量级数或有误差控制的低维积分。

联合验证须覆盖重叠、嵌套及相离区间、同类型双身份、区间内夹入精确告警、查询切面、双窗口交叉协方差、结构零与极小正证据，以及区间修订→冻结→更正→重开执行旧任务→发布失败回滚→重试读取。保留并运行全部原回归，新增用例与独立参考，不修改原测试。

沿现有 .pointwise-runtime.json 接通原回归和新增真实核验，demo 展示区间条件报告及更正后重开执行旧任务；运行清单的现有字段格式不变。样例模块和 test_interval_examples 只验证公开解析材料与既有精确接口，不代表目标功能已经完成。
