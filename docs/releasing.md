# 可验证发布流程

发布产物是源码与 Python 安装包，不是打包了模型的独立二进制。使用者仍需 Python、依赖下载和自己的 API key；离线 demo 不需要模型服务。

## 本地生成

在干净且已提交的 master checkout：

```bash
uv build --wheel --out-dir dist
uv run python tools/build_release.py
unzip -t dist/code.zip
cd dist && sha256sum --check SHA256SUMS
```

build_release 从 Git commit 导出白名单文件，不从任意工作目录收集文件。默认 HEAD；code.zip 使用固定 ZIP 元数据，SOURCE_MANIFEST.json 记录每个源码文件哈希及 commit。wheel 与 ZIP 哈希记录在 SHA256SUMS 和 release-manifest.json。

不包含 `.env`、本地 profile、缓存、运行日志目录、凭据、解压邮件或完整公共邮件压缩档案。docs/evaluations 中已经纳入版本控制的公开评测记录包含在源码 ZIP，不能混入真实企业数据。发布前仍需人工检查提交内容，构建脚本不能识别任意文本中的所有秘密。

wheel 包含应用代码和虚构 demo，独立于仓库 data/；code.zip 也包含开发测试和文档。复现全邮件评估需另取课程公开档案并按 data/source.json 校验，不能误认为 source ZIP 自带完整 benchmark 数据。

## GitHub Release

工作流 `.github/workflows/release.yml` 在推送 v* tag 时触发，验证 tag 版本与 pyproject 一致且源码位于 master 历史，运行离线测试、构建、校验，并在 checkout 外的新虚拟环境安装验证 CLI，然后发布 preview Release。

先推送 master，再在确认的提交上创建 tag：

```bash
git switch master
git push origin master
git tag v0.1.1
git push origin v0.1.1
```

main 保留给个人手写版本，不需要合并或修改。默认分支即使是 main，tag 指向的 master 提交内也携带本工作流；具体运行仍受仓库 Actions 权限策略影响。

Actions 使用仓库自动提供的 GITHUB_TOKEN，不把个人 token 写进代码。Release 附件为 code.zip、wheel、SHA256SUMS、release-manifest.json。当前会话若没有 GitHub 凭据，只能生成本地产物，不能声称已经发布；需要用户在有认证的终端推送或通过 GitHub 页面手动创建 Release 并上传这些文件。

GitHub 页面提供的自动 Source code ZIP 不等同于这里的 code.zip，后者有明确文件清单和构建验证。ZIP 本身不是可信度证明，源码可读、来源真实、测试可复查和安装可复现才是依据。
