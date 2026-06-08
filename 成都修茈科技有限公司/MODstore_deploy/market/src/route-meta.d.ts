import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    layout?: 'public' | 'default'
    auth?: boolean
    admin?: boolean
  }
}
