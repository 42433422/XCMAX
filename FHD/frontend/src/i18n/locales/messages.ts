import shellEn from './en-US/shell.json'
import chatEn from './en-US/chat.json'
import loginEn from './en-US/login.json'
import settingsEn from './en-US/settings.json'
import errorsEn from './en-US/errors.json'
import shellZh from './zh-CN/shell.json'
import chatZh from './zh-CN/chat.json'
import loginZh from './zh-CN/login.json'
import settingsZh from './zh-CN/settings.json'
import errorsZh from './zh-CN/errors.json'

export const enUSMessages = {
  ...shellEn,
  ...chatEn,
  ...loginEn,
  ...settingsEn,
  ...errorsEn,
}

export const zhCNMessages = {
  ...shellZh,
  ...chatZh,
  ...loginZh,
  ...settingsZh,
  ...errorsZh,
}
