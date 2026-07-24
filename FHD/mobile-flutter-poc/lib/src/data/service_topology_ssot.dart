// CI SSOT: generated from config/service_topology.yaml — DO NOT EDIT BY HAND
// 改拓扑请编辑该 yaml 后运行: python scripts/dev/service_topology_ssot.py generate --apply

class XcagiMobileTopology {
  const XcagiMobileTopology._();
  static const productionHost = 'xiu-ci.com';
  static const productionScheme = 'https';
  static const siteRootUrl = 'https://xiu-ci.com';
  static const fhdApiBaseUrl = 'https://xiu-ci.com/fhd-api';
  static const marketBaseUrl = 'https://xiu-ci.com/market';
  static const llmV1BaseUrl = 'https://xiu-ci.com/v1';
  static const marketCatalogUrl = 'https://xiu-ci.com/api/market/catalog';
  static const imWsUrl = 'wss://xiu-ci.com/ws/im';
  static const desktopFhdListenPort = 17500;
  static const fhdApiListenPort = 5000;
  static const fhdApiUpstreamPort = 5100;
  static const mobileLanProxyListenPort = 5011;
  static const modstoreListenPort = 9999;
  static const modstoreUpstreamPort = 9999;
  static const modstoreSchedulerListenPort = 9990;
  static const mustRunProcesses = <String>['web', 'modstore-api', 'modstore-scheduler'];
}
