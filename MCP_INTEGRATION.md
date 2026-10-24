# MCP 接入说明（MCP_INTEGRATION）

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| MCP Server | 麦当劳中国官方 MCP（`mcd-mcp`） |
| 端点 | `https://mcp.mcd.cn`（streamable-http，POST，单次请求响应） |
| 鉴权 | `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| Token 获取 | https://open.mcd.cn/mcp — 手机号登录 → 控制台 → 激活 → 领取（免费） |
| 官方文档 | https://github.com/M-China/mcd-mcp-server |

> 注意：`https://open.mcd.cn/mcp` 是**网页控制台**，不是 MCP 端点，直接 POST 会返回 405。
> 正确的 MCP 端点是不带路径的 `https://mcp.mcd.cn`。

配置示例见 [`mcp-config.example.json`](./mcp-config.example.json)，只保留环境变量占位符，不含任何真实凭据。

## 2. 实际调用的 Tool

| Tool | 在本项目中的作用 |
|---|---|
| `query-nearby-stores` | 按城市 + 位置关键词定位门店，拿到 `storeCode`（以及得来速场景下的 `beCode`） |
| `query-meals` | 拉取指定门店**当前时段**的实时菜单，得到商品 code、名称、现价/原价 |
| `query-meal-detail` | **核心**。展开一个套餐的全部槽位（`rounds`）与每个槽位的可选子项（`choices`，含 `isDefault`、`diffPrice`） |
| `calculate-price` | **核心**。对候选组合真实算价，返回到手价 `price`、原价 `originalPrice`、优惠 `discount`（单位：分） |
| `query-my-coupons` | （可选）展示卡包内已有券，提示还有哪些优惠没用上 |

本项目只做**只读查询与算价**，不调用 `create-order` / `auto-bind-coupons` 等会产生实际副作用的 Tool。

## 3. 调用流程

```
用户："想吃 吉士蛋麦满分 + 咖啡 + 薯饼"
        │
        ▼
[1] query-nearby-stores(beType=1, searchType=2, city, keyword)
        │  → storeCode
        ▼
[2] query-meals(storeCode, orderType=1, beType=1)
        │  → 当前时段菜单 {code: {name, currentPrice, originalPrice}}
        ▼
[3] 心愿模糊匹配（名称包含 / 编辑距离打分）
        │  → 每个心愿的候选：可单点商品 + 套餐内可选子项
        ▼
[4] query-meal-detail(每个套餐, code=...)
        │  → rounds[] → choices[]（槽位可选项，多数替换 +¥0）
        ▼
[5] 枚举方案
        ├─ 方案 A：全单点（基线）
        └─ 方案 B…：套餐覆盖（槽位优先选命中心愿的子项，未命中的回落 isDefault）
                     + 未被覆盖的心愿单点补齐
        ▼
[6] calculate-price(每个方案)  ← 真实算价，不靠菜单价推算
        │  items[].roundList 指定套餐各槽位选中的子项 code
        ▼
[7] 按到手价排序 → 输出最省方案 + 相对全单点省了多少
```

关键点：`calculate-price` 支持 `roundList`，因此可以**指定套餐内部每个槽位选什么**再算价，
这使得"套餐能否覆盖我的心愿"这件事可以被精确验证，而不是靠菜名猜。

## 4. 业务价值

1. **对用户**：把"我想吃 A 和 B"直接翻译成最便宜的下单方式，省的是真金白银。
   实测样例（唐山华北理工大学餐厅，早餐时段）：
   - 心愿「吉士蛋麦满分 + 咖啡」：全单点 ¥20.0 → 套餐流 ¥12.0，**省 ¥8.0（40%）**
   - 心愿「吉士蛋麦满分 + 咖啡 + 薯饼」：全单点 ¥28.0 → 套餐流 ¥17.5，**省 ¥10.5（37.5%）**
2. **对麦当劳 MCP 生态**：示范了一种"反向选品"的用法——不从预算出发，而从用户的心愿出发，
   用套餐槽位的可替换性做组合优化，把 MCP 的查询能力变成了决策能力。
3. **对开发者**：纯标准库实现（无第三方依赖），全流程只读，可作为把 MCP 接到组合优化类场景的最小参考实现。

## 5. 局限

- 菜单随时段变化（早餐 / 正餐 / 夜市），结果以调用时刻的实时数据为准。
- 菜单中套餐展示的 `currentPrice` 可能含"随单购早餐卡"等门槛优惠，真实到手价一律以 `calculate-price` 为准。
- 优惠券的自动择优尚未纳入（v1 只算不用券的到手价），是后续迭代方向。
