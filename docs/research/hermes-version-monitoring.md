# Hermes Agent 版本监控渠道调研

> 调研日期：2026-09-01（Asia/Shanghai）
> 范围：只使用 Nous Research、GitHub、PyPI、Docker Hub 的一手页面、源码或 API；本次不修改业务代码。

## 结论

这里的 Hermes 应按 **Nous Research 的 [Hermes Agent](https://github.com/NousResearch/hermes-agent)** 理解，而不是 Hermes 模型系列：官方仓库把它定义为 AI agent，仓库 topics 同时包含 `ai-agent`、`claude-code`、`codex` 和 `hermes-agent`，产品首页是 [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/)。这与本仓库监控 AI 编码/Agent 工具的范围最吻合。

建议采用：

1. **主渠道：GitHub Releases REST 列表 API**
   `GET https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=10`
2. **备用渠道：GitHub Releases Atom**
   `GET https://github.com/NousResearch/hermes-agent/releases.atom`
3. **完整性审计：Git tags API 与 Releases 集合做差集**，只告警、不直接发版本通知。
4. **可选的分发状态：Docker Hub 同名 CalVer tag**，只用于确认镜像是否已就绪，不作为版本发现源。

不要把 PyPI、npm、官网文档或 `main/latest` 镜像作为版本主源。

## 为什么 GitHub Releases 是官方发布口径

官方 [release script](https://github.com/NousResearch/hermes-agent/blob/main/scripts/release.py) 的说明就是“生成 changelog，并用 CalVer tag 创建 GitHub Release”。它的实际顺序是：

1. 更新 `hermes_cli/__init__.py` 与 `pyproject.toml` 中的 SemVer；
2. 创建并 push annotated CalVer tag；
3. 调用 `gh release create ... --notes-file` 发布 Release 和正文。

官方 [更新文档](https://hermes-agent.nousresearch.com/docs/getting-started/updating) 也让用户把 `hermes --version` 与 GitHub Releases 页的最新版本比较。仓库根目录没有 `CHANGELOG.md`，因此不能复用 Claude Code/OpenClaw 的 CHANGELOG 抓取方式。

Hermes 同时维护两套版本标识：

- **CalVer tag**：例如 `v2026.8.31`；
- **产品 SemVer**：例如 `0.21.0`，出现在 Release title/body 和 [`hermes_cli/__init__.py`](https://github.com/NousResearch/hermes-agent/blob/v2026.8.31/hermes_cli/__init__.py)。

应以 `tag_name` 作为稳定事件键和详情 URL 的组成部分，同时从 Release title 提取 SemVer 用于展示。不要只用 SemVer 去重。

## 渠道评估

| 渠道 | 及时性 | 结构化/正文 | 可监控性 | 主要风险 | 建议 |
| --- | --- | --- | --- | --- | --- |
| [GitHub Releases REST 列表](https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=10) | 发布即出现 | JSON 字段完整；`body` 是 Markdown changelog | 最好；可分页、按 tag 取详情、支持条件请求 | 未认证有速率限制；正文可能发布后补充 | **主源** |
| [GitHub Releases Atom](https://github.com/NousResearch/hermes-agent/releases.atom) | 发布即出现 | 有 entry id/title/link/content/updated | 无 token，且本项目已有 Atom 解析经验 | 当前只保留最近 10 条；编辑正文也会改变 entry `updated` | **降级备用** |
| [Git tags API](https://api.github.com/repos/NousResearch/hermes-agent/tags?per_page=100) | 比 Release 相同或略早 | 只有 tag/commit，无 release notes | 易轮询 | 含内部备份/实验 tag；脚本先 push tag、后建 Release，可能提前误报 | 仅做审计 |
| [Docker Hub tags API](https://hub.docker.com/v2/repositories/nousresearch/hermes-agent/tags?page_size=100) | Release 后有构建延迟 | tag/digest/更新时间，无 changelog | JSON 可读 | `main`/`latest` 随主分支提交滚动；构建失败或延迟不能代表没有 Release | 可选“镜像就绪”状态 |
| [PyPI JSON](https://pypi.org/pypi/hermes-agent/json) | 已停止同步 | 结构化但无可靠 changelog | 容易轮询 | 严重漏版；官方已声明 PyPI 安装不受支持 | 不使用 |
| npm `hermes-agent` | 非官方 | 注册表结构化 | 容易轮询 | 包元数据指向第三方 `wyrtensi/hermes-agent-npm`，不能代表 Nous Research 发版 | 不使用 |
| 官网/docs、`main` HEAD | 持续滚动 | 无独立 release feed | 可抓但语义错误 | 会把未发版提交/文档更新当成版本 | 不使用 |

## 实测证据

截至调研时，[Releases 列表 API](https://api.github.com/repos/NousResearch/hermes-agent/releases?per_page=100) 返回 31 个 Releases：

- 最新为 [`v2026.8.31`](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.8.31)，title 是 `Hermes Agent v0.21.0 (v2026.8.31)`，`published_at` 为 `2026-08-31T19:29:49Z`；正文约 39,683 字符，`updated_at` 为 `2026-08-31T19:57:53Z`，说明发布后正文确实可能继续编辑。
- 31 个 Release 的 body 均非空，当前全为 `draft=false`、`prerelease=false`；即使如此，实现仍应显式过滤这两个字段。
- 当前 31 个 `v<数字>` 版本 tag 都有对应 Release；tags 列表另有 `backup/...`、`clean-before-remerge` 等内部 tag，所以“任意新 tag 即发通知”会误报。
- Atom 当前只有 10 个 entry，适合正常频率轮询，不能承担长时间停机后的完整历史追赶。

[PyPI JSON](https://pypi.org/pypi/hermes-agent/json) 的最新版本仍为 `0.19.0`，而官方 GitHub 已到 `0.21.0`；它缺少 `0.19.1`、全部 `0.20.x` 和 `0.21.0`。官方 [Platform Support](https://hermes-agent.nousresearch.com/docs/getting-started/platform-support) 明确把 PyPI 安装列为 unsupported，官方 [`setup.py`](https://github.com/NousResearch/hermes-agent/blob/main/setup.py) 也阻止常规 wheel/sdist 构建。

Docker Hub 的 `v2026.8.31` 在 `2026-08-31T19:35:17Z` 更新，比 GitHub Release 晚约 5 分半钟。官方 [Docker workflow](https://github.com/NousResearch/hermes-agent/blob/main/.github/workflows/docker.yml) 也显示：Release 事件发布同名 release tag，而 `main` push 发布 `main` 和 `latest`。因此它适合在通知上补充“镜像已就绪”，不适合决定“有没有新版本”。

## 推荐监控规则

### 主流程

每 30 分钟请求最近 10 条 Releases，而不是只请求 `/releases/latest`：

```text
GET /repos/NousResearch/hermes-agent/releases?per_page=10
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
If-None-Match: <上次 ETag，可选>
```

GitHub 的 [List releases API](https://docs.github.com/en/rest/releases/releases#list-releases) 返回 `tag_name`、`name`、`body`、`published_at`、`updated_at`、`draft`、`prerelease`、`html_url` 等字段；[条件请求](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api#use-conditional-requests-if-appropriate) 可用 ETag 降低重复请求成本。

处理建议：

1. 丢弃 `draft=true` 或 `prerelease=true` 的条目；
2. 按 `published_at` 升序处理所有未见过的 `tag_name`，避免两次轮询之间连续发布时只通知最后一版；
3. 保存 CalVer `tag_name` 为事件键；从 `name` 优先提取 `Hermes Agent v<semver>`；提取失败时仍可只用 tag 通知；
4. `body` 作为英文原文，`html_url` 作为版本链接；
5. 同时保存 `updated_at` 或正文 hash。已通知 tag 的 body 变化时，可沿用本项目现有“编辑之前通知”的能力，而不是重复发版；
6. 正常轮询取 10 条；首次运行、状态丢失或发现断档时分页拉全，直到遇到已知 tag；
7. API 暂时失败时切 Atom，不要在同一次检查中把“主源失败”当作“没有新版”。

使用列表接口优于只用 [`/releases/latest`](https://api.github.com/repos/NousResearch/hermes-agent/releases/latest)：后者只能返回一个 Release，如果 30 分钟内连发补丁版，就可能跳过中间版本。

### Atom 降级

Atom 可直接复用 Codex checker 的基本解析路径。去重应取 entry link/ID 中的 tag，不应只看 entry `updated`；因为修改 Release notes 也会更新 `updated`。恢复 REST 后再用列表 API 对账。

### 审计与告警

可以低频比较：

```text
version_tags = tags 中匹配 ^v\d 的集合
release_tags = releases 的 tag_name 集合
```

只在 `version_tags - release_tags` 持续存在一段宽限期后报内部告警。不要向公开频道发送，因为官方发布脚本天然存在“tag 已 push、Release 尚未创建”的短窗口。

## 风险结论

- **最低漏报风险**：GitHub Releases 列表 API + 分页追赶 + 已知 tag 集合。
- **最低依赖备用**：Atom，但停机跨过 10 个版本时会漏历史。
- **最高误报风险**：直接监控全部 Git tags，或监控 `main`/`latest` Docker digest。
- **最高漏报风险**：PyPI；它已不再是官方支持分发渠道。
- **正文更新风险**：Release notes 可在发布后编辑；状态中需要同时记录 tag 与 body hash/`updated_at`。

最终建议是复用 Codex 的“Atom + GitHub API 验证”思路，但把优先级倒过来：**REST Releases 列表为主、Atom 为灾备**。Hermes 的官方 Release 正文质量高，直接使用它比拼接 commits 或抓滚动文档更稳。
