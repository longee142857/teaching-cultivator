# 公开示意站 / Public showcase

> 新人先看仓库根目录 [README.md](../README.md)，再打开线上站 <https://longee142857.github.io/teaching-cultivator/>。本文件只讲如何发布和本地预览。
> New humans: root [README.md](../README.md) and the live site first. This file is publish and local-preview notes only.

`site/` 是 teaching-cultivator 的静态示意站：中文 / English，练习台（暖纸色）与工作室（冷地面、硬边、绯红）。题干和数字都是占位，不含学员姓名、编号、令牌或会话。

页面不请求练习接口。公开练习入口只在文案里作为演示链接出现：<https://practice.longee.icu>（不附带令牌）。

## 启用 GitHub Pages

**Deploy from a branch** 只能选文件夹 `/` 或 `/docs`，不能发布 `/site`。本仓库用 **GitHub Actions** 发布 `site/`。

1. 仓库 → **Settings** → **Pages** → **Build and deployment** → **Source** 选 **GitHub Actions**。
2. [`.github/workflows/pages.yml`](../.github/workflows/pages.yml) 在推送到 `master`（`site/**` 或该工作流有变更）时部署；也可在 Actions 里手动运行。

站点地址：

`https://longee142857.github.io/teaching-cultivator/`

`site/` 里已有 `.nojekyll`。页面是纯静态 HTML/CSS/JS，没有构建步骤。

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
| `product.html` | 产品：数学，以及可配置的其他科目（示意例子：通信） |
| `gallery.html` | 样式：今日队列、作答、反馈、讲师、通知、外壳；可并排或单屏 |
| `how.html` | 如何工作：日程 → 回写，不写密钥 |
| `contact.html` | 联系：`mailto:longee142857@qq.com`；钉钉群定制服务不公布群号 |

## Enable GitHub Pages

**Deploy from a branch** only accepts folder `/` or `/docs`, so it cannot publish `/site`. This repo uses **GitHub Actions** to publish `site/`.

1. Repo → **Settings** → **Pages** → **Build and deployment** → set **Source** to **GitHub Actions**.
2. [`.github/workflows/pages.yml`](../.github/workflows/pages.yml) deploys on push to `master` when `site/**` or that workflow changes. You can also run it from the Actions tab.

The published URL is `https://longee142857.github.io/teaching-cultivator/`. `.nojekyll` is already in `site/`. The site is plain HTML/CSS/JS; there is no build step.

Subjects on the showcase are configurable: math, plus one or more others. Communications is only the demo example.
