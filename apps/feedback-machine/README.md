# 反馈出题机（Android · Capacitor）

自用 **答一题 → 看反馈 → 再出一题** 壳，对接现有练习台 `GET/POST /api/v1/practice/*`（与 `web/static/teaching-shell.html` 同源契约）。钉钉日推与 VPS 调度**不改动**。

## 包信息

| 项 | 值 |
|----|-----|
| applicationId | `icu.longee.feedback` |
| 显示名 | 反馈出题机 |
| Web 根目录 | `www/`（设置 + 主路径） |

## 设置项（本机 localStorage）

| 字段 | 说明 |
|------|------|
| DeepSeek API Key | 可选，预留本机 OCR/直连；当前批改仍走练习台 API |
| DeepSeek Base URL | 可选 |
| 练习台 Base URL | 默认 `https://practice.longee.icu` |
| Practice API Token | 与 VPS `PRACTICE_API_TOKEN` 一致 |
| Learner Id | 默认 `04022300566420984205` |

**勿将真实密钥提交 git。**

## API 假设（「再出一题」）

1. `GET /api/v1/practice/bootstrap?learner=` — 今日推送队列里未答的题优先。
2. 无未答题时：`GET /api/v1/practice/item?learner=&kind=math|comm|review` — 与 teaching-shell 的 `pickSlotFromBank` 相同，从题库 `ready` 抽题（`fromBank`）。
3. `POST /api/v1/practice/submit` — 批改反馈；大题可能异步，壳会轮询 `GET /item` 直至 `result` 就绪。

公网练习台需配置 `PRACTICE_API_TOKEN`；若浏览器/WebView 跨域，服务端还需 `PRACTICE_CORS_ORIGIN` 包含 Capacitor 来源（常见为 `https://localhost`）。

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

**Debug APK 路径：**

`apps/feedback-machine/android/app/build/outputs/apk/debug/app-debug.apk`

复制到 artifacts（可选）：

`apps/feedback-machine/artifacts/feedback-machine-debug.apk`

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

## 本期不做

- FCM 推送、应用商店上架、正式签名
- 多人登录、卸钉钉
- Android Keystore 存密钥（文档跟进；当前 localStorage）
- 本机 DeepSeek OCR 接线（设置项已预留）

## 与主仓关系

- 练习 API 实现：`deliver/practice_web.py` · `modules/bridge/practice_service.py`
- 契约：`docs/practice-api.md`
- 未启用 pi-rpc；未修改 DingTalk 推送路径
