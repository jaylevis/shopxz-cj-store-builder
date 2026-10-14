# 导入与上线衔接

## 1. 导入商品（fecify-site-manager-v6）

`export` 产出 `fecify-import/products.json`（字段与管理技能映射 schema 一致：title/handle/price/qty/sku/weight/body_html/meta/images/options/variants/tags）与 `images/`（本地 WebP，按 handle 分目录）。

```text
node <manager>/scripts/product-file-import/pipeline.js <run>/fecify-import/products.json --key=_id \
     --image-root=<run>/fecify-import/images --outdir=<temp>/cjbuild-import
```

Phase 1 只读，生成报告；向商家完整展示后，得到明确的「确认导入」再执行 `make-confirm.js` 与 `import-file.js --confirm-file=...`。导入后用 `verify-import.js` 回读数量、变体、图片。

## 2. 专辑与菜单

按 `summary.csv` 的类目建专辑，把商品绑定进去；头部菜单挂专辑，页脚挂条款页（管理技能 menu 模块，`menu/update` 为全量替换且带确认门禁）。

## 3. 条款、设置、邮件、召回（shopxz-japan-launch）

- `policies.json` 给出发货营业日与到货天数（取所选物流的最大时效），写入 profile 的 `shipping.handling_business_days` / `transit_business_days`；运费与免运门槛由商家决定，不从 CJ 运费直接照抄。
- 退货：CJ 对跨境退货支持有限，条款中客户原因退货的返送地址与承担方必须是商家真实安排，不能写成「退回中国仓」而实际做不到。
- 经营者、地址、电话为真实信息；缺失时条款页保持未公开。

## 4. 上线前检查

- ilang-gmc-auditor 只读审核：条款、联系方式、商品页、Feed（品牌字段留空或自有品牌，GTIN 无则 `identifier_exists=no`）。
- 真实下单测试一次（商家授权），确认运费、支付、CJ 侧能看到订单。
- 过审后换品：同类目分批，每次不超过 20–30%，条款与联系方式不变。
