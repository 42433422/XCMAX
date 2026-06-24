import SwiftUI

@MainActor
final class ProfileViewModel: ObservableObject {
    @Published var wallet: WalletBalanceData?
    func load(_ api: APIClient) async {
        wallet = try? await api.walletBalance()
    }
}

/// 我的(对标 Android `ProfileScreen`):账户信息 + 钱包 + 设置入口。
struct ProfileView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ProfileViewModel()

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: Theme.Space.md) {
                        AvatarView(text: session.session.displayName.isEmpty ? "我" : session.session.displayName, size: 56)
                        VStack(alignment: .leading, spacing: 3) {
                            Text(session.session.displayName.isEmpty ? "未命名用户" : session.session.displayName)
                                .font(.headline)
                            Text(accountKindLabel).font(.caption).foregroundColor(.secondary)
                            if !session.session.companyBrand.isEmpty {
                                Text(session.session.companyBrand).font(.caption2).foregroundColor(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }

                Section("钱包") {
                    HStack {
                        Label("余额", systemImage: "creditcard")
                        Spacer()
                        Text(walletText).foregroundColor(.secondary)
                    }
                    if let level = vm.wallet?.membershipLevel, !level.isEmpty {
                        HStack { Label("会员", systemImage: "crown"); Spacer(); Text(level).foregroundColor(.secondary) }
                    }
                }

                Section("服务") {
                    NavigationRow(icon: "headphones", tint: .blue, title: "专属客服") { CsChatView() }
                    NavigationRow(icon: "checkmark.seal.fill", tint: .green, title: "我的审批") { ApprovalListView() }
                }

                Section {
                    NavigationRow(icon: "gearshape.fill", tint: .gray, title: "设置") { SettingsView() }
                }
            }
            .navigationTitle("我的")
            .task { await vm.load(session.api) }
            .refreshable { await vm.load(session.api) }
        }
    }

    private var accountKindLabel: String {
        switch session.session.accountKind {
        case "enterprise": return "企业端账号"
        case "admin": return "管理端账号"
        default: return session.session.accountKind
        }
    }

    private var walletText: String {
        guard let w = vm.wallet, let b = w.balance else { return "—" }
        return "\(w.currency ?? "¥")\(String(format: "%.2f", b))"
    }
}
