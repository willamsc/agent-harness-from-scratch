# 本地使用指南

## 安装与初始化

Release wheel 安装后运行 `cardinal`，也可在 source ZIP 中 `uv sync --locked` 后用 `uv run cardinal`。支持 Python 3.11+；源码运行同时支持 `python -m cardinal_agent`。预览版仅在当前 Linux 环境验证；Windows/macOS 还需实际安装与 sandbox 验证，不承诺完整跨平台等价。

```bash
cardinal init --demo --provider deepseek --model deepseek-flash
cardinal demo onboarding
export DEEPSEEK_API_KEY='your-key'
cardinal doctor
cardinal ask "Who owns the demo Aurora project? Cite your source."
cardinal chat
```

`demo` 只运行真实 BM25 检索，不生成假 LLM 回答；`doctor` 不调用模型，也不显示 key 的值。模型 key 通过环境变量提供；源码开发环境也会兼容原来的 `.env`，不打进 Release。

## Profile 与数据

`--home DIR` 必须放在子命令前。同一员工不同公司/项目可以使用不同目录，避免把不相关知识混在一个助手里：

```bash
cardinal --home ./work-assistant init
cardinal --home ./work-assistant import docs ./my-markdown
cardinal --home ./work-assistant import emails ./emails.jsonl
cardinal --home ./work-assistant chat
```

默认目录在 XDG_DATA_HOME/cardinal-agent 或 ~/.local/share/cardinal-agent，新 profile 以仅用户可进入的权限创建（POSIX）。不要选择共享目录或把自己的 profile 放进仓库。

```text
profile/
  config.json        非秘密设置：provider/model/累计费用上限
  data/docs/         导入的 Markdown
  data/emails.jsonl  导入的邮件
  memory/            持久记忆
  cache/             模型完整请求/回复缓存和费用账本
  conversations/     保存的会话
  workspace/         命令数据副本及输出文件
```

本地落盘不代表数据不出设备：模型服务会收到问题、选中的证据、记忆或摘要。公司资料需要事先确认服务商、权限与保存政策。当前仅单用户/单进程 profile，不支持多个进程并发修改同一个记忆库。

文档导入支持 UTF-8 `.md` 和目录递归扫描，保留文本与标题。文件路径归一化为文档 ID，碰撞拒绝；单文件不超过 10 MB、单行不超过 6000 字符。PDF、Word、附件和 OCR 暂不支持。已有文件不同内容需 `--replace`，导入后重启已有 chat。

邮件每行一个 JSON 对象，必须字段：

```json
{"id":"mail-001","from":"alice@example.test","to":["me@example.test"],"date":"2026-11-16T09:00:00Z","subject":"Review","body":"Please review this afternoon.","thread_id":"thread-001","reply_to":null}
```

ID 唯一；时间必须含时区，导入统一为 UTC。thread_id/reply_to 可省略，分别默认本邮件 ID/null。最大导入 100 MB。全部校验后原子替换邮件文件，异常不覆盖原档案；日期分组按 UTC 而非用户本地时区。不是直接接入 Outlook/Gmail，也不会自动发邮件。

## 对话、审批与终端

当前产品入口固定 confirm，默认不提供 run_terminal。`chat --terminal` 显式开启，并逐条审批；没有可用 OS jail 时拒绝开启，只有明白风险后才使用 `--allow-unisolated-terminal`。后者仅表示用户接受无 OS 隔离的风险，白名单和拒绝正则不会因此消失。

工具会主动提问澄清，不直接猜用户意图。CLI 是同步 REPL，运行命令时不能实时输入 steering。Ctrl-C 退出/中断交互并尽量保存记录，不等于完善的异步任务取消/恢复系统。

每轮即时保存完整会话，异常也保存错误类型；查看：

```bash
cardinal history
cardinal history --show CONVERSATION_ID
cardinal memory
cardinal memory --forget MEMORY_ID
```

单条记忆删除不会擦除旧对话、模型缓存或命令输出。需要完整删除时，关闭该 profile 的所有进程，再由用户自行备份/移除 profile；本版本没有承诺企业级删除传播。

## 费用与故障

默认每 profile 累计费用上限 $1；`configure --budget 5` 是提高累计上限，不重置账本，不是单次请求额度。`/status` 显示本会话模型用量。费用为封装账本估计，缓存状态会影响本次新增费用。

API key 缺失先 doctor；代理问题检查自己的网络环境，不在应用里偷偷清除代理。API 异常或预算停止会报告失败，不生成伪造答案；已完成动作可能有副作用，不能盲目重复。
