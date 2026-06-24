import SwiftUI

/// 首启合规同意门(对标 Android `LegalConsentScreen` / 鸿蒙合规同意)。
struct LegalConsentView: View {
    @EnvironmentObject private var session: SessionManager

    var body: some View {
        VStack(spacing: Theme.Space.xl) {
            Spacer()
            Image(systemName: "checkmark.shield.fill")
                .font(.system(size: 64)).foregroundColor(Theme.brand)
            Text("欢迎使用修茈企业")
                .font(.title2).bold()
            Text("在开始前,请阅读并同意我们的服务条款与隐私政策。")
                .font(.subheadline).foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Theme.Space.xl)

            HStack(spacing: Theme.Space.lg) {
                Link("服务条款", destination: URL(string: AppConfig.legalTermsURL)!)
                Link("隐私政策", destination: URL(string: AppConfig.legalPrivacyURL)!)
            }
            .font(.footnote)

            Spacer()

            Button {
                session.acceptLegalConsent()
            } label: {
                Text("同意并继续")
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, Theme.Space.md)
            }
            .buttonStyle(.borderedProminent)
            .padding(.horizontal, Theme.Space.xl)
            .padding(.bottom, Theme.Space.xl)
        }
    }
}
