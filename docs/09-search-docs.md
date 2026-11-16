# Problem 9：公司文档检索（search_docs）

## 1. 任务与我们确认的方案

实现 run_build_doc_index、run_search_docs、run_read_doc，并替换第八题两个文档工具的占位。搜索提供短证据和来源位置，阅读提供原文行窗口，不能一次返回整篇长文档。

确认采用 Markdown 标题/段落结构分块、统一 BM25 索引，分类仅作元数据，不增加问题分类 LLM 调用。HR/财务/工程/产品分类按文件 ID 前缀作启发式标记，不匹配则 general；它不是访问权限边界或真实组织分类，不会硬性排除其他文档。

片段保留 doc_id、title、category、section、start_line、end_line。日期不猜测，保留在原文供模型核对。政策问题提醒 Agent 检查后续公告、明确生效时间和替代关系，不仅看文件名。来源 ID 和行号使用户能够回原文核查，但不等同于已验证模型回答的全部事实。

## 2. 索引与片段

- 遍历 splitlines(keepends=True)，用累计字符偏移定位原文。
- 遇 Markdown 标题先结束前块，再更新 section；不跨章节混合。
- 块目标最多约 2000 字符，空段落边界在已有约 800 字符时优先结束。
- 单个超长段落在索引中按词继续拆分，保留偏移和所属章节；原文阅读不拆行。
- 复用第三题 BM25，索引块正文，不加入重复标题影响单词匹配。当前语料小，搜索可排序所有命中块，再按位置去重取 k 条。
- 找到块内首次命中的查询词，从原文附近提取最多 600 字符（课程计数最多 150 tokens），尽量在空白处切边，保留原文连续内容。
- 行号根据最终 strip 后片段实际覆盖位置计算；相同 doc_id/字符范围不重复返回，不同章节可来自同一文档。

题目要求片段与原文至少连续四词一致，当前语料测试全部覆盖。极短或单词本身超过片段字符上限的任意外部文档不能保证同样性质，本实现遵循课程语料和固定计数器。

## 3. 按行阅读

read(doc_id, start_line=1) 用 text.splitlines()，行号从 1 开始；按完整行添加，通常最多约 800 tokens，第一行超过该目标但不超过 1500 时允许单独返回。硬上限 1500 tokens，未知 ID/非法起始行报错。返回原文行连接的 text，以及起止行和总行数，下一次从 end_line+1 继续无缺口。

单行本身超过 1500 tokens 时，完整行和硬上限无法同时满足，当前明确报错，不假造窗口。本课程文档没有这种输入。窗口可能在行边界而非完整章节结束，定位准确优先于保持整章。

## 4. 工具接线和懒加载

cardinal_tools._documents() 按 DOCS_DIR 路径缓存 DocumentIndex，以已有锁保护首次创建。创建会话不读取文档，search_docs/read_doc 第一次调用时共享初始化。工具返回紧凑 JSON，包含定位字段，不重复返回块全文；无匹配返回 []。完整原文按需读取。

read_doc 的描述要求模型尽量引用来源 ID 和行号，避免无必要重复读；这属于模型行为提示，不是强制引用校验。6000 tokens 对话总预算目前由短输出和 prompt 控制，实际 live 测试检查是否满足，本题不引入事后截断。

## 5. 本次发现的连接问题

首次真实问答 2/20，大多数模型输出 DSML 而不是第六题的标签。原循环将这些文本当作普通答案提前结束，并非先证明检索失败。

因此在第七题无调用分支增加：同时出现 DSML 和 invoke 的回复按不支持协议反馈，不执行，并消耗既有连续错误/回合/token 预算，要求改写为既定 ASCII JSON 标签。没有新增 DSML 解析或绕过注册表。这个检测是保守启发式，普通引用若含这两个标记也可能被误判；后续可在有需求时进一步讨论。

第二轮 20/20，输出上限通过。补充结构测试还发现末尾换行导致 end_line 多算一行，已修正。失败和成功轮全部保留；变化不单归因于分块或分类，不能声称分类令准确率提高。

## 6. 完整文档索引实现

