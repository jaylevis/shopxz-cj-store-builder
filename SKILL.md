---
name: shopxz-cj-store-builder
description: 用 CJ Dropshipping 真实可履约的商品为 ShopXZ/Fecify 日本 B2C 店搭建商品目录：选品门禁（发日本、库存、追踪、利润）、日文标题与文案由宿主 AI 改写、图片 WebP 与 AI 重拍、定价、生成 Fecify 导入文件与配送事实，再交给 fecify-site-manager-v6 走二段式导入、shopxz-japan-launch 做设置/条款/邮件/召回。用于申请 GMC 前的建店、站群复制与换品。
metadata:
  version: "0.1.0"
---

# ShopXZ × CJ 选品建店

目标：店里每一个商品从第一天起就能真实发货、价格含运费有利润、页面文案与条款和实际物流一致。这是 GMC 审核与过审后不被封的前提；不做占位商品。

## 依赖与边界

- CJ 凭据只从 `FECIFY_CJ_ENV` 或 `%LOCALAPPDATA%/Fecify/cj/cj.env`（`CJ_EMAIL`、`CJ_API_KEY`）读取，令牌缓存在同目录；不进 profile、不进仓库、不写在命令行。
- 店铺写入全部经 `fecify-site-manager-v6`：商品导入走其二段式门禁（报告 → 商家确认 → confirm 文件 → import-file），本技能不自制确认、不直接调创建 API。
- 文案由宿主 AI 按 `enrich-tasks` 的 schema 填写并经 `enrich-apply` 校验；不调用外部翻译服务。
- 图片：原图仅存档审计；上传用 WebP，`image_mode=ai-edit` 时用已配置的生图通道重拍（参考图编辑）。商品外观不得被改变成不存在的款式。
- 经营者信息、退货地址等法律事实不虚构；`policies.json` 只给出由 CJ 物流推导的发货与到货事实，供 shopxz-japan-launch 的 profile 使用。

## 流程

```text
python scripts/cjbuild.py auth
python scripts/cjbuild.py categories --filter "jewelry"
python scripts/cjbuild.py profile --out <run>/profile.json --categories "Necklaces,Earrings" --count 40 --brand "<店名>"
python scripts/cjbuild.py discover --profile <run>/profile.json --workdir <run>        # 只读，可续跑
python scripts/cjbuild.py select   --workdir <run> --count 40 [--pids a,b,c]
python scripts/cjbuild.py enrich-tasks --profile <run>/profile.json --workdir <run>   # 宿主 AI 填写 tasks[].output
python scripts/cjbuild.py enrich-apply --profile <run>/profile.json --workdir <run>
python scripts/cjbuild.py images   --profile <run>/profile.json --workdir <run> [--ai on|off]
python scripts/cjbuild.py export   --profile <run>/profile.json --workdir <run>
python scripts/cjbuild.py phase1   --workdir <run>        # 管理技能 schema-check/apply-rules/validate-data/report（只读）
```

`phase1` 产出 `fecify-phase1/products_report.md`；向商家完整展示，得到明确的「确认导入」后，按管理技能执行 `make-confirm.js <report.md>` 与 `import-file.js <products_products.ndjson> --image-root=<run>/fecify-import/images --confirm-file=<_confirm.json>`，再 `verify-import.js` 回读。导入后：专辑与菜单（管理技能）、条款与后台设置、邮件、召回（shopxz-japan-launch，`shipping` 取 `policies.json`）、GMC 只读审核（ilang-gmc-auditor）。

## 选品门禁（discover）

按 profile 的类目/关键词分页拉取，过滤测试品、价格区间、上架数、排除类目与禁用词（品牌、违禁品、供应商名），同名去重后取详情、首变体各仓库存、CN→目标国与 JP→目标国运费，选可追踪且时效达标的物流，算到手成本与日元售价，毛利低于 `min_margin` 不通过。每个商品都保留通过/不通过原因，`candidates.json` 可续跑，API 积分低于保留值即停止。

## 定价

`landed = 变体价 + 运费 + 手续费`；`售价 = landed × 汇率 × (1 + markup)` 按 `round_step/ending` 取整（默认 ¥…90），不低于 `min_price_jpy`。汇率来自公开汇率源并记录时间，可手动覆盖。不生成虚假划线价。

## 按任务读取

| 工作 | 引用 |
|---|---|
| 选品规则、禁用词维护 | [references/selection.md](references/selection.md) |
| 文案与图片要求 | [references/copy-and-images.md](references/copy-and-images.md) |
| 导入、条款、上线衔接 | [references/import-and-launch.md](references/import-and-launch.md) |
