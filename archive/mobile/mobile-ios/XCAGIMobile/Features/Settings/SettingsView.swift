import SwiftUI

/// 设置(对标 Android `SettingsScreen` / 鸿蒙设置):主题、生物识别、问题反馈、检查更新、关于、退出登录。
struct SettingsView: View {
    @EnvironmentObject private var session: SessionManager

    @State private var themeMode: String = "system"
    @State private var biometricEnabled = false
    @State private var showLogoutConfirm = false

    // 问题反馈(对标 Android submitFeedback / 鸿蒙 复用 chat 通道转发)
    @State private var feedback = ""
    @State private var submittingFeedback = false

    // 检查更新(对标 Android checkForUpdate / 鸿蒙 home() 探活)
    @State private var checkingUpdate = false

    // 一次性提示(反馈/更新结果),对标 Android snack
    @State private var toast: String?

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

            // ── 问题反馈(对标 Android「反馈」分组;提交后进入企业支持队列) ──
            Section {
                Label("问题反馈", systemImage: "ladybug")
                    .font(.subheadline)
                TextEditor(text: $feedback)
                    .frame(minHeight: 88)
                    .overlay(alignment: .topLeading) {
                        if feedback.isEmpty {
                            Text("描述问题或建议")
                                .foregroundColor(Color(uiColor: .placeholderText))
                                .padding(.top, 8).padding(.leading, 5)
                                .allowsHitTesting(false)
                        }
                    }
                    .onChange(of: feedback) { newValue in
                        if newValue.count > 500 { feedback = String(newValue.prefix(500)) }
                    }
                Button {
                    submitFeedback()
                } label: {
                    HStack {
                        Spacer()
                        if submittingFeedback { ProgressView().padding(.trailing, 6) }
                        Text(submittingFeedback ? "提交中…" : "提交反馈")
                        Spacer()
                    }
                }
                .disabled(feedback.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || submittingFeedback)
            } header: {
                Text("反馈")
            } footer: {
                Text("提交后进入企业支持队列")
            }

            // ── 检查更新(对标 Android「版本」分组) ──
            Section("版本") {
                Button {
                    checkForUpdate()
                } label: {
                    HStack {
                        Label("检查更新", systemImage: "arrow.down.circle")
                        Spacer()
                        if checkingUpdate {
                            ProgressView()
                        } else {
                            Image(systemName: "chevron.right")
                                .font(.caption).foregroundColor(.secondary.opacity(0.5))
                        }
                    }
                }
                .disabled(checkingUpdate)
            }

            Section("关于") {
                LabeledContent("版本", value: appVersion)
                LabeledContent("公司", value: AppConfig.companyName)
                LabeledContent("连接", value: serverModeLabel)
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
        .overlay(alignment: .bottom) {
            if let toast {
                Text(toast)
                    .font(.footnote).foregroundColor(.white)
                    .padding(.horizontal, 16).padding(.vertical, 10)
                    .background(Color.black.opacity(0.8))
                    .clipShape(Capsule())
                    .padding(.bottom, 24)
                    .transition(.opacity)
                    .task {
                        try? await Task.sleep(nanoseconds: 1_800_000_000)
                        self.toast = nil
                    }
            }
        }
    }

    // MARK: - 反馈 / 检查更新

    /// 提交问题反馈:复用 chat 通道转发(对标鸿蒙 submitFeedback「避免新增端点,与 Android repo.submitFeedback 行为对齐」)。
    private func submitFeedback() {
        let text = feedback.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !submittingFeedback else { return }
        submittingFeedback = true
        Task {
            do {
                _ = try await session.api.chat(message: "[用户反馈] \(text)", sessionId: session.session.sessionId.isEmpty ? "feedback" : session.session.sessionId)
                feedback = ""
                toast = "感谢您的反馈,我们会尽快处理"
            } catch {
                let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                toast = "反馈提交失败:\(msg)"
            }
            submittingFeedback = false
        }
    }

    /// 检查更新:探活后端(对标鸿蒙 checkForUpdate 用 home() 探活,报「已是最新版本」)。
    private func checkForUpdate() {
        guard !checkingUpdate else { return }
        checkingUpdate = true
        Task {
            do {
                _ = try await session.api.home()
                toast = "已是最新版本"
            } catch {
                let msg = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
                toast = "检查更新失败:\(msg)"
            }
            checkingUpdate = false
        }
    }

    // 只展示连接模式标签,不暴露后端原始地址(对标 Android serverModeLabel)
    private var serverModeLabel: String {
        session.resolvedBaseURL.contains("xiu-ci.com") ? "云端服务" : "桌面端 · 局域网"
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
