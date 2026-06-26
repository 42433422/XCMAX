import SwiftUI
import AVFoundation

@MainActor
final class ContactsViewModel: ObservableObject {
    @Published var employees: [EmployeeProfile] = []
    @Published var phase: LoadPhase = .idle
    @Published var searchQuery = ""

    /// 搜索过滤(对标 Android `filteredEmployees`:名字 / MOD 名 / AI号)。
    var filtered: [EmployeeProfile] {
        let q = searchQuery.trimmingCharacters(in: .whitespaces)
        guard !q.isEmpty else { return employees }
        return employees.filter {
            $0.name.localizedCaseInsensitiveContains(q) ||
            $0.modName.localizedCaseInsensitiveContains(q) ||
            $0.employeeId.localizedCaseInsensitiveContains(q)
        }
    }

    func load(_ api: APIClient, showError: Bool = false) async {
        if employees.isEmpty { phase = .loading }
        do {
            let data = try await api.mods()
            employees = (data.items ?? []).aiEmployeeProfiles()
            phase = employees.isEmpty ? .empty : .loaded
        } catch {
            if showError || employees.isEmpty {
                phase = .failed((error as? LocalizedError)?.errorDescription ?? error.localizedDescription)
            }
        }
    }
}

/// 通讯录(全量对标 Android `AiEmployeeListScreen`):
/// MOD → 工作流员工 → 列表搜索 + 顶栏扫码/刷新 + 空态引导;点员工先进档案页。
struct ContactsView: View {
    @EnvironmentObject private var session: SessionManager
    @StateObject private var vm = ContactsViewModel()
    @State private var showScanner = false

    private var titleText: String {
        let n = vm.filtered.count
        return n > 0 ? "AI员工(\(n))" : "AI员工"
    }

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .idle, .loading:
                    LoadingView()
                case .failed(let m):
                    ErrorStateView(message: m) { Task { await vm.load(session.api, showError: true) } }
                case .empty:
                    emptyGuide
                case .loaded:
                    list
                }
            }
            .navigationTitle(titleText)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItemGroup(placement: .navigationBarTrailing) {
                    Button { Task { await vm.load(session.api, showError: true) } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("刷新AI员工")
                    Button { showScanner = true } label: {
                        Image(systemName: "qrcode.viewfinder")
                    }
                    .accessibilityLabel("扫码绑定")
                }
            }
            .navigationDestination(for: EmployeeProfile.self) { emp in
                EmployeeProfileView(employee: emp)
            }
            .sheet(isPresented: $showScanner) {
                ScanBindSheet { code in
                    showScanner = false
                    Task {
                        await session.applyPairingQr(code)
                        await vm.load(session.api, showError: true)
                    }
                }
            }
        }
        .task { if case .idle = vm.phase { await vm.load(session.api) } }
    }

    // 列表(带搜索框 + 无结果提示)
    private var list: some View {
        List {
            Section {
                ForEach(vm.filtered) { emp in
                    NavigationLink(value: emp) {
                        employeeRow(emp)
                    }
                }
                if vm.filtered.isEmpty && !vm.searchQuery.isEmpty {
                    Text("未找到匹配的 AI 员工")
                        .font(.subheadline).foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.vertical, Theme.Space.lg)
                }
            }
        }
        .listStyle(.insetGrouped)
        .searchable(text: $vm.searchQuery, prompt: "搜索 AI 员工")
        .refreshable { await vm.load(session.api, showError: true) }
    }

    // 单行(对标 Android 列表行:头像 / 名字 / summary / contactLine + chevron)
    private func employeeRow(_ emp: EmployeeProfile) -> some View {
        HStack(spacing: Theme.Space.md) {
            AvatarView(text: emp.name, url: emp.avatarUrl, size: 44)
            VStack(alignment: .leading, spacing: 3) {
                Text(emp.name).font(.body.weight(.medium)).lineLimit(1)
                if !emp.summary.isEmpty {
                    Text(emp.summary).font(.footnote).foregroundColor(.secondary).lineLimit(1)
                }
                let contact = emp.contactLine
                if !contact.isEmpty {
                    Text(contact).font(.caption).foregroundColor(Theme.brand).lineLimit(1)
                }
            }
        }
        .padding(.vertical, 2)
    }

    // 空态引导(对标 Android 空态:图标 + 文案 + 扫码绑定按钮)
    private var emptyGuide: some View {
        VStack(spacing: Theme.Space.md) {
            Image(systemName: "sparkles")
                .font(.system(size: 34))
                .foregroundColor(Theme.brand)
                .frame(width: 64, height: 64)
                .background(Theme.brand.opacity(0.10))
                .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            Text("暂无 AI 员工").font(.subheadline)
            Text("扫码绑定企业端或登录管理端后，员工会自动同步到这里。")
                .font(.footnote).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Theme.Space.xl)
            Button {
                showScanner = true
            } label: {
                Label("扫码绑定", systemImage: "qrcode.viewfinder")
            }
            .buttonStyle(.borderedProminent)
            .padding(.top, Theme.Space.xs)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding()
    }
}

/// 扫码绑定 sheet:复用 `QRScannerView`,识别到即回调(对标 Android `onScan`)。
private struct ScanBindSheet: View {
    var onFound: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var permissionDenied = false

    var body: some View {
        NavigationStack {
            ZStack {
                if permissionDenied {
                    ErrorStateView(message: "未获得相机权限。请在「设置 → 隐私 → 相机」中开启。")
                } else {
                    QRScannerView { value in onFound(value) }
                        .ignoresSafeArea()
                    VStack {
                        Spacer()
                        Text("扫描企业端绑定码以同步 AI 员工")
                            .font(.footnote).foregroundColor(.white)
                            .padding(.horizontal, Theme.Space.lg).padding(.vertical, Theme.Space.sm)
                            .background(.black.opacity(0.5)).clipShape(Capsule())
                            .padding(.bottom, Theme.Space.xl)
                    }
                }
            }
            .navigationTitle("扫码绑定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
            .task { await checkPermission() }
        }
    }

    private func checkPermission() async {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: permissionDenied = false
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            permissionDenied = !granted
        default: permissionDenied = true
        }
    }
}
