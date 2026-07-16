import { appTasks, OhosAppContext, OhosPluginId } from '@ohos/hvigor-ohos-plugin';
import { getNode } from '@ohos/hvigor';

// 发版动态签名:env HARMONY_PWD_CIPHER 存在时注入发布签名(密文密码,工具链固定 material 派生)。
const SIGN_DIR = `${process.env.HOME}/XCMAX-runtime/harmony/signing`;
const CIPHER = process.env.HARMONY_PWD_CIPHER;

if (CIPHER) {
  const node = getNode(__filename);
  node.afterNodeEvaluate((n: any) => {
    const ctx: OhosAppContext = n.getContext(OhosPluginId.OHOS_APP_PLUGIN);
    const opt: any = ctx.getBuildProfileOpt();
    opt.app.signingConfigs = [{
      name: 'release',
      type: 'HarmonyOS',
      material: {
        storeFile: `${SIGN_DIR}/xcagi-release.p12`,
        storePassword: CIPHER,
        keyAlias: 'xcagi',
        keyPassword: CIPHER,
        signAlg: 'SHA256withECDSA',
        profile: `${SIGN_DIR}/xcagi-release.p7b`,
        certpath: `${SIGN_DIR}/xcagi-release-chain.cer`,
      },
    }];
    (opt.app.products || []).forEach((p: any) => { p.signingConfig = 'release'; });
    ctx.setBuildProfileOpt(opt);
  });
}

export default { system: appTasks, plugins: [] };
