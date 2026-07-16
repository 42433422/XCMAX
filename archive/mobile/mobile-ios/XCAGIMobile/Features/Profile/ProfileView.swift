import SwiftUI

@MainActor
final class ProfileViewModel: ObservableObject {
    @Published var wallet: WalletBalanceData?
    /// 真实头像 URL(经 me() 拉取,对标 Android userAvatarSource)。
    @Published var avatarUrl: String = ""
    /// 立即同步状态(对标 Android homeHub.syncing)。
    @Published var syncing = false
    /// 一次性提示(同步/保存结果),对标 Android snack。
    @Published var toast: String?

    func load(_ api: APIClient) async {
        wallet = try? await api.walletBalance()
        if let url = try? await api.me().user?.avatarUrl, !url.isEmpty {
            avatarUrl = url
        }
    }

    /// 静默刷新余额(对标 Android LifecycleResumeEffect 进页拉取)。
    func refreshWallet(_ api: APIClient) async {
        if let w = try? await api.walletBalance() { wallet = w }
    }

    /// 立即同步:健康探测 + 刷新钱包(iOS 同步真相源即钱包/会话,对标 Android runSyncNow)。
    func syncNow(_ session: SessionManager) async {
        guard !syncing else { return }
        syncing = true
        _ = await session.isHostOnline()
        await refreshWallet(session.api)
        syncing = false
        toast = "同步完成"
    }
}

