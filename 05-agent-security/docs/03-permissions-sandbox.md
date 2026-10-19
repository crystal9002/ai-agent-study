# 03 · 权限分级与沙箱：让 Agent "手里没权"

## 本课要点

- 三级权限：read 自动放行 / write 记录放行 / destructive 必须审批（default-deny）。
- shell 双防线：**白名单是主力**，黑名单拦白名单命令的危险变体；`shell=False` +
  超时兜底——直接扩展自 [012 练习 1](../../AI-Agent开发教程/012-进阶练习清单.md)。
- 路径沙箱：realpath 之后必须落在沙箱内，一次校验防住 `../`、绝对路径、软链接。

## 1. 三级权限（`sec/permissions.py`）

| 级别 | 例子 | 策略 | 依据 |
|------|------|------|------|
| read | list_files / read_file / 白名单 shell | 自动放行 | 不改变世界状态 |
| write | write_file | 记录审计后放行 | 可逆（可重写回来） |
| destructive | delete_file | 审批（未批 = 拒绝） | 不可逆 |

策略可配置（`POLICIES`）：

```
strict       只读；写/删除硬拒绝（连审批入口都不给）
auto（默认）  只读自动批、写记录放行、删除走审批闸门
             （闸门默认 APPROVAL_MODE=deny → 等效"destructive 拒绝"）
interactive  同 auto，但闸门强制 ask：tty 逐条 y/N，Web 出待审卡片
```

关键点：`level_for(tool)` 对未知工具返回 `None` → 直接 deny。
这就是 **default-deny**：新加一个工具忘了配权限？默认不放行，而不是默认放行。

## 2. 路径沙箱（`permissions.PathSandbox`）

```python
p, err = sandbox.resolve(user_supplied_path)   # 失败返回拒绝原因
```

实现只有几行，但每一处都对应一类真实攻击：

- `Path(path).expanduser()` 后与沙箱根拼接，`resolve()` 解析 `..` 与软链接；
- 校验 `resolved == root or root in resolved.parents`，越界即拒绝；
- 拒绝空路径与含 `\x00` 的路径。

防御覆盖：`../../etc/passwd`、`/etc/passwd`（绝对路径）、
软链接指向沙箱外的文件（resolve 会解析出真实目标）。`tools.py` 里
read 与 write 各绑一个沙箱实例，写/删的沙箱锁得比读更紧。

## 3. run_shell：白名单主力 + 黑名单拦变体（012 练习 1 的系统化）

`permissions.check_shell()` 三连检：

```
1. 黑名单：rm/sudo/mkfs/dd/重定向到根/管道接 sh/curl/wsgt 出网/
   $(命令替换)/链式 ; && |/敏感路径（.env、.ssh、id_rsa、/etc/shadow）
2. 白名单：首命令 ∈ {ls pwd cat grep wc head tail du df echo}
3. 参数级：不允许指向沙箱外的绝对路径
```

为什么两道都要（呼应 012 练习 1 的解析）：

- 只靠黑名单：`rm -fr`、`/bin/rm`、`echo x | sh` 等变体防不完；
- 只靠白名单：误伤时只能整体放行，且"白名单命令的危险参数"管不住；
- `shell=False`：命令按空格拆分直接 exec，`;` `|` `$( )` 不被解释，
  天然防注入——注意黑名单里的"链式字符"检测是在拆分**前**做的，
  因为 shell=False 下它们会变成字面量参数，留着只会造成语义混乱，直接拒；
- 超时 10s：`cat /dev/zero` 这类挂死命令不至于拖垮整个循环。

拒绝一律**返回字符串**（`REJECTED: …`）而不是抛异常——回填给 LLM，
它会自己换命令重试（012 课的反思机制）。

## 4. 与 012 练习 1 的差异：从"一个函数"到"一层策略"

012 练习 1 把双防线写在一个 `run_shell` 函数里；本课把它拆成两层：

```
策略层（permissions.py）  与具体工具实现无关，可配置、可审计、可替换
物理层（tools.py）        工具内部最后的保险丝：路径沙箱 + shell=False + 超时
```

这样"裸 Agent 对照实验"才做得出来：`BareAgent` 抽掉策略层，只留物理层
（演示环境甚至把危险命令改成模拟执行）——`scripts/01_attack_demo.py` 场景 B
里 `rm -rf /` 对裸 Agent"到达执行边界"、对加固 Agent 被黑名单拒绝，
两者的差异清晰可断言。

## 思考题

1. 为什么 delete_file 不在工具内部直接调用 input() 确认，而要单独抽一个
   approval 层（`sec/approval.py`）？
2. 白名单里有 `echo`，模型可以让 `echo $OPENAI_API_KEY` 泄密吗？
   现有防线拦得住吗？

### 参考答案

1. 三个原因：(a) Web/队列场景下没有人守着 tty，`input()` 会直接 EOF——
   审批必须支持 CLI 与 HTTP 两种通道（docs/04）；(b) 审批是**流程**不是
   **交互**：要生成 pending 记录、可被审计、可超时过期，塞进工具函数里
   这些都没了；(c) 策略可配置——strict 策略下连审批都不需要（直接拒），
   把判断留在策略层，工具只管做事。
2. 拦得住。`check_shell` 的黑名单含 `substitution`（`$\(`、反引号）与
   `sensitive_path`（`.env`），而环境变量不会被 subprocess 继承为可打印
   内容之外的东西——但真正兜底的是：`echo $OPENAI_API_KEY` 中的 `$` 直接
   命中黑名单被拒。这条题的考点是"白名单命令 ≠ 白名单参数"，
   所以三连检缺一不可。

*上一课：[02 提示注入与内容隔离](02-prompt-injection.md) | 下一课：[04 人工审批（human-in-the-loop）](04-human-in-the-loop.md)*
