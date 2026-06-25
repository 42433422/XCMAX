import SwiftUI

/// 登录页(全量对标 Android `AuthScreen`)。
///
/// 对齐能力:
/// - 密码登录 / 手机号登录双 Tab;
/// - 手机号登录获取验证码 + 60s 冷却倒计时(`sendCode` → `loginPhone`);
/// - 服务器后台 / 企业工作台账号类型分段(密码模式);
/// - 密码显隐切换;
/// - 记住密码 / 免登录(本机持久化,冷启动自动回填);
/// - 协议勾选门(未勾不可登录),服务协议 / 隐私政策可点开(URL 读配置,非强解包);
/// - 扫码绑定/登录 + 桌面绑定码手输。
struct LoginView: View {
    @EnvironmentObject private var session: SessionManager

    private enum LoginMode { case password, phone }

    @State private var loginMode: LoginMode = .password
    @State private var username = ""
    @State private var password = ""
    @State private var phone = ""
    @State private var otpCode = ""
    @State private var adminMode = false          // true=服务器后台,false=企业工作台
    @State private var passwordVisible = false
    @State private var agreed = true
    @State private var rememberPass = false
    @State private var autoLogin = false
    @State private var isSubmitting = false
    @State private var loginError: String?

    @State private var codeCooldown = 0
    @State private var sendingCode = false
    @State private var cooldownTask: Task<Void, Never>?

    @State private var showPairing = false
    @State private var showScanner = false

    // 本机持久化(对标 Android SessionStore.savedUsername/savedPassword/rememberPass/autoLogin)。
    private enum PrefKey {
        static let username = "auth_saved_username"
        static let password = "auth_saved_password"
        static let rememberPass = "auth_remember_pass"
        static let autoLogin = "auth_auto_login"
    }

    private var canLogin: Bool {
        guard agreed, !isSubmitting else { return false }
        switch loginMode {
        case .password:
            return !username.trimmingCharacters(in: .whitespaces).isEmpty && !password.isEmpty
        case .phone:
            return phone.count == 11 && otpCode.count >= 4
        }
    }