/// 我的(对标 Android `ProfileScreen`):账户信息 + 钱包卡(余额/会员/经验/BYOK)+ 扫码绑定 + 设置/关于 + 账号管理(退出/注销)+ ICP 备案合规页脚。
struct ProfileView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ProfileViewModel()

    @State private var showProfileEditor = false
    @State private var showDelete = false
    @State private var deletePassword = ""

    /// App 备案号(对标 Android strings.xml `app_filing_number`,工信部备案已通过)。
    static let appFilingNumber = "蜀ICP备2026014056号-3A"

    var body: some View {
        NavigationStack {
            List {
                // ── 用户信息区:头像 + 名称 + 账号类型 + 连接 + 同步胶囊;点进编辑资料 ──
                Section {
                    Button {
                        showProfileEditor = true
                    } label: {
                        HStack(spacing: Theme.Space.md) {
                            ZStack(alignment: .bottomTrailing) {
                                AvatarView(
                                    text: displayName,
                                    url: vm.avatarUrl.isEmpty ? nil : vm.avatarUrl,
                                    fallback: .user,
                                    size: 56,
                                    cornerRadius: MessageAvatarLayout.headerAvatarCornerRadius
                                )
                                Image(systemName: "photo.fill")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundColor(.white)
                                    .frame(width: 18, height: 18)
                                    .background(Theme.brand)
                                    .clipShape(Circle())
                                    .overlay(Circle().stroke(Theme.cardBackground, lineWidth: 2))
                            }
                            VStack(alignment: .leading, spacing: 3) {
                                Text(displayName).font(.headline).foregroundColor(.primary)
                                Text(accountKindLabel).font(.caption).foregroundColor(.secondary)
                                Text(serverModeLabel).font(.caption2).foregroundColor(.secondary)
                                syncPill.padding(.top, 2)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption).foregroundColor(.secondary.opacity(0.5))
                        }
                        .padding(.vertical, 4)
                    }
                    .buttonStyle(.plain)
                }

                // ── 钱包卡:余额 + 会员等级 + 经验值 + BYOK ──
                Section {
                    WalletBalanceCard(wallet: vm.wallet) {
                        Task { await vm.refreshWallet(session.api) }
                    }
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                }

                Section("服务") {
                    NavigationRow(icon: "qrcode.viewfinder", tint: .indigo, title: "扫码绑定") { ScanQrView() }
                    NavigationRow(icon: "headphones", tint: .blue, title: "专属客服") { CsChatView() }
                    NavigationRow(icon: "checkmark.seal.fill", tint: .green, title: "我的审批") { ApprovalListView() }
                }

                Section {
                    NavigationRow(icon: "gearshape.fill", tint: .gray, title: "设置") { SettingsView() }
                }

                // ── 账号管理:退出登录 + 注销账号(密码确认,App Store 硬要求) ──
                Section("账号管理") {
                    Button(role: .destructive) { session.logout() } label: {
                        Text("退出登录").frame(maxWidth: .infinity)
                    }
                    Button(role: .destructive) { showDelete = true } label: {
                        Text("注销账号").frame(maxWidth: .infinity)
                    }
                }

                // ── 合规页脚:版本号 + ICP 备案号 ──
                Section {
                    VStack(spacing: 4) {
                        Text("版本 \(appVersion)")
                            .font(.caption2).foregroundColor(.secondary)
                        Text(Self.appFilingNumber)
                            .font(.caption2).foregroundColor(.secondary)
                        Text(AppConfig.companyName)
                            .font(.caption2).foregroundColor(Color.secondary.opacity(0.7))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 6)
                    .listRowBackground(Color.clear)
                }
            }
            .navigationTitle("我的")
            .task { await vm.load(session.api) }
            .refreshable { await vm.load(session.api) }
            .sheet(isPresented: $showProfileEditor) {
                ProfileEditorSheet(
                    displayName: displayName,
                    avatarUrl: vm.avatarUrl
                ) { newName in
                    saveDisplayName(newName)
                    showProfileEditor = false
                }
            }
            .alert("注销账号", isPresented: $showDelete) {
                SecureField("密码", text: $deletePassword)
                Button("确认注销", role: .destructive) {
                    let pwd = deletePassword
                    deletePassword = ""
                    Task { await session.deleteAccount(password: pwd) }
                }
                Button("取消", role: .cancel) { deletePassword = "" }
            } message: {
                Text("注销后无法恢复,请确认密码。")
            }
            .overlay(alignment: .bottom) {
                if let toast = vm.toast {
                    Text(toast)
                        .font(.footnote).foregroundColor(.white)
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(Color.black.opacity(0.8))
                        .clipShape(Capsule())
                        .padding(.bottom, 24)
                        .transition(.opacity)
                        .task {
                            try? await Task.sleep(nanoseconds: 1_600_000_000)
                            vm.toast = nil
                        }
                }
            }
        }
    }

    // MARK: - 同步胶囊(对标 Android StatusPill)

    private var syncPill: some View {
        Button {
            Task { await vm.syncNow(session) }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.triangle.2.circlepath")
                    .font(.system(size: 11))
                Text(vm.syncing ? "同步中…" : "立即同步")
                    .font(.caption2)
            }
            .padding(.horizontal, 10).padding(.vertical, 4)
            .overlay(Capsule().stroke(Color.secondary.opacity(0.3), lineWidth: 0.5))
            .foregroundColor(vm.syncing ? Theme.brand : .secondary)
        }
        .buttonStyle(.plain)
        .disabled(vm.syncing)
    }

    // MARK: - 衍生值

    private var displayName: String {
        session.session.displayName.isEmpty ? "未登录" : session.session.displayName
    }

    private var accountKindLabel: String {
        switch session.session.accountKind {
        case "enterprise": return "企业端账号"
        case "admin": return "管理端账号"
        default: return session.session.accountKind
        }
    }

    private var serverModeLabel: String {
        session.resolvedBaseURL.contains("xiu-ci.com") ? "云端服务" : "桌面端 · 局域网"
    }

    private var appVersion: String {
        let v = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
        let b = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
        return "\(v) (\(b))"
    }

    private func saveDisplayName(_ name: String) {
        let clean = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }
        session.session.displayName = String(clean.prefix(32))
        SessionStore.shared.saveSession(session.session)
        vm.toast = "资料已保存"
    }
}

// MARK: - 钱包余额卡(对标 Android WalletBalanceCard)

