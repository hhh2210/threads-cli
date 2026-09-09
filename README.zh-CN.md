# threads-cli

**搜索 Threads，精确筛选，保留证据。**

[English](README.md) · [简体中文](README.zh-CN.md) · [MIT 许可证](LICENSE)

![杂乱的对话卡片经过终端，整理成可追溯的证据](docs/assets/launch.png)

一个非官方 Threads CLI：搜索帖子，查看回复与个人主页，在本地做严格过滤，
将带原文链接的证据导出为 JSON。通过浏览器桥接，还支持账号通知和显式文字发布。

**当前使用条件：** 登录态命令依赖 **Codex Desktop 中已有的 Dia 浏览器连接**及其
可信 Node 运行环境。仅安装 CLI 不会建立浏览器连接。离线命令和有限的匿名公共页面
模式可直接在终端运行；其他浏览器环境尚未验证。

## 解决什么问题？

Threads 搜索是模糊的：输入两个词，不代表每条结果都包含这两个词。
`threads-cli` 在搜索之后增加一层确定性的本地处理：

- **严格筛选：** 必含词、排除词、时间范围、回复数量上限。
- **保留出处：** 原文、作者、链接、时间戳和采集状态。
- **重复利用：** SQLite 分页保存、JSON 导出和离线查看。
- **明确覆盖范围：** 页数限制、部分结果标记、进程间共享的访问节奏。
- **显式发布：** 默认本地预览，发送前核对账号，用持久化发件记录防止盲目重复发送。

内置 CS2 找队友预设，展示多关键词采集、按证据判断和按作者去重的用法。
通用搜索可以用于其他主题。

## 安装

