# 04 手写多智能体：Supervisor / Worker

> 上一课：[03 客户端接入与桥接](03-client-bridge.md) | 下一课：[05 LangGraph 对照](05-langgraph.md)
> 对应代码：`multi/bus.py` `multi/agents.py` `multi/supervisor.py` `multi/runner.py`
> 概念呼应：[006 多智能体协作](../../AI-Agent开发教程/006-多智能体协作.md)

006 课讲了"什么时候需要多智能体"和 Supervisor 模式的伪代码。本篇把它落成可运行的四文件实现。

## 1. 先回答：什么时候值得拆

单 Agent + 好工具仍是首选。值得拆成 supervisor/worker 的三个信号（本场景各自对应一个）：

| 信号 | 本教程的体现 | 收益 |
|---|---|---|
| **上下文隔离** | researcher 的检索原文不进 calculator 的上下文 | 每步上下文小而准，防"检索长文淹没计算推理" |
| **权限分立** | writer 只有 `save`、researcher 只有 `search_kb` | 减小工具面；写文件的权限不会被检索环节滥用 |
| **任务类型异构** | 查资料/算数/写文档三种能力，提示词互相冲突 | 每个 worker 一个专注 system prompt |

反例提醒：如果目标只是"算一下 29×50×12"，上多智能体就是灾难——3 倍以上的 LLM 调用换
0 收益。**判断标准：子任务是否需要不同的上下文、不同的工具集、不同的"人设"。**

## 2. 消息总线（bus.py）：先造观察性，再造智能

所有 Agent 间通信走 `EventBus`，而不是各处 `print`：

```python
bus.send("supervisor", "researcher", task)     # 落 history + 广播给订阅者
bus.subscribe(sse_queue.put)                   # Web 端订阅同一事件流
```

三个作用：
- **可观察**：`bus.history()` 完整回放谁在何时派了什么（CLI 打印、SSE 都从订阅者来）
- **可推送**：CLI 和 Web 复用同一 `on_event` 协议，业务代码零感知消费者是谁
- **可审计**：dispatch/交回都带 from/to，事后能算每个 worker 的调用次数与 token

消息是简单 dataclass：`Message(from_, to, content, tool_events)`。

## 3. Worker（agents.py）：独立上下文的迷你 ReAct

每个 worker = **专属 system prompt + 工具白名单 + 一个精简 ReAct 循环**：

```python
class WorkerAgent:
    system = WORKER_SYSTEM[name]        # 检索/计算/写作各一套
    tool_names = WORKER_TOOLSET[name]   # 工具子集（权限分立的落地）
    def run(self, task, llm):           # 只看到 task，看不到全局对话
        messages = [{"role":"system","content":self.system},
                    {"role":"user","content":task}]
        for _ in range(self.max_iters): # max_iters 兜底防跑飞
            ...  # 模型输出工具 JSON → 执行 → 结果回填 → 循环
```

两个刻意的教学取舍：
- worker 用**文本 JSON 协议**调工具（一行 `{"tool":..,"args":..}`），而不是结构化
  tool_calls——让本文件自包含、不依赖 SDK 细节；生产可无缝换成 02 教程 executor
- `_invoke` 把一切错误转 `{"error"}`——与 MCP server 同一纪律，错误以数据回填不炸循环

## 4. Supervisor（supervisor.py）：路由 → 分发 → 验收 → 汇总

对应 006 课伪代码的四步，每步的工程细节：

```
for round in range(max_rounds):          # ① 上限：绝不无限循环
    decision = llm.chat_json(...)        # ② 结构化路由：dispatch / answer
    校验 worker 名（防 LLM 幻觉出不存在的 worker）
    result = workers[name].run(task)     # ③ 分发：task 必须自包含
    if _result_ok(result):               # ④ 结构化验收
        记录、继续
    else:
        带失败原因重派一次；再失败 → 放弃该子任务、继续总目标
```

要点展开：

**② 路由协议**：模型只输出两种 JSON——
`{"action":"dispatch","worker":"...","task":"..."}` 或 `{"action":"answer","content":"..."}`。
动作空间小而封闭，解析鲁棒（`llm.chat_json` 带剥围栏 + 重试）。

**③ 自包含任务文本**：worker 看不到历史，所以 supervisor 必须把已确认的数字写进 task
（"已知团队版 29 元/人/月…请计算…"）。这是 supervisor 提示词里最重要的规则，也是
多智能体 prompt 工程的第一大坑——**偷懒不写全，worker 就只能编**。

**④ 验收与失败处理**（006 课"结构化验收"的最小实现）：
- 不合格判定：结果为空 / 以"（失败"开头 / 前 200 字含 `"error"`
- 重派必须**附失败原因**（006 课原话："否则它只会原样重做"）
- 每个 worker 最多重派 1 次；总轮数 `max_rounds=6` 兜底

## 5. 编排入口（runner.py）：一套事件协议喂两种前端

`run(goal, on_event)` 把 bus 消息与 supervisor 结构化事件统一成 8 种 type：
`goal / supervisor_plan / dispatch / worker_step / worker_done / worker_retry / worker_failed / final / error`。

- CLI（`scripts/03`）：`on_event=打印`
- Web（`scripts/04`）：`on_event=queue.put`，SSE 边取边发（02 教程同款模式）
- 测试：`on_event=收集列表`，断言事件序列

**每个 dispatch/worker_step 都同时走"总线落 history"和"事件推订阅者"**——
可观察性不是事后加的，是骨架的一部分。

## 6. 动手验证

```bash
.venv/bin/python scripts/03_multi_agent.py
# 🧠 [round 1] dispatch → researcher
# 🔧 researcher 调用 search_kb(...) → 命中 2 条定价文档
# 🧠 [round 2] dispatch → calculator
# 🔧 calculator 调用 calc({"expression": "29*50*12"}) → 17400
# 🧠 [round 3] dispatch → writer
# 🔧 writer 调用 save({"filename": "output/summary.md", ...})
# 🏁 最终结论: … 14,790 元/年 …
```

## 思考题

1. supervisor 把 researcher 的检索原文直接塞进 calculator 的 messages，会破坏本篇说的哪个收益？
2. "重派时必须把失败原因写进 task"——如果去掉这条规则，失败重试大概率发生什么？
3. 什么情况下应该把"逐轮 dispatch"改成"一轮并行派给多个 worker"？本教程为什么没做？

### 参考答案

1. 破坏上下文隔离。calculator 的上下文会充满检索原文（几十上百行 FAQ），既浪费 token，又让"做算术"的注意力被无关文本稀释；而 supervisor 摘要后的"29 元/人/月、8.5 折"才是它需要的全部输入。这正是 supervisor 中继的价值：**每跳都在做信息压缩**。
2. worker 收到与上次完全相同的 task，模型大概率输出相同的错误结果——无效重试烧掉 token 后仍失败，最终被"重派后仍失败"规则放弃。带上失败原因（如"calc 报除零"）才能引导换参数/换方法。
3. 当子任务之间无数据依赖（如"同时查三个数据源"）且延迟敏感时并行收益最大。本教程目标是串行依赖链（查价→算账→写文件），第二步需要第一步的输出，并行无意义；且串行轨迹对教学可视化（泳道逐条出现）更友好。并行版可把 runner 改成 `asyncio.gather` + 每 worker 独立 bus 通道，见 06 篇延伸。

---

*上一课：[03 客户端接入与桥接](03-client-bridge.md) | 下一课：[05 LangGraph 对照](05-langgraph.md)*
