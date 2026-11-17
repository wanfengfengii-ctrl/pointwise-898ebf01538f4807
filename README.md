# Device alarm archive

Python 3.11 标准库工程，无安装依赖。产品用于离线登记设备模型、接纳告警更正、固定分析任务并发布可重开报告。所有命令从项目根目录运行。

```sh
python3 -B -m unittest discover -s tests -v
python3 -B -m examples.run_archive
```

demo 使用有限设备样例，在测试临时目录建立真实 SQLite 归档：先固定旧任务，再更正模型和告警，关闭重开后执行旧任务，展示发布失败、重开重试、新旧报告及幂等结果。退出时清理自己的临时目录。

## 公开接口

```python
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model, get_model_revision
from alarm.observations.batches import apply_observations
from alarm.archive.tasks import create_task, load_task_snapshot
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report
```

`ArchiveStore.open(path=':memory:')` 返回上下文管理器；显式路径用于持久归档。接口均以 store 为第一个参数。

`register_model(store, model_id, request_id, states, Q, initial, intensities)` 返回 ModelReceipt，字段为 model_id、revision、request_id。states 的顺序就是矩阵和概率轴；intensities 是告警类型到状态强度向量的字典。必须有 2—4 个唯一状态及恰好两类告警。接受有限 int、float、Decimal，拒绝 bool；float 按其十进制字符串解释。建议使用 Decimal 表达业务小数。Q 非对角率及强度非负，Q 每行精确为零，initial 非负且精确和为一。MODEL_VALIDATION_TOLERANCE 为零；非法数据不自动归一化或修正。同模型同请求同规范内容重放返回原回执，异内容抛 ModelRequestConflict。新请求创建新修订，历史不可变。非法模型抛 ModelValidationError；未知明确修订抛 ModelRevisionNotFound。

`apply_observations(store, sequence_id, changes)` 接受 ObservationChange 或等字段字典的可迭代批次，返回 ObservationRevision。新增或更正格式为 `{alarm_id, source_revision, action:'put', time, kind}`；撤回格式为 `{alarm_id, source_revision, action:'withdraw'}`，不能附带事件字段。source_revision 是非布尔正整数。time 有限且非负，kind 为非空字符串。整批先验证；同身份同版本异内容，包括历史版本冲突，抛 ObservationRevisionConflict；字段非法抛 ObservationValidationError。两类错误均整批回滚。较低版本忽略，同版同内容重放，较高版本覆盖；撤回保留水位。首次空批创建空序列。无有效集合或水位变化时返回现有序列修订；接纳过的源版本内容保留用于识别历史冲突。同刻不同身份保留。有效事件按时间、身份稳定排序。明确序列修订可通过 read_observation_revision 读取。

`create_task(store, model_id, model_revision, sequence_id, observation_revision, T, queries=(), windows=())` 返回任务 ID。修订必须明确。queries 是有序时刻列表；windows 是 OccupancyRequest 或 `{state,start,end,label}` 字典列表，label 可省略。每个窗口按位置生成独立 index，允许相同 label、重复窗口、重叠窗口及零窗口，不去重。T 有限且非负；所有事件和查询在 [0,T]，窗口满足 0≤start≤end≤T。模型状态、告警类型必须匹配；最多 64 个有效告警和 4 个窗口，最大总离开及告警强度乘 T 不超过 40。未知修订抛明确的 LookupError 子类，其余跨输入非法抛 SnapshotValidationError，均不创建任务。创建时复制完整输入，执行时不读取当前修订替换它。

`analyze_task(store, task_id, before_commit=None)` 返回报告 ID。全部计算在发布事务外完成，before_commit 是无参数故障接缝，在全部发布写入后、事务提交前调用。回调异常原样传播并回滚。已发布任务再次执行直接返回原报告 ID，不调用接缝。未知任务抛 TaskNotFound。零路径支持抛 ImpossibleEvidence；数值错误抛 AnalysisExecutionError，不发布部分结果，任务仍为 READY，可重试。每任务至多一份报告。

`read_report(store, report_id)` 返回独立嵌套字典；未知或未发布报告抛 ReportNotFound。字段包括 task_id、binding、T、states、alarms、queries、occupancy_axes、log_likelihood、posteriors、means、covariance。后验列按 states 排列；查询行按 queries 排列；占用向量及协方差行列按 occupancy_axes 排列。数值为 Decimal。报告 JSON 编码使用显式 `$decimal` 对象，无损保留数值，不转换为二进制浮点。修改返回值不改变归档。

## 条件分析语义

行向量约定下，等待生成元为 Q-diag(sum(lambda))，类型告警乘 diag(lambda_type)。观察包含整个 [0,T] 没有其他告警的信息；0、T 处告警各参与一次，同刻各身份逐个参与。告警本身不触发隐状态跳变。状态查询是使用完整未来证据的平滑后验。

占用量为窗口内处于指定状态的累计时长。均值和完整协方差均以全部观测为条件；不相交窗口也可相关。实现以不可变完整证据计划交接条件语义，联合传播零阶、一阶和混合二阶路径矩，所有通道共同缩放。内部使用按 T 归一化的积分及根据 T 数量级提升的 Decimal 精度，最后恢复时长单位。合法极小正证据不使用固定拒绝阈值；结构零支持独立识别。明显负方差、非对称或不可信矩阵拒绝发布；数值舍入残差允许在公开 1e-8 绝对误差内，不以裁剪掩盖错误。

## 回归

完整套件覆盖模型及请求身份、源版本历史、冲突回滚、撤回和旧版重放、同刻事件、输入快照边界、全段静默及尾部静默、未来告警平滑、正罕见证据、零支持、重叠与重复窗口、跨窗依赖、零窗口、零时长、大时长、三四状态、独立矩阵解析例、可切换链独立标量高精度级数、冻结后更正、报告轴、返回副本及磁盘重开重试。独立参考不调用生产条件分析或生产矩阵指数生成期望值。

归档采用单进程离线调用和显式 SQLite 事务，不提供在线接入、工作者调度、参数训练或展示前端。
