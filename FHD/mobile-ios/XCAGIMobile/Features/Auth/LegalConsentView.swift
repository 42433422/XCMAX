import SwiftUI

/// 首启合规同意门(全量对标 Android `LegalConsentScreen` / 鸿蒙合规同意)。
///
/// 对齐能力:品牌蓝满屏背景 + Logo + 标题/副标题;协议勾选门控
/// (未勾不可进入,按钮文案随状态:已勾「进入 XCAGI」/ 未勾「请先同意协议」);
/// 《用户协议》《隐私政策》URL 读配置而非强解包。
struct LegalConsentView: View {
    @EnvironmentObject private var session: SessionManager
    @State private var checked = false

    private var termsURL: URL? { URL(string: AppConfig.legalTermsURL) }
    private var privacyURL: URL? { URL(string: AppConfig.legalPrivacyURL) }

    var body: some View {
        ZStack {
            Theme.brand.ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()

                // Logo
                ZStack {
                    RoundedRectangle(cornerRadius: 22)
                        .fill(Color.white.opacity(0.15))
                        .frame(width: 88, height: 88)
                    Image("Logo")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 64, height: 64)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                }

                Spacer().frame(height: Theme.Space.xl)

                Text("XCAGI")
                    .font(.system(size: 40, weight: .bold))
                    .foregroundColor(.white)
                    .tracking(2)

                Spacer().frame(height: 6)

                Text("企业智能工作平台")
                    .font(.footnote)
                    .foregroundColor(.white.opacity(0.7))

                Spacer()

                // 协议勾选
                Button {
                    checked.toggle()
                } label: {
                    HStack(spacing: Theme.Space.sm) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(checked ? Color.white : Color.white.opacity(0.2))
                                .frame(width: 18, height: 18)
                            if checked {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 11, weight: .bold))
                                    .foregroundColor(Theme.brand)
                            }
                        }
                        consentText
                    }
                }
                .buttonStyle(.plain)

                Spacer().frame(height: Theme.Space.lg)

                // 进入按钮(文案 / 可用态随勾选)
                Button {
                    guard checked else { return }
                    session.acceptLegalConsent()
                } label: {
                    Text(checked ? "进入 XCAGI" : "请先同意协议")
                        .font(.body).fontWeight(.medium)
                        .foregroundColor(checked ? Theme.brand : Color.white.opacity(0.5))
                        .frame(maxWidth: .infinity)
                        .frame(height: 48)
                        .background(checked ? Color.white : Color.white.opacity(0.2))
                        .clipShape(RoundedRectangle(cornerRadius: 24))
                }
                .buttonStyle(.plain)
                .disabled(!checked)

                Spacer().frame(height: Theme.Space.xl)
            }
            .padding(.horizontal, Theme.Space.xl)
        }
    }

    /// "我已阅读并同意《用户协议》和《隐私政策》",协议名可点开(URL 读配置)。
    private var consentText: some View {
        HStack(spacing: 0) {
            Text("我已阅读并同意")
                .font(.caption).foregroundColor(.white.opacity(0.6))
            link("《用户协议》", url: termsURL)
            Text("和").font(.caption).foregroundColor(.white.opacity(0.6))
            link("《隐私政策》", url: privacyURL)
        }
    }

    @ViewBuilder
    private func link(_ title: String, url: URL?) -> some View {
        if let url {
            Link(title, destination: url)
                .font(.caption).foregroundColor(.white)
                .underline()
        } else {
            Text(title).font(.caption).foregroundColor(.white).underline()
        }
    }
}