需要 Python **3.12+** 和 [uv](https://docs.astral.sh/uv/)。浏览器命令还需要
已连接浏览器提供的可信 Node 运行环境。

```sh
uv tool install 'git+https://github.com/hhh2210/threads-cli.git'
threads doctor --json
threads --help
```

Python 包名是 `larry-threads-cli`，命令名是 `threads`。
`doctor` 只检查本地环境和辅助模块路径，不代表已验证在线登录状态。

从源码安装：

```sh
git clone https://github.com/hhh2210/threads-cli.git
cd threads-cli
uv sync --locked
uv tool install --editable .
```

## 第一次登录态搜索

1. 在 Dia 中正常登录 Threads，将已有浏览器连接到 Codex Desktop。
2. 在可信 Node REPL 中，按连接提供的文档取得一个**本任务专用的 Threads 标签页**。
   先读取浏览器、确认机制和 CDP 文档。辅助模块会跳转此标签页，请使用没有未发草稿的页面。
3. 从 `threads doctor --json` 取得 `helper_path`，然后运行：

```js
// tab 是已有 Dia 连接中的任务专用标签页。
const { runBrowserCli } = await import("<threads doctor 返回的 helper_path>");
const result = await runBrowserCli(tab, [
  "search", "cs2 完美", "--sort", "recent", "--pages", "2", "--limit", "50",
  "--all", "cs2", "--all", "完美", "--exclude", "faceit", "--since", "14d"
]);
nodeRepl.write(result);
```

辅助模块默认调用 `~/.local/bin/threads`。如果安装到了其他位置，可用第三个参数
`{ executable: "/absolute/path/to/threads" }` 指定。运行环境发现方式见
[浏览器工作流](skills/threads-search/SKILL.md)。本仓库不附带独立浏览器驱动，
也不会创建浏览器、扩展、后台服务或公共端口。

`browser_connection_required` 表示需要接入该驱动，不是让你往终端粘贴 token。
认证留在浏览器内；CLI 不导出 Cookie，不读钥匙串，不收集密码，也不重放浏览器凭据。

### 搜索参数

| 参数 | 含义 |
| --- | --- |
| `--all TEXT`，可重复 | 本地结果必须包含每个词，匹配时做简繁规范化 |
| `--exclude TEXT`，可重复 | 排除包含任意指定词的结果 |
| `--since 14d` / `--since YYYY-MM-DD` | 按时间严格过滤，时间未知的结果不通过 |
| `--max-replies N` | 回复数不超过上限，数量未知的结果不通过 |
| `--sort top\|recent` | 选择平台提供的热门或最新搜索 |
| `--pages N` / `--limit N` | 限制采集页数 / 返回的不重复结果数 |

一整页可能先被缓存，再按输出数量截断。过滤只能处理平台已经返回的帖子，
无法补回上游搜索遗漏的内容。

## 查看和导出

```js
await runBrowserCli(tab, ["read", "https://www.threads.com/@user/post/shortcode"]);
await runBrowserCli(tab, ["user", "username"]);
```

以下本地命令不需要浏览器：

```sh
threads runs --json
threads candidates --include-review --json
threads export evidence.json
threads import evidence.json
```

数据默认保存在 `~/.local/share/threads-cli`。用 `--data-dir PATH` 或
`THREADS_CLI_HOME` 隔离不同数据集。导入接受规范化的 schema-v1 帖子证据，
不接受任意 HTML。证据库不会保存原始页面、请求头或原始 GraphQL 响应体。

有限的**匿名公共页面模式**：

```sh
threads --auth public search 'open source' --pages 1 --json
```

匿名结果可能遗漏登录后才能搜到的帖子，中文组合尤其可能受影响。
空结果不能证明没有匹配内容。

## 批量添加屏蔽词

将一整份词表导入 Threads「屏蔽词」里的**自定义过滤器**。修改的是账号实际生效的
设置，不只是 CLI 的本地搜索排除词。目前适配英文网页版的新过滤器界面；
旧版手机词库界面和其他网页语言尚未验证。

在 `words.txt` 中一行写一个词或短语，也支持英文逗号、中文逗号混合分隔。
短语内部的空格会保留。先在终端本地预览，不会修改账号：

```sh
threads hidden-words add --filter "关键词屏蔽" --file words.txt --json
```

通过已有浏览器连接，查看过滤器、核对哪些词需要追加，再保存：

```js
const options = { viewer: "your_handle" };
await runBrowserCli(tab, ["hidden-words", "list"], options);
await runBrowserCli(tab, ["hidden-words", "add", "--filter", "关键词屏蔽",
  "--file", "/absolute/path/words.txt", "--check"], options);
await runBrowserCli(tab, ["hidden-words", "add", "--filter", "关键词屏蔽",
  "--file", "/absolute/path/words.txt", "--apply"], options);
```

允许新建不存在的过滤器时，额外加 `--create`。新过滤器默认对所有人的帖子生效，
直到手动关闭。追加到已有过滤器时，保留其开关、作用范围、期限、描述和旧词。
重复输入和已有词会跳过。编辑器中每批添加 50 个词，最后只保存一次，
然后刷新回读完整词表；重复执行已经完成的导入会返回 `unchanged`。

输入限制、异常恢复和实测记录见[命令参考](docs/reference.md#bulk-hidden-words)。

## 通知和发布

在 `~/.local/share/threads-cli/config.toml` 配置预期的公开用户名：

```toml
viewer = "your_handle"
```

这是账号核对与联系记录设置，不是认证凭据。也可通过辅助模块第三个参数
`{ viewer: "your_handle" }` 指定。

```js
await runBrowserCli(tab, ["notifications", "--kind", "all", "--limit", "50"]);
await runBrowserCli(tab, ["inbox", "--limit", "50"]); // 收到的公开回复
```

先在本地预览帖子或回复：

```sh
threads --viewer your_handle post --text-file /absolute/path/post.txt
threads --viewer your_handle reply https://www.threads.com/@author/post/code \
  --text-file /absolute/path/reply.txt
```

确定要发布时，通过浏览器运行并显式加上 `--send`：

```js
await runBrowserCli(tab, ["reply", "https://www.threads.com/@author/post/code",
  "--text-file", "/absolute/path/reply.txt", "--send"]);
await runBrowserCli(tab, ["post", "--text-file", "/absolute/path/post.txt", "--send"]);
```

发件记录包含发送者、目标和精确文本。发送结果不确定时，应先只读核对，
不要自动重发。`inbox` 指收到的公开回复；私信走单独的 `dm` 命令，
当前仅支持**已有的一对一会话**。实验性写入能力的用法与边界见
[命令参考](docs/reference.md)。

## 哪些能力已经验证？

以下是 **2026-09-08/09** 在作者的 Dia/Codex 环境中的实测记录，
不代表其他环境的兼容性保证。

| 能力 | 状态 |
| --- | --- |
| 账号状态、分页搜索、帖子回复、个人主页 | 已实测；折叠回复可能缺失 |
| 批量屏蔽词 | 已实测：追加 54 个词、保留旧词、重复导入去重及新建过滤器 |
| 通知与收到的公开回复 | 已实测；只覆盖页面返回的有限窗口 |
| 公开文字回复 | 已发布，并回读核对作者、精确文本和永久链接 |
| 独立文字发帖 | 已检查编辑器；最终发布尚未在线实测 |
| 向已有会话发送私信 | 一次经授权测试已发送并回读确认 |
| CLI 撤回私信 | 实验性，尚未完成端到端验证 |
| 新建私信会话、附件、点赞、关注 | 尚未实现 |

`complete` 仅表示本次网页数据连接结束，**不代表搜遍整个 Threads**。
达到页数上限、部分返回、登录失败、限流和页面结构变化是不同结果。

## 开发

```sh
uv sync --locked
uv run pytest
uv run ruff check .
node --test tests/*.test.mjs
```

最近一次本地验证通过了 56 项 Python 测试、23 项 Node 测试及 Ruff。
反馈问题时，请提供命令、结构化错误码、运行环境和脱敏的最小示例。
欢迎参与浏览器兼容性、采集覆盖范围和可复现的发布验证。

## 许可证与致谢

[MIT](LICENSE)。非官方项目，与 Meta 无关联。

使用 [Click](https://github.com/pallets/click)、[Rich](https://github.com/Textualize/rich)、
[curl_cffi](https://github.com/lexiforest/curl_cffi)、Beautiful Soup 和
[OpenCC Python](https://github.com/yichen0831/opencc-python)。匿名公共页面方案参考了
[tamnd/threads-cli](https://github.com/tamnd/threads-cli)。
