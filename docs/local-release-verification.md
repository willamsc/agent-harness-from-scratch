# 本地预览版验证

版本 0.1.0。当前 Linux/Python 3.12 环境，实际结果记录于 [本次产品验证目录](evaluations/20261116-123641-local-product/)。尚未验证 Windows/macOS。

- 完整离线回归 **379 项通过**，13 个 live 未执行，pytest 耗时 6.90 秒。
- 新增 6 个 CLI 测试：初始化与真实离线检索、邮件输入校验和原子替换、UTC 归一化、文档覆盖/行长检查、记忆删除/历史路径校验、默认无终端且失败后保存会话。
- 发布白名单测试排除 .env/.env.local、凭据、运行目录、私有 profile、完整评估邮件档案等，保留公开源码、虚构 demo 和已归档评测资料。
- 在 /tmp 新虚拟环境安装 wheel，依赖重新解析，独立于开发虚拟环境；从 /tmp 启动，模块实际来自安装环境 site-packages。
- 安装后执行 --version、init --demo、demo、doctor、history；离线检索找到真实内置文档的 Morgan Lee，未使用假模型生成答案。
- 安装后的真实问答使用 deepseek-flash，正确回答 Aurora owner 并给出文档 ID/章节/行号，完整会话和新增费用账本单独保存。只是一例连通性/安装验证，不作为新的任务成功率样本。

wheel 安装的宽版本依赖与源码 uv.lock 固定版本不同，因此 installed-dependencies.json 单独保存。不能拿开发环境测试替代安装环境验证。

后续 code.zip 以明确 Git commit 导出，ZIP 解压与重新安装的验证记录在同目录的 release-artifact-verification.json（构建后生成）。源码 ZIP 的 commit 和 SHA256SUMS/manifest 是对应关系依据，不是任意当前工作区的快照。

实际 GitHub Release 是否存在，以远程页面和 CI 运行结果为准；本地构建成功不代表已经上传。工作流尚未在 GitHub 执行时不能说 CI 已通过。
