// CI SSOT: generated from config/deployment_modes.yaml — DO NOT EDIT BY HAND
// 改部署模式请编辑该 yaml 后运行: python scripts/dev/deployment_modes_ssot.py generate --apply

class DeploymentModesSsot {
  const DeploymentModesSsot._();

  static const defaultMode = "safe";
  static const modeIds = <String>["absolute_safe", "safe", "performance"];
  static const mobileLanFirstConnections = <String>["lan_direct", "public_relay_with_lan_fallback"];

  static bool mobileConnectionPrefersLan(String value) =>
      mobileLanFirstConnections.contains(value.trim());
}
