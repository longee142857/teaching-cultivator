# 反馈出题机（Android · Capacitor）

自用 **答一题 → 看反馈 → 再出一题** 壳，对接现有练习台 `GET/POST /api/v1/practice/*` 与 `POST /api/v1/tutor/chat`（与 `web/static/teaching-shell.html` 同源契约）。钉钉日推与 VPS 调度**不改动**。

视觉与主路径对齐练习台：纸色底、题干卡片、批改条、折叠讲解、「不懂，问讲师」。公式使用仓内 `web/static/katex` 的同一份 KaTeX（拷到 `www/vendor/katex`），不走 jsDelivr。正文字体是仓内 `www/vendor/fonts` 的 Source Serif 4 与 IBM Plex Mono。

同一 APK 里有两套画法，页头或设置里切换，记在本机 `fqm_theme_v1`：

| 值 | 画法 |
|----|------|
| `desk`（默认） | 对齐现网练习台：纸色、卡片微倾、软阴影、56px 横滑翻页 |
| `studio` | 工作室对照：冷底、硬边套印、更大的翻页和批改章 |

底栏四项：练习、周卷、讲师、能力。能力页是 `www/brain/`（练习台同一份脑图，接口带壳里的 Token）。

改了 `www/` 之后打 APK 前要 `npx cap sync android`，否则安装包里还是旧页面。

## 包信息

| 项 | 值 |
|----|-----|
| applicationId | `icu.longee.feedback` |
| 显示名 | 反馈出题机 |
| Web 根目录 | `www/`（设置 + 主路径） |

## 设置项（本机 localStorage）

| 字段 | 说明 |
|------|------|
| DeepSeek API Key | **当前未使用**。只存在本机；批改仍走练习台，填了也不会拿去打分 |
| DeepSeek Base URL | **当前未使用**，预留 |
| 练习台 Base URL | 默认 `https://practice.longee.icu`。出题、批改、讲题都打这里 |
| Practice API Token | 与 VPS `PRACTICE_API_TOKEN` 一致。错了会提示 **Token 无效（401）**，不会当成网络中断 |
| Learner Id | 默认 `04022300566420984205`。请求带 `X-Learner-Id` |
| 更新清单地址 | 可留空。留空时固定检查 `https://practice.longee.icu/app/feedback-machine/version.json` |

**勿将真实密钥提交 git。**

## 应用更新

启动时静默拉一次更新清单，失败不打断做题。设置页显示当前 `versionName` / `versionCode`，并有「检查更新」。远端 `versionCode` 更大，或本机低于 `minVersionCode` 时，提示「有新版本」，用系统浏览器打开 `apkUrl` 下载。`package` 不是 `icu.longee.feedback` 的清单会忽略。

默认地址（已挂在练习台，CORS `*`，CapacitorHttp 从 `https://localhost` 可拉，不带练习台 Token）：

`https://practice.longee.icu/app/feedback-machine/version.json`

| 字段 | 说明 |
|------|------|
| `package` | 应用包名，须为 `icu.longee.feedback` |
| `versionCode` | 整数。大于本机 versionCode 才提示更新 |
| `versionName` | 展示用 |
| `apkUrl` | APK 的 https 直链 |
| `apkMd5` | 设置页展示，下载仍直接打开 `apkUrl` |
| `releaseNotes` | 设置页里的短说明 |
| `minVersionCode` | 本机低于此值时也提示更新 |

本机版本优先读 Capacitor `App.getInfo()`（`build` 是 versionCode，`version` 是 versionName）。浏览器预览没有该插件时，回退 `www/js/config.js` 里的 `3` / `1.0.2`，与 `android/app/build.gradle` 相同。发布新包时把这两处 `versionCode` 一起加一，并改练习台上的 `version.json`。依赖 `@capacitor/app`，打包前 `npm ci` 然后 `npx cap sync android`。

## API 假设（「再出一题」）

