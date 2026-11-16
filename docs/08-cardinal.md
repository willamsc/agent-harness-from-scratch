# 实现笔记 8：组装 Cardinal 工具集（cardinal）

## 1. 题目与前面各题的关系

业务流水线 实现业务函数，第五题提供注册/验证/执行，第六题提供调用协议，第七题提供循环。本题把业务函数和默认工具定义连接，让 run_agent_session(lm, None, config) 创建可使用业务工具的 Agent，而不是重写流水线或注册表。

工具的名字、参数 Schema、read_only 由课程 cardinal.py 固定，通过 cardinal_spec(name, description, fn) 绑定说明和真实函数。Schema 是使用说明，fn 才是实际能力。

## 2. 已确认方案

新增 agent/cardinal_tools.py，提供 build_cardinal_tools(lm, config)。tools=None 时组装十个工具；显式传入列表则只按配置补充 ask_user、remember、recall，不重复添加同名工具，也不改变调用方列表。

当前完成的四个邮件工具：

| 工具 | 绑定实现 | 给模型的返回值 |
| --- | --- | --- |
| search_emails(query, k=5) | 第三题 BM25，文档下标映射回邮件 | JSON 列表：id、date、subject、最多 400 字符正文 snippet、是否截断 |
| read_email(email_id) | ID 查找表 | 完整邮件 JSON；未知 ID 抛 LookupError，由注册表转 tool_error |
| email_qa(question) | 第四题流水线 | JSON：answer、support；内部搜索使用完整邮件 |
| daily_digest(date) | data.emails_on(date) + 第二题流水线 | 直接返回摘要字符串 |

默认十工具还包括 search_docs、read_doc、run_terminal、remember、recall、ask_user。按讨论先注册占位，说明不可用，调用抛 NotImplementedError，由注册表转为 tool_error，不伪装成功。后续逐题替换。本题不执行终端，也不写记忆文件或接通用户交互。

## 3. 延迟加载及共享

创建工具和会话都不读取邮件。首次调用需要邮件的 read_email/search_emails/email_qa 时才初始化档案缓存；搜索才建立索引。日报使用课程提供的按日加载函数，该函数自身缓存档案；不为日报额外建立 BM25。

模块级 _ARCHIVES 按 data.EMAILS_PATH.resolve() 缓存 emails、by_id、index。使用 RLock 串行保护加载及索引初始化，避免多个线程重复创建；初始化完成后搜索只读索引。加载或构建失败时不会留下已完成索引的假象，可在后续调用重试。

缓存以路径区分语料，但不检测同一路径文件内容被原地替换；本题假设进程内档案稳定。长期运行服务如需热更新，应另行设计失效策略。多个不同路径缓存会留在内存中，当前没有淘汰策略。

## 4. 辅助模型

aux_lm = config.aux_lm if config.aux_lm is not None else lm。

工具内部 email_qa、daily_digest 使用 aux_lm；Agent 自身循环仍用 lm。关键词提取、证据判断和邮件分类都属于流水线内部调用，不应消耗 Agent ScriptedLM 的预设回复。

## 5. 一个调用例子

用户要求搜索 Heron 审批邮件 → Agent 输出 search_emails(query="Heron approval", k=5) → 注册表验证 → 包装函数按需加载档案并复用/构建索引 → BM25 返回下标 → 转换成邮件 ID、主题、片段 JSON → 第七题把结果反馈给模型。

需要更多内容时，模型用 read_email(email_id) 获取原文。内部第四题 search 回调直接返回完整邮件，不把片段当作全部证据。

## 6. 完整实现

