import { common } from '@kit.AbilityKit';
import { util } from '@kit.ArkTS';
import { cryptoFramework } from '@kit.CryptoArchitectureKit';
import { huks } from '@kit.UniversalKeystoreKit';
import {
  FlutterPlugin,
  FlutterPluginBinding,
  MethodCall,
  MethodCallHandler,
  MethodChannel,
  MethodResult,
} from '@ohos/flutter_ohos';

const credentialAlias = 'com.xiuci.xcagi.credentials.v1';
const credentialPrefix = 'enc:v1:';
const nonceLength = 12;
const tagLength = 16;

class CredentialCipher implements MethodCallHandler {
  private keyReady?: Promise<void>;
  private readonly encoder = new util.TextEncoder();
  private readonly base64 = new util.Base64Helper();

  onMethodCall(call: MethodCall, result: MethodResult): void {
    switch (call.method) {
      case 'encrypt': {
        const plain = call.argument('plain');
        if (typeof plain !== 'string') {
          result.error('invalid_argument', '无法加密无效的凭证', null);
          return;
        }
        this.encrypt(plain).then((encrypted: string) => result.success(encrypted))
          .catch(() => result.error('credential_cipher', '当前设备无法安全保存凭证', null));
        break;
      }
      case 'decrypt': {
        const stored = call.argument('stored');
        if (typeof stored !== 'string') {
          result.success('');
          return;
        }
        // An invalid envelope or a missing local key must never become a token.
        this.decrypt(stored).then((plain: string) => result.success(plain))
          .catch(() => result.success(''));
        break;
      }
      default:
        result.notImplemented();
    }
  }

  private async prepareKey(): Promise<void> {
    const storage: huks.HuksParam = {
      tag: huks.HuksTag.HUKS_TAG_AUTH_STORAGE_LEVEL,
      value: huks.HuksAuthStorageLevel.HUKS_AUTH_STORAGE_LEVEL_CE,
    };
    if (await huks.hasKeyItem(credentialAlias, { properties: [storage] })) return;
    await huks.generateKeyItem(credentialAlias, {
      properties: [
        storage,
        { tag: huks.HuksTag.HUKS_TAG_ALGORITHM, value: huks.HuksKeyAlg.HUKS_ALG_AES },
        { tag: huks.HuksTag.HUKS_TAG_KEY_SIZE, value: huks.HuksKeySize.HUKS_AES_KEY_SIZE_256 },
        {
          tag: huks.HuksTag.HUKS_TAG_PURPOSE,
          value: huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_ENCRYPT |
            huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_DECRYPT,
        },
      ],
    });
  }

  private async encrypt(plain: string): Promise<string> {
    if (plain.length === 0) return '';
    if (!this.keyReady) {
      this.keyReady = this.prepareKey().catch(() => {
        this.keyReady = undefined;
        throw new Error('Cannot initialize the credential key');
      });
    }
    await this.keyReady;
    const nonce = cryptoFramework.createRandom().generateRandomSync(nonceLength).data;
    const input = this.encoder.encodeInto(plain);
    const encrypted = await this.transform(input, nonce);
    if (encrypted.length !== input.length + tagLength) {
      throw new Error('Invalid HUKS ciphertext');
    }
    const envelope = new Uint8Array(nonce.length + encrypted.length);
    envelope.set(nonce);
    envelope.set(encrypted, nonce.length);
    return credentialPrefix + this.base64.encodeToStringSync(envelope);
  }

  private async decrypt(stored: string): Promise<string> {
    if (!stored.startsWith(credentialPrefix)) return '';
    const envelope = this.base64.decodeSync(stored.slice(credentialPrefix.length));
    if (envelope.length <= nonceLength + tagLength) return '';
    const end = envelope.length - tagLength;
    const nonce = envelope.slice(0, nonceLength);
    const plain = await this.transform(envelope.slice(nonceLength, end), nonce, envelope.slice(end));
    return util.TextDecoder.create('utf-8').decodeToString(plain);
  }

  // HUKS owns the non-exportable AES key and performs authenticated encryption.
  private async transform(input: Uint8Array, nonce: Uint8Array, tag?: Uint8Array): Promise<Uint8Array> {
    const properties: huks.HuksParam[] = [
      { tag: huks.HuksTag.HUKS_TAG_ALGORITHM, value: huks.HuksKeyAlg.HUKS_ALG_AES },
      { tag: huks.HuksTag.HUKS_TAG_KEY_SIZE, value: huks.HuksKeySize.HUKS_AES_KEY_SIZE_256 },
      { tag: huks.HuksTag.HUKS_TAG_AUTH_STORAGE_LEVEL,
        value: huks.HuksAuthStorageLevel.HUKS_AUTH_STORAGE_LEVEL_CE },
      {
        tag: huks.HuksTag.HUKS_TAG_PURPOSE,
        value: tag === undefined ? huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_ENCRYPT :
          huks.HuksKeyPurpose.HUKS_KEY_PURPOSE_DECRYPT,
      },
      { tag: huks.HuksTag.HUKS_TAG_BLOCK_MODE, value: huks.HuksCipherMode.HUKS_MODE_GCM },
      { tag: huks.HuksTag.HUKS_TAG_PADDING, value: huks.HuksKeyPadding.HUKS_PADDING_NONE },
      { tag: huks.HuksTag.HUKS_TAG_NONCE, value: nonce },
      { tag: huks.HuksTag.HUKS_TAG_ASSOCIATED_DATA, value: this.encoder.encodeInto(credentialAlias) },
    ];
    if (tag !== undefined) properties.push({ tag: huks.HuksTag.HUKS_TAG_AE_TAG, value: tag });
    const options: huks.HuksOptions = { properties: properties, inData: input };
    const session = await huks.initSession(credentialAlias, options);
    try {
      const output = await huks.finishSession(session.handle, options);
      if (output.outData === undefined) throw new Error('HUKS did not return data');
      return output.outData;
    } catch (error) {
      await huks.abortSession(session.handle, { properties: [] }).catch(() => {});
      throw new Error('Credential operation failed');
    }
  }
}

class SessionPaths implements MethodCallHandler {
  private readonly context: common.Context;

  constructor(context: common.Context) {
    this.context = context;
  }

  onMethodCall(call: MethodCall, result: MethodResult): void {
    switch (call.method) {
      case 'sessionFilePath':
        result.success(this.context.filesDir + '/xcagi_session.json');
        break;
      case 'localWorkspaceDirectory':
        result.success(this.context.databaseDir);
        break;
      default:
        result.notImplemented();
    }
  }
}

export default class XcagiPlatformPlugin implements FlutterPlugin {
  private sessionChannel?: MethodChannel;
  private credentialChannel?: MethodChannel;

  getUniqueClassName(): string {
    return 'XcagiPlatformPlugin';
  }

  onAttachedToEngine(binding: FlutterPluginBinding): void {
    const messenger = binding.getBinaryMessenger();
    this.sessionChannel = new MethodChannel(messenger, 'xcagi/session_store');
    this.sessionChannel.setMethodCallHandler(new SessionPaths(binding.getApplicationContext()));
    this.credentialChannel = new MethodChannel(messenger, 'xcagi/credential_cipher');
    this.credentialChannel.setMethodCallHandler(new CredentialCipher());
  }

  onDetachedFromEngine(binding: FlutterPluginBinding): void {
    this.sessionChannel?.setMethodCallHandler(null);
    this.credentialChannel?.setMethodCallHandler(null);
    this.sessionChannel = undefined;
    this.credentialChannel = undefined;
  }
}
