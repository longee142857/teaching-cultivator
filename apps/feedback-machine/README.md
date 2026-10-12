# 反馈出题机（Android · Capacitor）

自用 **答一题 → 看反馈 → 再出一题** 壳，对接现有练习台 `GET/POST /api/v1/practice/*` 与 `POST /api/v1/tutor/chat`（与 `web/static/teaching-shell.html` 同源契约）。钉钉日推与 VPS 调度**不改动**。

视觉与主路径对齐练习台：纸色底、题干卡片、批改条、折叠讲解、「不懂，问讲师」。公式使用仓内 `web/static/katex` 的同一份 KaTeX（拷到 `www/vendor/katex`），不走 jsDelivr。

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

**勿将真实密钥提交 git。**

## API 假设（「再出一题」）

1. `GET /api/v1/practice/bootstrap?learner=` — 今日队列里未答的 **数学** 题优先。
2. 没有可做的数学题时：`GET /api/v1/practice/item?learner=&kind=math` — 与 teaching-shell 的 `pickSlotFromBank` 相同，从题库 `ready` 抽题（`fromBank`）。**「再出一题」和空槽补题固定 `kind=math`**，不因当前题是通信/复习就把 `lastKind` 改过去（通信 ready 库存很薄，这条路径不补通信）。
3. `POST /api/v1/practice/submit` — 批改反馈。结果若已就绪，立刻 `busy=false` 并画到反馈页（不再停在「提交中」）。仍在批改则轮询 `GET /item`。
4. `POST /api/v1/tutor/chat` — 练习台上的「不懂，问讲师」/「发给老师讨论」。壳要 JSON（`Accept: application/json`），因为 CapacitorHttp 不能消费 SSE。未接线时服务端 501，文案与练习台一致。

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

## 与练习台仍有的差距

- 无今日三槽总览、左右翻页、历史未答列表
- 无周卷、资料库、能力页、手写拍照 OCR、「题质量差」
- 讲师是整段 JSON 回复，没有练习台的 SSE 打字流，也没有最近会话条
- 默认回路只抽数学；通信/复习未答不会被「再出一题」抽走
- DeepSeek 字段只保存，不发起请求

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