```python
"""Bind fixed Cardinal schemas to lazy email workflows and future tools."""

import json
from threading import RLock

from cardinal_agent import data
from cardinal_agent.cardinal import CARDINAL_TOOLS, cardinal_spec
from cardinal_agent.pipelines.bm25 import BM25Index


_LOCK = RLock()
_ARCHIVES: dict = {}


def _archive(needs_index=False):
    # Key by source path so distinct archives never reuse another file's index.
    key = data.EMAILS_PATH.resolve()
    with _LOCK:
        if key not in _ARCHIVES:
            emails = data.load_emails()
            _ARCHIVES[key] = {"emails": emails, "by_id": {e["id"]: e for e in emails}, "index": None}
        archive = _ARCHIVES[key]
        if needs_index and archive["index"] is None:
            archive["index"] = BM25Index([data.email_text(e) for e in archive["emails"]])
        return archive


def _pending(name):
    def unavailable(**kwargs):
        raise NotImplementedError(f"{name} is registered but not implemented yet; it is completed in a later problem.")
    return cardinal_spec(name, "Not available yet; registered for a later problem. Do not call this tool.", unavailable)


def build_cardinal_tools(lm, config):
    """Construct specs without loading data or building an index."""
    aux_lm = config.aux_lm if config.aux_lm is not None else lm

    def search(query, k=5):
        archive = _archive(needs_index=True)
        return [archive["emails"][i] for i, _ in archive["index"].search(query, k)]

    def search_emails(query, k=5):
        return json.dumps([
            {"id": e["id"], "date": e["date"], "subject": e["subject"],
             "snippet": e["body"][:400], "snippet_truncated": len(e["body"]) > 400}
            for e in search(query, k)
        ], ensure_ascii=False)

    def read_email(email_id):
        email = _archive()["by_id"].get(email_id)
        if email is None:
            raise LookupError(f"Unknown email ID: {email_id}")
        return json.dumps(email, ensure_ascii=False)

    def email_qa(question):
        from cardinal_agent.adapters import run_email_qa
        return json.dumps(run_email_qa(question, search, aux_lm), ensure_ascii=False)

    def daily_digest(date):
        from cardinal_agent.adapters import run_daily_digest
        return run_daily_digest(data.emails_on(date), aux_lm)

    available = {
        "search_emails": cardinal_spec("search_emails", "Search the 2001 email archive by BM25 keywords. Returns JSON email IDs, dates, subjects and up to 400 body characters; use read_email for full evidence. No matches returns [].", search_emails),
        "read_email": cardinal_spec("read_email", "Read one complete archive email as JSON by its ID from search results; unknown IDs return a tool error.", read_email),
        "email_qa": cardinal_spec("email_qa", "Answer a factual question over the email archive with up to three retrieval hops. Returns JSON answer and supporting email IDs; null means no supported answer found.", email_qa),
        "daily_digest": cardinal_spec("daily_digest", "Generate an English digest for one UTC archive date YYYY-MM-DD. Classifies that day's emails concurrently, omits ignore mail and summarizes urgent threads first in at most 300 words.", daily_digest),
    }
    return [available[name] if name in available else _pending(name) for name in CARDINAL_TOOLS]


def supplement_tools(tools, config):
    """Explicit lists gain only configured interaction/memory tools, once."""
    result = list(tools)
    names = {tool.name for tool in result}
    required = (["ask_user"] if config.user is not None else [])
    if config.memory_dir is not None:
        required.extend(["remember", "recall"])
    for name in required:
        if name not in names:
            result.append(_pending(name))
            names.add(name)
    return result

```

第七题构造函数新增接线，其他循环逻辑保持原样：

```python
from cardinal_agent.agent.cardinal_tools import build_cardinal_tools, supplement_tools

tools = build_cardinal_tools(lm, config) if tools is None else supplement_tools(tools, config)
```

## 7. 验证及记录

课程本题 **5 项通过**，另有 3 项接线补充测试；与此前已完成题目和 local_tests 合计 **265 项通过**，7 项 live 未执行，pytest 耗时 5.32 秒。真实 API 调用 0，费用 0。

[原始测试与环境记录](evaluations/20261116-103925-cardinal/)保存完整命令、代码版本、文件哈希、环境、JUnit、原始输出、session 差异及新增模块快照。

接线补充测试用小型可控档案验证：

- 创建会话时 load=0、build=0。
- 首次 read_email 后 load=1、build=0。
- 另一个会话的 8 个并发搜索结束后 load=1、build=1，说明同路径共享初始化。
- 搜索返回最多 400 字符正文并标注截断，无匹配为 []，未知 ID 为 tool_error。
- 工作流收到的是 aux_lm，并获取完整邮件，而非摘要片段。
- 显式列表已有 ask_user 时保留原实现、不重复注册，仅补配置要求的记忆占位。

这些是脚本断言的初始化次数，不是生产环境提速倍数。没有串行/无缓存性能对照，不能声称延迟降低多少。基准测试只检查组装契约；尚未完成工具不能算作已有业务能力。

## 8. 手写参考与限制

先将一个 search_emails 包装函数接到注册表，确认能由 query/k 转换到已有 BM25；再补按 ID 读邮件，最后接两个辅助模型流水线。延迟加载必须放到调用路径里，不能在创建工具时提前读取数据。

默认工具中只有四个邮件工具可用。read_email 目前返回完整正文，可能很大；搜索片段是正文开头而非查询相关片段，可能漏掉命中位置。上下文裁剪属于后续压缩与观察策略。config.user 仅触发工具注册，本题不代表已经实现审批和 steering。固定 Schema 对日期只验证外形，不保证它是合法日历日期。
