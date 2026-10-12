# 公开示意站 / Public showcase

`site/` 是 teaching-cultivator 的静态示意站：中文 / English，练习台（暖纸色）与工作室（冷地面、硬边、绯红）。题干和数字都是占位，不含学员姓名、编号、令牌或会话。

页面不请求练习接口。公开练习入口只在文案里作为演示链接出现：<https://practice.longee.icu>（不附带令牌）。

## 启用 GitHub Pages

仓库 → **Settings** → **Pages** → **Build and deployment** → **Deploy from a branch**：

| 项 | 值 |
|----|----|
| Branch | `master` |
| Folder | `/site` |

保存后，站点地址形如：

`https://longee142857.github.io/teaching-cultivator/`

本目录已放 `.nojekyll`，避免 Jekyll 改写静态文件。无需构建，也不需要 Actions。

## 本地预览

在仓库根目录：

```bash
python3 -m http.server 4173 --directory site
```

打开 <http://127.0.0.1:4173/>。语言和皮肤记在浏览器 `localStorage`（`tc-lang`、`tc-style`）。

## 页面

| 文件 | 内容 |
|------|------|
| `index.html` | 首页：日程、反馈、钉钉、可选外壳，并排两种皮肤 |
| `product.html` | 产品：数学 / 通信，练习台、钉钉、反馈出题机 |
| `gallery.html` | 样式：今日队列、作答、反馈、讲师、通知、外壳；可并排或单屏 |
| `how.html` | 如何工作：日程 → 回写，不写密钥 |
| `contact.html` | 联系：`mailto:longee142857@qq.com`；钉钉群定制服务不公布群号 |

## Enable GitHub Pages

Repo → **Settings** → **Pages** → **Deploy from a branch** → branch **`master`**, folder **`/site`**.

The published URL looks like `https://longee142857.github.io/teaching-cultivator/`. `.nojekyll` is included so Pages serves the files as-is. There is no build step.