1. `GET /api/v1/practice/bootstrap?learner=` — 今日三槽。队列里未答的题按顺序做，**包含复习**；已经推送的通信题也可以点槽进入。
2. 空槽补题：`GET /api/v1/practice/item?learner=&kind=math|review`。**空的通信槽不请求 `kind=comm`**（通信 ready 库存很薄）。
3. `POST /api/v1/practice/submit` — 批改反馈。结果若已就绪，立刻 `busy=false` 并画到反馈页（不再停在「提交中」）。仍在批改则轮询 `GET /item`。
4. `POST /api/v1/tutor/chat` — 「不懂，问讲师」/「发给老师讨论」，`Accept: text/event-stream`。浏览器边收边画；原生 CapacitorHttp 等整段结束后按 SSE 事件回放。未接线时 501，文案与练习台一致。
5. `POST /api/v1/practice/ocr`、`POST /api/v1/practice/report-poor`、`GET /api/v1/exam/papers`。能力页经壳代发 `practice/params` 和 `capability/events`。

公网练习台需配置 `PRACTICE_API_TOKEN`。

### 网络：为何用 CapacitorHttp

Capacitor WebView 的页面 Origin 为 `https://localhost`，对 `practice.longee.icu` 的 `fetch` 会触发浏览器 CORS（练习台未开 `Access-Control-Allow-Origin` 时直接失败）。**APK 内** `www/js/api.js` 在原生壳上优先走 `Capacitor.Plugins.CapacitorHttp`（原生 HTTP，不经 WebView CORS）；仅浏览器静态预览或 `cap run` 的 web 平台才回退 `fetch`。因此**不必**为 App 单独改 VPS `PRACTICE_CORS_ORIGIN`。

## 本地打开 Web（不打包）

```bash
cd apps/feedback-machine
python3 -m http.server 5199 --directory www
# 浏览器 http://127.0.0.1:5199/
```

仅静态页；调用远程 API 时受浏览器 CORS 限制，完整联调请用 APK 或在本机反代练习台。

## Android Debug APK

### 依赖

- Node 18+、JDK 17+
- Android SDK（API 34+）与 `ANDROID_HOME` / `ANDROID_SDK_ROOT`

云端/CI 一键安装 SDK 示例：

```bash
bash scripts/install-android-sdk.sh
source scripts/android-env.sh
```

### 构建

```bash
cd apps/feedback-machine
npm ci
bash scripts/copy-capacitor-runtime.sh   # www/js/capacitor.js（CapacitorHttp 桥）
npx cap sync android
cd android
./gradlew assembleDebug
```

或使用仓库脚本（sync + assemble）：

```bash
cd apps/feedback-machine
npm ci
npm run build:apk
```

**Debug APK 路径（本地或 CI，不入库）：**

`apps/feedback-machine/android/app/build/outputs/apk/debug/app-debug.apk`

脚本会再复制一份到 `apps/feedback-machine/artifacts/`，该目录已 gitignore。安装包以 GitHub Actions artifact `feedback-machine-debug-apk` 为准，不要把 APK 提交进 git。

### 安装到手机（侧载）

```bash
adb install -r apps/feedback-machine/android/app/build/outputs/apk/debug/app-debug.apk
```

调试签名，**不可上架**；无正式 keystore。

### Capacitor 常用命令

```bash
npx cap sync android    # 拷贝 www → android/app/src/main/assets
npx cap open android    # 打开 Android Studio（若已安装）
```

## 和练习台对齐的主路径

- 今日三槽（数学 / 通信 / 复习）、翻页、历史未答
- 页头切换练习台 / 工作室
- 周卷列表和试卷页
- 能力页：`www/brain/`
- 拍照或选图 OCR、「题质量差」
- 讲师走 SSE。原生壳等整段响应后再按事件打字；最近会话留在本机
- 讲师回复「复制原文」写入消息原文（含公式分隔符），并打开与练习台相同的原文面板，便于 WebView 拦剪贴板时长按复制
- 复习题进入「下一题」。空的复习槽按 `kind=review` 补题

通信空槽不从题库补货。DeepSeek 字段只保存在本机，不发请求。

## 壳逻辑自测

```bash
cd apps/feedback-machine
npm test
```

## 本期不做

- FCM 推送、应用商店上架、正式签名
- 多人登录、卸钉钉
- Android Keystore 存密钥（文档跟进；当前 localStorage）
- 本机 DeepSeek OCR 接线（设置项标明未使用）

## 与主仓关系

- 练习 API 实现：`deliver/practice_web.py` · `modules/bridge/practice_service.py`
- 契约：`docs/practice-api.md`
- 未启用 pi-rpc；未修改 DingTalk 推送路径
