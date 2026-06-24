import SwiftUI

/// 企业账号自助注册(对标 Android `RegisterScreen`)。
struct RegisterView: View {
    @EnvironmentObject private var session: SessionManager
    @Environment(\.dismiss) private var dismiss

    @State private var username = ""
    @State private var password = ""
    @State private var email = ""
    @State private var submitting = false
    @State private var error: String?
    @State private var done = false

    private var canSubmit: Bool {
        !username.trimmingCharacters(in: .whitespaces).isEmpty && password.count >= 6 && !submitting
    }

    var body: some View {
        Form {
            Section {
                Text("注册 XCAGI 企业平台账号")
                    .font(.subheadline).foregroundColor(.secondary)
            }
            Section("账号信息") {
                TextField("用户名", text: $username)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                SecureField("密码(至少 6 位)", text: $password)
                TextField("邮箱(可选)", text: $email)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.emailAddress)
            }
            if let e = error {
                Section { Text(e).font(.footnote).foregroundColor(.red) }
            }
            if done {
                Section { Label("注册成功,请返回登录", systemImage: "checkmark.circle.fill").foregroundColor(.green) }
            }
            Section {
                Button(action: submit) {
                    HStack {
                        if submitting { ProgressView() }
                        Text(submitting ? "注册中…" : "注册").frame(maxWidth: .infinity)
                    }
                }
                .disabled(!canSubmit)
            }
        }
        .navigationTitle("注册")
        .navigationBarTitleDisplayMode(.inline)
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
