import shell from './shell.json'
import chat from './chat.json'
import login from './login.json'
import settings from './settings.json'
import errors from './errors.json'

export default {
  ...shell,
  ...chat,
  ...login,
  ...settings,
  ...errors,
}
