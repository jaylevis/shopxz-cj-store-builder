# 文案与图片

## 文案（enrich-tasks → 宿主 AI → enrich-apply）

`tasks.json` 的每个任务给出英文标题、类目路径、材质、重量、选项值、售价和清洗过的描述文本。宿主 AI 填写 `output`：

- `title_ja`：30–60 字，自然的日文商品名，不含品牌、型号堆砌、感叹号。
- `handle_en`：小写英文 slug，用作 URL；日文 URL 会被编码，不利于分享与广告。
- `bullets_ja`：3–5 条事实性卖点，每条 ≤40 字。
- `body_html_ja`：300–700 字，只用 `<p><ul><li><strong><h3>`，写素材、尺寸感、使用场景、注意事项；不写效能断言、不写在库・期限煽动、不放外链。
- `options_ja`：把每个英文选项值映射为日文（Blue→ブルー、M→M）。缺一个值即拒绝。
- `tags_ja`、`meta_title`（≤60）、`meta_description`（80–120）。

校验失败的任务写入 `enrich/problems.json`，修正后重跑 `enrich-apply`。禁用词校验覆盖全部字段。

## 图片

- 原图下载到 `images/<pid>/orig/`，仅用于审计，不上传。
- WebP 由管理技能 `optimize-webp.py` 生成（最大宽 1600，约 300 KB）。
- `image_mode=ai-edit`：前 N 张用参考图编辑重拍（`scripts/image-edit.js`，走管理技能已配置的生图通道），提示词固定为干净影棚背景、商品不变、无文字无水印。重拍失败则回退 WebP 原图并在 manifest 记录错误。
- 变体图按原始 URL 映射到对应变体；AI 重拍后用重拍版本。
- 上传前人工抽查至少 10% 的 AI 图：商品形态、颜色、数量必须与原图一致，否则该商品改用 WebP 原图。

## 禁止

- 在标题、描述、alt、Meta 或图片内出现「AI 生成」「CJ」「ドロップシッピング」等来源说明。
- 用 AI 图伪造工厂、证书、客户评价等信任证据。
