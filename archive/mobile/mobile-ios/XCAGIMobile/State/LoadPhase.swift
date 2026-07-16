import Foundation

/// 通用列表/详情加载阶段。
enum LoadPhase: Equatable {
    case idle
    case loading
    case loaded
    case empty
    case failed(String)
}
