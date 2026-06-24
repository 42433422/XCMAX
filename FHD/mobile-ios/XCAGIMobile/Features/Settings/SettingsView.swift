import SwiftUI

/// 设置(对标 Android `SettingsScreen` / 鸿蒙设置):主题、生物识别、关于、退出登录。
struct SettingsView: View {
    @EnvironmentObject private var session: SessionManager

    @State private var themeMode: String = "system"
    @State private var biometricEnabled = false
    @State private var showLogoutConfirm = false

    var body: some View {
        Form {
            Section("外观") {
                Picker("主题", selection: $themeMode) {
                    Text("跟随系统").tag("system")
                    Text("浅色").tag("light")
                    Text("深色").tag("dark")
                }
                .onChange(of: themeMode) { _ in persist() }
            }

            Section("安全") {
                Toggle(isOn: $biometricEnabled) {
                    Label("生物识别解锁", systemImage: "faceid")
                }
                .disabled(!BiometricGate.isAvailable)
                .onChange(of: biometricEnabled) { newValue in
                    if newValue {
                        Task {
                            let ok = await BiometricGate.authenticate()
                            if !ok { biometricEnabled = false }
                            persist()
                        }
                    } else {
                        persist()
                    }
                }
                if !BiometricGate.isAvailable {
                    Text("当前设备不支持或未设置面容/触控 ID")
                        .font(.caption).foregroundColor(.secondary)
                }
            }

            Section("关于") {
                LabeledContent("版本", value: appVersion)
                LabeledContent("公司", value: AppConfig.companyName)
                LabeledContent("后端", value: session.resolvedBaseURL)
                Link("服务条款", destination: URL(string: AppConfig.legalTermsURL)!)
                Link("隐私政策", destination: URL(string: AppConfig.legalPrivacyURL)!)
            }

            Section {
                Button(role: .destructive) { showLogoutConfirm = true } label: {
                    Text("退出登录").frame(maxWidth: .infinity)
                }
            }
        }
        .navigationTitle("设置")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            themeMode = session.session.themeMode
            biometricEnabled = session.session.biometricEnabled
        }
        .confirmationDialog("确定退出登录?", isPresented: $showLogoutConfirm, titleVisibility: .visible) {
            Button("退出登录", role: .destructive) { session.logout() }
            Button("取消", role: .cancel) {}
        }
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(v) (\(b))"
    }

    private func persist() {
        session.updatePreferences(biometricEnabled: biometricEnabled, themeMode: themeMode)
    }
}