/// 余额 + 会员等级 + 经验值 + BYOK,渐变蓝底,点击刷新。
private struct WalletBalanceCard: View {
    let wallet: WalletBalanceData?
    let onRefresh: () -> Void

    private var balanceText: String {
        guard let b = wallet?.balance else { return "—" }
        return Self.balanceFormatter.string(from: NSNumber(value: b)) ?? String(format: "%.2f", b)
    }

    /// 千分位 + 两位小数(对标 Android DecimalFormat("#,##0.00"))。
    private static let balanceFormatter: NumberFormatter = {
        let f = NumberFormatter()
        f.numberStyle = .decimal
        f.minimumFractionDigits = 2
        f.maximumFractionDigits = 2
        return f
    }()
    private var currency: String {
        let c = wallet?.currency?.trimmingCharacters(in: .whitespaces) ?? ""
        return c.isEmpty ? "CNY" : c
    }
    private var membership: String { wallet?.membershipLevel?.nilIfBlank ?? "未开通" }
    private var experience: String { wallet?.experience.map(String.init) ?? "—" }
    private var byok: String { wallet?.byokConfigured == true ? "已开通" : "未开通" }

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.Space.md) {
            HStack {
                Text("账户余额").font(.caption).foregroundColor(.white.opacity(0.85))
                Spacer()
                Button(action: onRefresh) {
                    Image(systemName: "arrow.clockwise")
                        .font(.caption).foregroundColor(.white.opacity(0.85))
                }
                .buttonStyle(.plain)
            }
            HStack(alignment: .lastTextBaseline, spacing: 4) {
                Text(balanceText)
                    .font(.system(size: 30, weight: .semibold)).foregroundColor(.white)
                Text(currency)
                    .font(.caption).foregroundColor(.white.opacity(0.85))
            }
            HStack {
                metric("会员等级", membership)
                Spacer()
                metric("经验值", experience)
                Spacer()
                metric("BYOK", byok)
            }
            if wallet?.synced == false, let msg = wallet?.message?.nilIfBlank {
                Text(msg).font(.caption2).foregroundColor(.white.opacity(0.7))
            }
        }
        .padding(Theme.Space.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            LinearGradient(
                colors: [Theme.brand, Theme.brand.opacity(0.72)],
                startPoint: .topLeading, endPoint: .bottomTrailing
            )
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.Radius.lg))
        .contentShape(Rectangle())
        .onTapGesture(perform: onRefresh)
        .padding(.horizontal, Theme.Space.lg)
        .padding(.vertical, Theme.Space.sm)
    }

    private func metric(_ label: String, _ value: String) -> some View {
        VStack(spacing: 2) {
            Text(label).font(.caption2).foregroundColor(.white.opacity(0.7))
            Text(value).font(.subheadline.weight(.medium)).foregroundColor(.white)
        }
    }
}

// MARK: - 编辑资料(对标 Android ProfileEditorDialog)

/// 昵称编辑(头像展示;头像更换在 iOS 走真机相册后续接入,此处只读展示)。
private struct ProfileEditorSheet: View {
    let displayName: String
    let avatarUrl: String
    let onSave: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var draft: String = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    HStack {
                        Spacer()
                        AvatarView(text: draft.isEmpty ? displayName : draft,
                                   url: avatarUrl.isEmpty ? nil : avatarUrl,
                                   fallback: .user,
                                   size: 76,
                                   cornerRadius: MessageAvatarLayout.emptyStateAvatarCornerRadius)
                        Spacer()
                    }
                    .listRowBackground(Color.clear)
                }
                Section("昵称") {
                    TextField("昵称", text: $draft)
                        .onChange(of: draft) { newValue in
                            if newValue.count > 32 { draft = String(newValue.prefix(32)) }
                        }
                    HStack {
                        Spacer()
                        Text("\(draft.count)/32").font(.caption2).foregroundColor(.secondary)
                    }
                }
            }
            .navigationTitle("个人资料")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") { onSave(draft) }
                        .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
            .onAppear { draft = displayName == "未登录" ? "" : displayName }
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let t = trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }
}