    private var loginButtonTitle: String {
        if isSubmitting { return "登录中…" }
        if loginMode == .password && adminMode { return "进入服务器后台" }
        if loginMode == .password { return "进入企业工作台" }
        return "登录"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 0) {
                    header

                    modeTabs
                        .padding(.horizontal, Theme.Space.xl)
                    Spacer().frame(height: Theme.Space.lg)

                    if loginMode == .password {
                        accountKindSegment
                            .padding(.horizontal, Theme.Space.xl)
                        Spacer().frame(height: Theme.Space.md)
                    }

                    inputs
                        .padding(.horizontal, Theme.Space.xl)

                    if let err = loginError {
                        Text(err)
                            .font(.footnote).foregroundColor(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, Theme.Space.xl)
                            .padding(.top, Theme.Space.md)
                    }

                    Spacer().frame(height: Theme.Space.lg)

                    loginButton
                        .padding(.horizontal, Theme.Space.xl)

                    Spacer().frame(height: Theme.Space.md)
                    scanButton
                        .padding(.horizontal, Theme.Space.xl)

                    if loginMode == .password {
                        Spacer().frame(height: Theme.Space.md)
                        rememberRow
                            .padding(.horizontal, Theme.Space.xl)
                    }

                    Spacer().frame(height: Theme.Space.lg)
                    consentRow
                        .padding(.horizontal, Theme.Space.xl)

                    Spacer().frame(height: Theme.Space.md)
                    NavigationLink {
                        RegisterView()
                    } label: {
                        Text("没有账号?注册企业账号")
                            .font(.footnote).foregroundColor(Theme.brand)
                    }
                    .padding(.bottom, Theme.Space.xl)
                }
                .padding(.top, Theme.Space.xl)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Theme.screenBackground.ignoresSafeArea())
            .navigationTitle("")
            .sheet(isPresented: $showPairing) { PairingSheet() }
            .sheet(isPresented: $showScanner) {
                NavigationStack { ScanQrView() }
            }
            .onAppear(perform: restoreSavedCredentials)
            .onDisappear { cooldownTask?.cancel() }
        }
    }

    // MARK: - 头部

    private var header: some View {
        VStack(spacing: Theme.Space.sm) {
            Image("Logo")
                .resizable()
                .scaledToFit()
                .frame(width: 72, height: 72)
                .clipShape(RoundedRectangle(cornerRadius: 18))
            Text("XCAGI 手机控制端")
                .font(.title2).bold()
            Text("连接服务器后台、企业工作台和电脑执行端")
                .font(.caption).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(.bottom, Theme.Space.xl)
    }

    // MARK: - 密码 / 手机号 Tab

    private var modeTabs: some View {
        HStack(spacing: Theme.Space.lg) {
            tab(title: "密码登录", mode: .password)
            tab(title: "手机号登录", mode: .phone)
        }
    }

    private func tab(title: String, mode: LoginMode) -> some View {
        let selected = loginMode == mode
        return VStack(spacing: 6) {
            Text(title)
                .font(.body)
                .fontWeight(selected ? .semibold : .regular)
                .foregroundColor(selected ? .primary : .secondary)
            Rectangle()
                .fill(selected ? Theme.brand : Color.clear)
                .frame(height: 2.5)
                .clipShape(Capsule())
        }
        .frame(maxWidth: .infinity)
        .contentShape(Rectangle())
        .onTapGesture {
            loginError = nil
            loginMode = mode
        }
    }

    // MARK: - 账号类型分段(服务器后台 / 企业工作台)

    private var accountKindSegment: some View {
        HStack(spacing: Theme.Space.xs) {
            segmentItem(title: "服务器后台", selected: adminMode) { adminMode = true }
            segmentItem(title: "企业工作台", selected: !adminMode) { adminMode = false }
        }
        .padding(4)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 18))
        .overlay(
            RoundedRectangle(cornerRadius: 18)
                .stroke(Color(uiColor: .separator), lineWidth: 0.5)
        )
    }

    private func segmentItem(title: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.subheadline).fontWeight(.medium)
                .foregroundColor(selected ? .white : .secondary)
                .frame(maxWidth: .infinity)
                .frame(height: 36)
                .background(selected ? Theme.brand : Color.clear)
                .clipShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }

    // MARK: - 输入区

    @ViewBuilder
    private var inputs: some View {
        if loginMode == .password {
            VStack(spacing: Theme.Space.md) {
                inputBox(
                    placeholder: adminMode ? "管理员账号" : "账号或邮箱",
                    text: $username
                )
                passwordBox
            }
        } else {
            VStack(spacing: Theme.Space.sm) {
                inputBox(placeholder: "请输入手机号", text: $phone, keyboard: .numberPad)
                    .onChange(of: phone) { newValue in
                        let digits = String(newValue.filter(\.isNumber).prefix(11))
                        if digits != phone { phone = digits }
                    }
                otpField
            }
        }
    }

    private func inputBox(placeholder: String, text: Binding<String>, keyboard: UIKeyboardType = .default) -> some View {
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
            .textContentType(.password)
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

    private var otpField: some View {
        HStack(spacing: Theme.Space.sm) {
            TextField("验证码", text: $otpCode)
                .keyboardType(.numberPad)
                .onChange(of: otpCode) { newValue in
                    let digits = String(newValue.filter(\.isNumber).prefix(6))
                    if digits != otpCode { otpCode = digits }
                }
                .padding(.horizontal, Theme.Space.lg)
                .frame(height: 46)
                .background(Theme.cardBackground)
                .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.sm))
                .overlay(
                    RoundedRectangle(cornerRadius: Theme.Radius.sm)
                        .stroke(Color(uiColor: .separator), lineWidth: 1)
                )

            Button(action: sendCode) {
                Text(otpActionLabel)
                    .font(.subheadline).fontWeight(.medium)
                    .foregroundColor(otpActionEnabled ? Theme.brand : .secondary)
                    .frame(width: 110, height: 46)
                    .background(
                        RoundedRectangle(cornerRadius: Theme.Radius.sm)
                            .stroke(otpActionEnabled ? Theme.brand : Color(uiColor: .separator), lineWidth: 1)
                    )
            }
            .buttonStyle(.plain)
            .disabled(!otpActionEnabled)
        }
    }

    private var otpActionLabel: String {
        if sendingCode { return "发送中…" }
        if codeCooldown > 0 { return "\(codeCooldown)s 后重发" }
        return "获取验证码"
    }

    private var otpActionEnabled: Bool {
        phone.count == 11 && codeCooldown == 0 && !sendingCode
    }

    // MARK: - 登录按钮

    private var loginButton: some View {
        Button(action: submit) {
            HStack(spacing: Theme.Space.sm) {
                if isSubmitting { ProgressView().tint(.white) }
                Text(loginButtonTitle)
                    .font(.body).fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .frame(height: 48)
            .foregroundColor(canLogin ? .white : .secondary)
            .background(canLogin ? Theme.brand : Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: 24))
        }
        .buttonStyle(.plain)
        .disabled(!canLogin)
    }

    private var scanButton: some View {
        Menu {
            Button {
                showScanner = true
            } label: {
                Label("扫描二维码", systemImage: "qrcode.viewfinder")
            }
            Button {
                showPairing = true
            } label: {
                Label("输入桌面绑定码", systemImage: "number")
            }
        } label: {
            HStack(spacing: Theme.Space.sm) {
                Image(systemName: "qrcode.viewfinder")
                Text("扫码绑定/登录").fontWeight(.medium)
            }
            .font(.subheadline)
            .foregroundColor(Theme.brand)
            .frame(maxWidth: .infinity)
            .frame(height: 44)
            .background(Theme.brand.opacity(0.06))
            .clipShape(RoundedRectangle(cornerRadius: 22))
            .overlay(
                RoundedRectangle(cornerRadius: 22)
                    .stroke(Theme.brand.opacity(0.35), lineWidth: 0.5)
            )
        }
    }

    // MARK: - 记住密码 / 免登录

    private var rememberRow: some View {
        HStack(spacing: Theme.Space.xl) {
            Spacer()
            checkbox(checked: rememberPass, label: "记住密码") { rememberPass.toggle() }
            checkbox(checked: autoLogin, label: "免登录") { autoLogin.toggle() }
        }
    }

    private func checkbox(checked: Bool, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                ZStack {
                    RoundedRectangle(cornerRadius: 3)
                        .fill(checked ? Theme.brand : Theme.cardBackground)
                        .frame(width: 18, height: 18)
                        .overlay(
                            RoundedRectangle(cornerRadius: 3)
                                .stroke(checked ? Color.clear : Color(uiColor: .separator), lineWidth: 0.5)
                        )
                    if checked {
                        Image(systemName: "checkmark")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                Text(label).font(.subheadline).foregroundColor(.secondary)
            }
        }
        .buttonStyle(.plain)
    }

    // MARK: - 协议勾选

    private var consentRow: some View {
        HStack(spacing: 0) {
            Button {
                agreed.toggle()
            } label: {
                ZStack {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(agreed ? Theme.brand : Theme.cardBackground)
                        .frame(width: 20, height: 20)
                        .overlay(
                            RoundedRectangle(cornerRadius: 4)
                                .stroke(agreed ? Color.clear : Color(uiColor: .separator), lineWidth: 0.5)
                        )
                    if agreed {
                        Image(systemName: "checkmark")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
            }
            .buttonStyle(.plain)
            .padding(.trailing, Theme.Space.sm)

            Text("已阅读并同意 ").font(.caption).foregroundColor(.secondary)
            if let terms = URL(string: AppConfig.legalTermsURL) {
                Link("服务协议", destination: terms).font(.caption).fontWeight(.medium)
            } else {
                Text("服务协议").font(.caption).fontWeight(.medium).foregroundColor(Theme.brand)
            }
            Text(" 和 ").font(.caption).foregroundColor(.secondary)
            if let privacy = URL(string: AppConfig.legalPrivacyURL) {
                Link("隐私政策", destination: privacy).font(.caption).fontWeight(.medium)
            } else {
                Text("隐私政策").font(.caption).fontWeight(.medium).foregroundColor(Theme.brand)
            }
            Spacer()
        }
    }

    // MARK: - 行为

    private func restoreSavedCredentials() {
        let d = UserDefaults.standard
        rememberPass = d.bool(forKey: PrefKey.rememberPass)
        autoLogin = d.bool(forKey: PrefKey.autoLogin)
        if rememberPass {
            username = d.string(forKey: PrefKey.username) ?? ""
            password = d.string(forKey: PrefKey.password) ?? ""
        }
    }

    private func persistCredentials() {
        let d = UserDefaults.standard
        d.set(rememberPass, forKey: PrefKey.rememberPass)
        d.set(autoLogin, forKey: PrefKey.autoLogin)
        if rememberPass {
            d.set(username, forKey: PrefKey.username)
            d.set(password, forKey: PrefKey.password)
        } else {
            d.removeObject(forKey: PrefKey.username)
            d.removeObject(forKey: PrefKey.password)
        }
    }

    private func sendCode() {
        guard otpActionEnabled, phone.count == 11 else { return }
        sendingCode = true
        loginError = nil
        Task {
            let ok = await session.sendPhoneCode(phone: phone)
            sendingCode = false
            if ok {
                startCooldown()
            } else {
                loginError = session.lastError ?? "验证码发送失败"
            }
        }
    }

    private func startCooldown() {
        cooldownTask?.cancel()
        codeCooldown = 60
        cooldownTask = Task {
            while codeCooldown > 0 {
                try? await Task.sleep(nanoseconds: 1_000_000_000)
                if Task.isCancelled { return }
                if codeCooldown > 0 { codeCooldown -= 1 }
            }
        }
    }

    private func submit() {
        guard canLogin else { return }
        isSubmitting = true
        loginError = nil
        Task {
            switch loginMode {
            case .password:
                let kind = adminMode ? "admin" : "enterprise"
                await session.login(username: username, password: password, loginAccountKind: kind)
            case .phone:
                await session.loginWithPhone(phone: phone, code: otpCode)
            }
            isSubmitting = false
            if session.phase == .main {
                if loginMode == .password { persistCredentials() }
            } else {
                loginError = session.lastError ?? {
                    switch loginMode {
                    case .password: return adminMode ? "服务器后台账号或密码错误" : "用户名或密码错误"
                    case .phone: return "验证码错误或已过期"
                    }
                }()
            }
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
