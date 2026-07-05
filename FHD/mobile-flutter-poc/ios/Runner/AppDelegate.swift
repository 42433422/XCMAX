import Flutter
import LocalAuthentication
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var deepLinkChannel: FlutterMethodChannel?
  private var pendingDeepLinkRoute: String?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    if let url = launchOptions?[.url] as? URL {
      pendingDeepLinkRoute = parseDeepLinkRoute(url)
    }
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    registerXcagiChannels(messenger: engineBridge.applicationRegistrar.messenger())
  }

  func handleDeepLink(_ url: URL) {
    guard let route = parseDeepLinkRoute(url) else {
      return
    }
    if let channel = deepLinkChannel {
      channel.invokeMethod("onRoute", arguments: route)
    } else {
      pendingDeepLinkRoute = route
    }
  }

  private func registerXcagiChannels(messenger: FlutterBinaryMessenger) {
    deepLinkChannel = FlutterMethodChannel(
      name: "xcagi/deep_link",
      binaryMessenger: messenger
    )
    deepLinkChannel?.setMethodCallHandler { [weak self] call, result in
      guard call.method == "getInitialRoute" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(self?.consumePendingDeepLinkRoute())
    }

    FlutterMethodChannel(
      name: "xcagi/session_store",
      binaryMessenger: messenger
    ).setMethodCallHandler { [weak self] call, result in
      guard call.method == "sessionFilePath" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(self?.sessionFilePath())
    }

    FlutterMethodChannel(
      name: "xcagi/credential_cipher",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      switch call.method {
      case "encrypt":
        let args = call.arguments as? [String: Any]
        result(args?["plain"] as? String ?? "")
      case "decrypt":
        let args = call.arguments as? [String: Any]
        result(args?["stored"] as? String ?? "")
      default:
        result(FlutterMethodNotImplemented)
      }
    }

    FlutterMethodChannel(
      name: "xcagi/biometric",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      switch call.method {
      case "canAuthenticate":
        result(Self.canAuthenticate())
      case "authenticate":
        Self.authenticate(result: result)
      case "finishApp":
        result(nil)
      default:
        result(FlutterMethodNotImplemented)
      }
    }

    FlutterMethodChannel(
      name: "xcagi/background_work",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "reconcile" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result(["platform": "ios", "available": false])
    }

    FlutterMethodChannel(
      name: "xcagi/update_installer",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "startPackageUpdate" else {
        result(FlutterMethodNotImplemented)
        return
      }
      result("iOS 请通过 App Store 更新")
    }

    FlutterMethodChannel(
      name: "xcagi/content_uri",
      binaryMessenger: messenger
    ).setMethodCallHandler { call, result in
      guard call.method == "readBytes" else {
        result(FlutterMethodNotImplemented)
        return
      }
      let args = call.arguments as? [String: Any]
      let uri = args?["uri"] as? String ?? ""
      Self.readBytes(uri: uri, result: result)
    }
  }

  private func consumePendingDeepLinkRoute() -> String? {
    let route = pendingDeepLinkRoute
    pendingDeepLinkRoute = nil
    return route
  }

  private func sessionFilePath() -> String {
    let manager = FileManager.default
    let base = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
      ?? manager.temporaryDirectory
    let directory = base.appendingPathComponent("XCAGI", isDirectory: true)
    try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
    return directory.appendingPathComponent("xcagi_session.json").path
  }

  private func parseDeepLinkRoute(_ url: URL) -> String? {
    if url.scheme?.lowercased() == "xcagi" {
      let host = url.host ?? ""
      let path = url.path
      let route = "\(host)\(path)".trimmingCharacters(in: .whitespacesAndNewlines)
      return route.isEmpty ? nil : route
    }
    if url.host?.contains("xiu-ci.com") == true {
      let route = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
      return route.isEmpty ? "chat" : route
    }
    return nil
  }

  private static func canAuthenticate() -> Bool {
    var error: NSError?
    return LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: &error)
  }

  private static func authenticate(result: @escaping FlutterResult) {
    let context = LAContext()
    var error: NSError?
    guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
      result(false)
      return
    }
    context.evaluatePolicy(
      .deviceOwnerAuthentication,
      localizedReason: "Authenticate to unlock XCAGI"
    ) { success, _ in
      DispatchQueue.main.async {
        result(success)
      }
    }
  }

  private static func readBytes(uri: String, result: FlutterResult) {
    let text = uri.trimmingCharacters(in: .whitespacesAndNewlines)
    let url = URL(string: text) ?? URL(fileURLWithPath: text)
    do {
      let data = try Data(contentsOf: url)
      result(FlutterStandardTypedData(bytes: data))
    } catch {
      result(
        FlutterError(
          code: "CONTENT_URI_READ_FAILED",
          message: error.localizedDescription,
          details: nil
        )
      )
    }
  }
}
