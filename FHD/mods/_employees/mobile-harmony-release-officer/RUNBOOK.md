# 鸿蒙发版员 · Runbook(全自动发版)

本员工负责鸿蒙 HarmonyOS 企业版上架华为应用市场(AppGallery),**全自动**:编译 → 真证书签名 → AGC Publishing API 上传 + 自动提交审核。

## 执行位置与密钥
- 执行:**本机 Mac mini**(脚本逻辑在本仓 `FHD/mobile-harmony/scripts/`,版本可控)。
- 密钥:仓库外 `~/XCMAX-runtime/harmony/signing/`(不进 git):
  - 签名材料:`xcagi-release.{p12,cer,p7b}`
  - 发布密钥:`agc-api.env`(从 `agc-api.env.template` 复制填写)
    - `AGC_CLIENT_ID` / `AGC_CLIENT_SECRET`(AGC → 用户与访问 → Connect API 团队密钥,需发布权限)
    - `AGC_APP_ID`(默认 `6917609159673222535`)
    - `HARMONY_KEY_PWD`(签名密钥库密码)

## 一条龙
```bash
bash FHD/mobile-harmony/scripts/release-harmony.sh --version 10.0.0
```
步骤:
1. 倒序证书链(AGC 给的是 根→中间→叶子,hap-sign-tool 要 叶子→中间→根)
2. `hvigor assembleApp -p buildMode=release` → unsigned `.app`
3. 从 `.app` 取 `entry-default.hap`,`hap-sign-tool sign-app` 用 AGC 发布证书签名,zip 换回 `.app`
4. **质量门**:`verify-app` 不通过即中止,绝不推坏包(此为工程校验,非人工审批)
5. `publish-agc-harmony.sh` 调 AGC Publishing API:token → upload-url → 上传 → app-file-info → **app-submit(自动提交审核)**

只上传不提交:`release-harmony.sh --no-submit`。

## 关键事实
- 包名:`com.xiuci.xcagi.mobile.enterprise`(= 安卓企业版,完全一致)
- 备案:`蜀ICP备2026015936号`(工信部 2026-04-08;鸿蒙证书签名与安卓不同,若上传校验备案签名报错,把鸿蒙公钥/MD5 补登同一备案号)
- 开发者账号:个人(李佳泷),非企业 → 商店开发者显示个人名
- AppGallery 收 `.app`(App Pack),不收 `.hap`;每个版本都要过华为审核(1–3 工作日),API 只免去手动上传,审核免不掉
- 鸿蒙消费版**不能**像安卓那样应用内 OTA 静默自更新(NEXT 锁侧载),更新必须走应用市场

## AGC API 鉴权与上传(2026-06 已实测通过)
- 凭证类型必须是「**API客户端**」(给 Client ID + 密钥字符串),**不是** Service Account(JWT 私钥那种,发布接口不认)。
- ⚠️ 403 坑:API 客户端必须能访问目标 app(app 须在该客户端所属**项目**下);否则 token 有效也 403。首个客户端 403,新建客户端 `1980171939389399488` 后 403 消失。
- 上传流(`publish-agc-harmony.py` 已固化,**实测通过**):
  1. `POST /api/oauth2/v1/token`(client_credentials)→ token
  2. `GET /api/publish/v2/upload-url/for-obs?appId=&fileName=&contentLength=&releaseType=1` → OBS 预签名 PUT 地址 + objectId(**注意:鸿蒙用 for-obs,不是旧的多段 upload-url**)
  3. PUT .app 到 OBS(带返回的 AWS4 签名头 + Content-Length)
  4. `PUT /api/publish/v2/app-file-info` body `{fileType:5, files:[{fileName, fileDestUrl:objectId}]}` → 绑定,返回 pkgVersion
  5. `POST /api/publish/v2/app-submit?appId=&releaseType=1` → 提交审核

## 首跑前置(只需一次)
1. `~/XCMAX-runtime/harmony/signing/agc-api.env` 填 AGC_CLIENT_ID/SECRET/APP_ID + HARMONY_KEY_PWD(已配好)
2. AGC「应用信息」填齐(名称/介绍/图标/隐私政策 HTTPS/截图)——**submit 的前置**,否则 app-submit 报应用信息不全
3. ✅ 上传+绑定已实测通(包已挂上版本);**只剩 submit 待首次成功**(需上面第2步)
