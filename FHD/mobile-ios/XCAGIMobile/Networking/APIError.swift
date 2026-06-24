import Foundation

/// 网络层错误(带可读中文消息,直接可上屏)。
enum APIError: LocalizedError {
    case invalidURL
    case transport(String)
    case http(status: Int, message: String)
    case decoding(String)
    case business(String)   // success == false 的业务错误

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "无效的请求地址"
        case .transport(let m): return m.isEmpty ? "网络连接失败" : m
        case .http(let status, let m): return m.isEmpty ? "请求失败(HTTP \(status))" : m
        case .decoding(let m): return "数据解析失败:\(m)"
        case .business(let m): return m.isEmpty ? "请求失败" : m
        }
    }
}

/// HTTP 方法。
enum HTTPMethod: String {
    case get = "GET"
    case post = "POST"
    case put = "PUT"
    case delete = "DELETE"
}
