# 运行状态与查询

目标：无需初始化模型、输入 API key 或读取整个对话，即可知道任务进展及恢复条件。

```bash
cardinal runs list
cardinal runs show RUN_ID
cardinal runs show RUN_ID --trace
```

RUN_ID 为 profile/checkpoints 下文件名（与 CLI 会话 ID 一致）。参数只接受字母、数字和连字符，拒绝路径穿越。CLI 仍需存在已初始化的 profile。

`agent/runs.py` 从原子 checkpoint 读取快照，结合 `CheckpointStore.is_active()` 对 OS flock 的探测判断当前是否仍有进程持锁。不会根据 PID 或残留 lock 文件猜测进程存活；查询不调用模型、不修改 checkpoint。状态为查询时观察结果，执行可能在查询后立即推进。

| 状态 | 含义 |
| --- | --- |
| running | 发送/恢复操作持有锁，正在推进 |
| waiting_approval | 持锁且已持久化等待批准状态 |
| needs_reconciliation | 无活跃持锁进程，存在未确认工具调用 |
| interrupted | 无活跃进程，轮次未结束且没有未确认工具 |
| failed | 模型请求失败；保留未完成状态，可以恢复 |
| completed | 模型返回最终回复，不代表业务事实必然正确 |
| stopped | 达到轮次、token 或协议错误上限，任务未完成 |
| cancelled | 在边界处理了取消请求 |
| unreadable | 列表中的 checkpoint 无法读取或结构错误 |

工具是否成功与运行结束状态分开：某次 tool_error 后模型仍可能解释失败并正常结束。summary 给出调用/结果数、模型尝试次数、本地估算 token、最近活动、未确认工具名和 operation ID、是否可恢复及最近错误类型。默认不展示用户问题、工具参数、输出或异常消息；--trace 显式展开敏感事件。

实现代码：agent/runs.py、agent/checkpoint.py、app/cli.py。测试覆盖 API key 缺失时的 CLI 查询、失败与完成、损坏文件、敏感内容不出现在默认摘要、路径校验；真实子进程测试覆盖活跃锁和等待审批。

CLI 会话目前多轮共用一个 checkpoint，因此 summary 反映最近轮次状态，累计工具事件来自会话 transcript。不是多租户调度系统，不提供分布式集群状态或远程取消服务。
