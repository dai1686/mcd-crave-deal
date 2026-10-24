# workbuddy.md · 使用腾讯 WorkBuddy 开发 mcd-crave-deal 的对话上下文

> 本文件用于核验 WorkBuddy 联动活动奖励条件，记录本项目从 0 到可跑通的完整开发过程。
> 开发环境：腾讯 WorkBuddy 桌面版（Agent 模式）｜本机 MCP 连接器：`mcd-mcp`

---

## 一、需求起点

**用户（小代）**：华北理工大学信管专业大一学生。10-24 早上把桌面上「麦当劳设计比赛.WorkBuddy」
文件夹里的 `参赛要求 .doc` 和 `0.jpg` 丢给我，让我总结内容、查详细赛事规则。

**WorkBuddy 做的事**：
1. 解析 `.doc`（旧二进制格式，按 UTF-16LE 解码提取中文），读出比赛时间与参与方式；
2. 联网检索并从官方仓库 `M-China/mcd-developer-innovation-challenge` 拉取
   `README.md` / `activityGuidelines.md` / `RANKING.md` 原文，整理出完整规则；
3. 给出截止倒计时提醒（10-25 23:59）与进榜门槛（当时第 100 名约 42 Star）。

## 二、MCP 接入与排坑

**用户**：在 open.mcd.cn 激活后拿到 Token，问"接下来要干嘛"。

**WorkBuddy 做的事**：
1. 把 MCP 配置写入 `C:\Users\我会早起\.workbuddy\mcp.json`；
2. 用脚本直接 POST 探测端点，逐个试了 5 个候选地址，得到关键结论：
   - `https://open.mcd.cn/mcp` → **405**（那是网页控制台，不是 MCP 端点）
   - `https://mcp.mcd.cn` → **200**，返回 `tools/list`
   - 网上多篇文章说的"要改成 open.mcd.cn/mcp"是错的，官方 README 的 `mcp.mcd.cn` 才对
3. 调用 `tools/list` 拿到 **35 个工具**清单，并按能力分组讲给用户；
4. 用户问"mcd-mcp 在哪找"，WorkBuddy 拉取官方文档确认 UI 路径后给出三步指引。

## 三、创意方向

**用户**：选定方向——"麦麦自主选择想要吃的单品并匹配最优惠套餐"。

**WorkBuddy 给的差异化建议**：榜单上省钱/预算类已十几个，要做出差异，核心应落在
"**从心愿出发的反向选品 + 套餐槽位可替换性**"，而不是再做一个预算分配器。

## 四、数据结构调研（决定算法可行性的一步）

WorkBuddy 依次调用真实接口验证：
1. `query-nearby-stores` → 找到用户学校里的门店（唐山华北理工大学曹妃甸校区，storeCode 1980439）
2. `query-meals` → 拿到 69 个在售商品及价格
3. `query-meal-detail` → 第一次用 `productCode` 入参报 `code不得为空白`，**改用 `code` 后成功**，
   发现套餐的本质结构：`rounds[]`（槽位）→ `choices[]`（可选项，含 `isDefault`、`diffPrice`）
4. `calculate-price` → 验证单点与套餐两种算价：
   - 单点（麦满分 + 大杯咖啡）= **¥22.0**
   - 套餐（麦满分套餐，roundList 指定三个槽位）= **¥17.5**

到这一步，"套餐槽位可以指定 + 能真实算价"被证实，算法路线成立。

## 五、编码与调试

WorkBuddy 在 `D:\workbuddy_file\代码\mcd-crave-deal\scripts\` 下写出两个文件：
- `mcp_client.py`：仅用标准库的 MCP 客户端（Token 只从环境变量读）
- `crave.py`：心愿匹配 → 套餐槽位扫描 → 方案枚举 → 真实算价 → 排序输出

**三轮调试（每轮都是跑真实接口、看真实输出后修的）**：

| 轮次 | 现象 | 原因 | 修法 |
|---|---|---|---|
| 1 | 冒出 ¥0.0 的"最省方案" | 不可售组合算价返回 0 | 过滤 `price <= 0` |
| 2 | "全单点"基线里混进了「组合」 | 基线应只用可单点商品 | 匹配时排除名称含套餐/组合/三件套等的商品 |
| 3 | 套餐明明盖住了心愿，却还重复补单 | 覆盖判定时 `wish_codes/wish_names` 是**全局集合**，导致对每个心愿都打 92 分，索引恒为 0 | 改成**按心愿各自的** code/name 集合判定 |

修复后输出正确：

```
🎯 想吃：吉士蛋麦满分 + 咖啡
   ¥12.0   套餐流：吉士蛋麦满分组合  ✅
   ¥17.5   套餐流：吉士蛋麦满分套餐
   ¥20.0   全单点
🤑 比全单点省 ¥8.0（40.0%）
```

## 六、交付物（均由 WorkBuddy 生成）

| 文件 | 作用 |
|---|---|
| `SKILL.md` | WorkBuddy Skill 定义（触发词、参数、执行流程、边界） |
| `scripts/mcp_client.py` | MCP 客户端（标准库实现） |
| `scripts/crave.py` | 核心：心愿 → 最省组合 |
| `README.md` | 项目介绍 / 安装 / 示例 / 目标用户 |
| `MCP_INTEGRATION.md` | 用了哪些 MCP Server、Tool、调用流程、业务价值 |
| `CONTEST_DECLARATION.md` | 官方参赛声明原文（未改动一字） |
| `mcp-config.example.json` | 脱敏配置，仅 `${MCD_MCP_TOKEN}` 占位符 |
| `docs/index.html` | GitHub Pages 项目主页 |
| `.gitignore` | 排除凭据与中间产物 |

## 七、一句话总结

从"这比赛是啥"到"Skill 跑通、真实省下 40%"，全程在腾讯 WorkBuddy 内完成：
查规则 → 接 MCP → 排端点错 → 反推数据结构 → 写代码 → 跑真实数据三轮调试 → 出交付物。
