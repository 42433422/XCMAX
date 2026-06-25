import SwiftUI

/// 登录页(对标 Android 登录 + 桌面绑定码 / 鸿蒙 `LoginPage`)。
struct LoginView: View {
    @EnvironmentObject private var session: SessionManager

    @State private var username = ""
    @State private var password = ""
    @State private var accountKind = "admin"     // admin=管理端,enterprise=企业端
    @State private var isSubmitting = false
    @State private var showPairing = false

    private var canSubmit: Bool {
        !username.trimmingCharacters(in: .whitespaces).isEmpty && !password.isEmpty && !isSubmitting
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: Theme.Space.lg) {
                    header

                    Picker("账号类型", selection: $accountKind) {
                        Text("管理端").tag("admin")
                        Text("企业端").tag("enterprise")
                    }
                    .pickerStyle(.segmented)

                    VStack(spacing: Theme.Space.md) {
                        TextField("账号 / 手机号", text: $username)
                            .textContentType(.username)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .padding()
                            .background(Theme.cardBackground)
                            .cornerRadius(Theme.Radius.md)

                        SecureField("密码", text: $password)
                            .textContentType(.password)
                            .padding()
                            .background(Theme.cardBackground)
                            .cornerRadius(Theme.Radius.md)
                    }

                    if let err = session.lastError {
                        Text(err)
                            .font(.footnote).foregroundColor(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button(action: submit) {
                        HStack {
                            if isSubmitting { ProgressView().tint(.white) }
                            Text(isSubmitting ? "登录中…" : "登录")
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, Theme.Space.md)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!canSubmit)

                    HStack(spacing: Theme.Space.xl) {
                        Button {
                            showPairing = true
                        } label: {
                            Label("桌面绑定码", systemImage: "desktopcomputer").font(.footnote)
                        }
                        NavigationLink {
                            RegisterView()
                        } label: {
                            Label("注册账号", systemImage: "person.badge.plus").font(.footnote)
                        }
                    }
                    .padding(.top, Theme.Space.sm)

                    Text("当前后端:\(session.resolvedBaseURL)")
                        .font(.caption2).foregroundColor(.secondary)
                        .padding(.top, Theme.Space.xs)
                }
                .padding(Theme.Space.xl)
            }
            .background(Theme.screenBackground.ignoresSafeArea())
            .navigationTitle("")
            .sheet(isPresented: $showPairing) {
                PairingSheet()
            }
        }
    }

    private var header: some View {
        VStack(spacing: Theme.Space.sm) {
            Image(systemName: "building.2.crop.circle.fill")
                .font(.system(size: 56)).foregroundColor(Theme.brand)
            Text("XCAGI").font(.title).bold()
            Text(AppConfig.companyName).font(.caption).foregroundColor(.secondary)
        }
        .padding(.top, Theme.Space.xl)
        .padding(.bottom, Theme.Space.md)
    }

    private func submit() {
        guard canSubmit else { return }
        isSubmitting = true
        Task {
            await session.login(username: username, password: password, loginAccountKind: accountKind)
            isSubmitting = false
        }
    }
}

/// 桌面端绑定码输入(对标 Android `pairing/exchange`)。
private struct PairingSheet: View {
    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            VStack(spacing: Theme.Space.lg) {
                Text("在桌面端「设置 → 移动绑定」生成 6 位绑定码,在此输入以连接到该主机。")
                    .font(.subheadline).foregroundColor(.secondary)
                    .multilineTextAlignment(.center)

                TextField("绑定码", text: $code)
                    .keyboardType(.numberPad)
                    .multilineTextAlignment(.center)
                    .font(.title3.monospaced())
                    .padding()
                    .background(Theme.cardBackground)
                    .cornerRadius(Theme.Radius.md)

                Button {
                    busy = true
                    Task {
                        await session.applyPairing(code: code)
                        busy = false
                        if session.lastError == nil { dismiss() }
                    }
                } label: {
                    Text(busy ? "连接中…" : "连接")
                        .frame(maxWidth: .infinity).padding(.vertical, Theme.Space.sm)
                }
                .buttonStyle(.borderedProminent)
                .disabled(code.trimmingCharacters(in: .whitespaces).isEmpty || busy)

                if let err = session.lastError {
                    Text(err).font(.footnote).foregroundColor(.red)
                }
                Spacer()
            }
            .padding(Theme.Space.xl)
            .navigationTitle("桌面绑定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() } } }
        }
        .presentationDetents([.medium])
    }
}
