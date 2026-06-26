import SwiftUI

/// 企业账号自助注册(全量对标 Android `RegisterScreen`)。
///
/// 对齐能力:用户名 / 密码 / 邮箱三项必填 + 协议勾选门(均满足才可提交),
/// 提交走 `api.register`;协议链接 URL 读配置而非强解包。
struct RegisterView: View {
    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss

    @State private var username = ""
    @State private var password = ""
    @State private var email = ""
    @State private var agreed = false
    @State private var passwordVisible = false
    @State private var submitting = false
    @State private var error: String?
    @State private var done = false

    // 对标 Android:u && p && e 三项非空 + 协议勾选。
    private var canSubmit: Bool {
        !username.trimmingCharacters(in: .whitespaces).isEmpty
            && !password.isEmpty
            && !email.trimmingCharacters(in: .whitespaces).isEmpty
            && agreed
            && !submitting
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("创建账号")
                    .font(.title).bold()
                Spacer().frame(height: 6)
                Text("注册 XCAGI 企业平台账号")
                    .font(.subheadline).foregroundColor(.secondary)

                Spacer().frame(height: Theme.Space.xl)

                fieldBox(placeholder: "用户名", text: $username)
                Spacer().frame(height: Theme.Space.md)
                passwordBox
                Spacer().frame(height: Theme.Space.md)
                fieldBox(placeholder: "邮箱", text: $email, keyboard: .emailAddress)

                Spacer().frame(height: Theme.Space.lg)
                consentRow

                if let e = error {
                    Spacer().frame(height: Theme.Space.md)
                    Text(e).font(.footnote).foregroundColor(.red)
                }
                if done {
                    Spacer().frame(height: Theme.Space.md)
                    Label("注册成功,请返回登录", systemImage: "checkmark.circle.fill")
                        .font(.footnote).foregroundColor(.green)
                }

                Spacer().frame(height: Theme.Space.xl)
                registerButton
            }
            .padding(.horizontal, Theme.Space.xl)
            .padding(.top, Theme.Space.xl)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Theme.screenBackground.ignoresSafeArea())
        .navigationTitle("注册")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func fieldBox(placeholder: String, text: Binding<String>, keyboard: UIKeyboardType = .default) -> some View {
        TextField(placeholder, text: text)
            .keyboardType(keyboard)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .padding(.horizontal, Theme.Space.lg)
            .frame(height: 46)
            .background(Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm))
            .overlay(
                RoundedRectangle(cornerRadius: Theme.Radius.sm)
                    .stroke(Color(uiColor: .separator), lineWidth: 1)
            )
    }

    private var passwordBox: some View {
        HStack(spacing: 0) {
            Group {
                if passwordVisible {
                    TextField("密码", text: $password)
                } else {
                    SecureField("密码", text: $password)
                }
            }
            .textContentType(.newPassword)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()

            Button {
                passwordVisible.toggle()
            } label: {
                Image(systemName: passwordVisible ? "eye.slash" : "eye")
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, Theme.Space.lg)
        .frame(height: 46)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm))
        .overlay(
            RoundedRectangle(cornerRadius: Theme.Radius.sm)
                .stroke(Color(uiColor: .separator), lineWidth: 1)
        )
    }

    private var consentRow: some View {
        HStack(spacing: 0) {
            Button {
                agreed.toggle()
            } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(agreed ? Theme.brand : Theme.cardBackground)
                        .frame(width: 16, height: 16)
                        .overlay(
                            RoundedRectangle(cornerRadius: 3)
                                .stroke(agreed ? Color.clear : Color(uiColor: .separator), lineWidth: 0.5)
                        )
                    if agreed {
                        Image(systemName: "checkmark")
                            .font(.system(size: 10, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
            }
            .buttonStyle(.plain)
            .padding(.trailing, 6)

            Text("我已阅读并同意").font(.caption2).foregroundColor(.secondary)
            if let terms = URL(string: AppConfig.legalTermsURL) {
                Link("《用户协议》", destination: terms).font(.caption2).fontWeight(.medium)
            } else {
                Text("《用户协议》").font(.caption2).fontWeight(.medium).foregroundColor(Theme.brand)
            }
            Text("和").font(.caption2).foregroundColor(.secondary)
            if let privacy = URL(string: AppConfig.legalPrivacyURL) {
                Link("《隐私政策》", destination: privacy).font(.caption2).fontWeight(.medium)
            } else {
                Text("《隐私政策》").font(.caption2).fontWeight(.medium).foregroundColor(Theme.brand)
            }
            Spacer()
        }
    }

    private var registerButton: some View {
        Button(action: submit) {
            HStack(spacing: Theme.Space.sm) {
                if submitting { ProgressView().tint(.white) }
                Text(submitting ? "注册中…" : "注册")
                    .font(.body).fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .foregroundColor(canSubmit ? .white : .secondary)
            .background(canSubmit ? Theme.brand : Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: 24))
        }
        .buttonStyle(.plain)
        .disabled(!canSubmit)
    }

    private func submit() {
        guard canSubmit else { return }
        submitting = true
        error = nil
        Task {
            do {
                _ = try await session.api.register(username: username, password: password, email: email)
                done = true
                try? await Task.sleep(nanoseconds: 900_000_000)
                dismiss()
            } catch {
                self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
            }
            submitting = false
        }
    }
}