```python
"""Structural Markdown chunks with original source positions and bounded reads."""
import re

from cardinal_agent.pipelines.bm25 import BM25Index
from cardinal_agent.tokenizer import tokenize
from cardinal_agent.tokens import count_tokens


def category(doc_id):
    groups = {
        'hr': ('people', 'parental', 'pto', 'benefits', 'employee', 'remote', 'onboarding'),
        'finance': ('expense', 'finance'),
        'engineering': ('engineering', 'firmware', 'architecture', 'oncall', 'it-security'),
        'product': ('gridlens', 'project'),
    }
    return next((name for name, prefixes in groups.items() if doc_id.startswith(prefixes)), 'general')


class DocumentIndex:
    def __init__(self, docs):
        self.docs = {d['doc_id']: dict(d) for d in docs}
        self.chunks = []
        for doc in docs:
            lines = doc['text'].splitlines(keepends=True)
            section = doc['title']
            start = offset = 0
            block = []

            def flush():
                if block:
                    self.chunks.append({'doc_id': doc['doc_id'], 'section': section,
                                        'offset': start, 'text': ''.join(block)})
                    block.clear()

            for line in lines:
                heading = re.match(r'^#{1,6}\s+(.+)', line)
                if heading:
                    flush()
                    section = heading.group(1).strip()
                if block and (sum(map(len, block)) + len(line) > 2000):
                    flush()
                if not block:
                    start = offset
                # Long paragraphs are split only in the retrieval index;
                # read() always preserves whole original lines.
                if len(line) > 2000:
                    flush()
                    for match in re.finditer(r'\S+(?:\s+|$)', line):
                        if block and sum(map(len, block)) + len(match.group()) > 2000:
                            flush()
                        if not block:
                            start = offset + match.start()
                        block.append(match.group())
                else:
                    block.append(line)
                offset += len(line)
                if not line.strip() and sum(map(len, block)) >= 800:
                    flush()
            flush()
        self.bm25 = BM25Index([c['text'] for c in self.chunks])

    def search(self, query, k=5):
        terms = set(tokenize(query))
        results = []
        if k <= 0:
            return results
        seen = set()
        for i, _ in self.bm25.search(query, len(self.chunks)):
            chunk = self.chunks[i]
            doc = self.docs[chunk['doc_id']]
            text = doc['text']
            hit = next((m for m in re.finditer(r'[a-z0-9]+', chunk['text'].lower()) if m.group() in terms), None)
            anchor = chunk['offset'] + (hit.start() if hit else 0)
            # Quote a contiguous original passage around the matching term.
            begin = max(0, anchor - 100)
            if begin:
                boundary = re.search(r'\s', text[begin:anchor])
                begin = begin + boundary.end() if boundary else anchor
            end = min(len(text), begin + 600)
            if end < len(text):
                boundary = text.rfind(' ', anchor, end)
                if boundary > anchor:
                    end = boundary
            raw = text[begin:end]
            begin += len(raw) - len(raw.lstrip())
            snippet = raw.strip()
            end = begin + len(snippet)
            start_line = text.count('\n', 0, begin) + 1
            end_line = text.count('\n', 0, max(begin, end - 1)) + 1
            position = (doc['doc_id'], begin, end)
            if position in seen:
                continue
            seen.add(position)
            results.append({'doc_id': doc['doc_id'], 'title': doc['title'], 'snippet': snippet,
                            'category': category(doc['doc_id']), 'section': chunk['section'],
                            'start_line': start_line, 'end_line': end_line})
            if len(results) >= k:
                break
        return results

    def read(self, doc_id, start_line=1):
        if doc_id not in self.docs:
            raise LookupError(f'Unknown document: {doc_id}')
        lines = self.docs[doc_id]['text'].splitlines()
        if not 1 <= start_line <= len(lines):
            raise ValueError('start_line outside document')
        chosen = []
        for line in lines[start_line - 1:]:
            candidate = '\n'.join(chosen + [line])
            if count_tokens(candidate) > 1500:
                break
            if chosen and count_tokens(candidate) > 800:
                break
            chosen.append(line)
            if count_tokens(candidate) >= 800:
                break
        if not chosen:
            raise ValueError('A single source line exceeds the 1500-token window')
        return {'doc_id': doc_id, 'start_line': start_line, 'end_line': start_line + len(chosen) - 1,
                'total_lines': len(lines), 'text': '\n'.join(chosen)}

```

三个 adapter 分别转发 DocumentIndex(docs)、index.search(query,k)、index.read(doc_id,start_line)。agent/cardinal_tools.py 注册两个文档工具，其他工具功能不变；agent/session.py 仅增加上文不支持协议的恢复分支。

## 7. 测试记录

最终离线回归 **304 项通过**，8 项 live 未执行，pytest 耗时 5.84 秒；本题课程确定性测试 36 项。最终真实模型 deepseek-flash **20/20 正确**，文档结果每段对话最多 **2880 tokens**、平均 **1219 tokens**（报告取整），全部低于 6000；pytest 耗时 8.82 秒，缓存状态见该轮 metadata，不能作为纯 API 延迟。最初 2/20 到后续 20/20 增加 90 个百分点，但包含协议恢复修复，不能归因于结构分块。课程离线测试检查 24 份文档的搜索形状、原文片段、独有词、稳定性、阅读窗口、连续覆盖及错误行号。补充测试覆盖长段落后部关键词定位、章节分类和原文行号、搜索与阅读共享懒加载，以及 DSML 恢复。

完整记录位于 docs/evaluations/*-search-docs/，真实模型轮次位于 20261116-105131-search-docs/live、live-attempt-02、live-final。包含命令、依赖、实现哈希/快照、原始输出、JUnit、预测、完整会话、模型配置及费用账本。不同轮次不要混作同一版本；最终成功记录的指标在验证结束后汇总。

公开问答按可接受答案字符串核对，不是逐条人工审查所有陈述。模型可能直接利用搜索片段答题，未必调用 read_doc。token 是课程每四字符近似计数，不是 provider 精确 tokenizer；冷/热缓存和 API 延迟分开解释。

## 8. 手写与局限

先实现行窗口并验证不跳行，再用简单块接 BM25，最后完善结构块、命中片段、元数据和工具接线。不要因摘要方便改写 read_doc 原文。

当前支持普通 Markdown 标题，不是完整 Markdown AST，代码围栏中的伪标题可能被识别；类别为文件名前缀推断而非内容分类；路径缓存不支持原地文件热更新；没有多轮上下文压缩。提示注入由 prompt 边界约束，完整对抗测试留到第十四题。没有检索性能对照实验，不宣称结构分块、分类或懒加载有量化速度提升。
