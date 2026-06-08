import { installFetchDbReadToken } from './installFetchDbReadToken'

export function registerPrimaryKeyGuard(): void {
  installFetchDbReadToken()
}
