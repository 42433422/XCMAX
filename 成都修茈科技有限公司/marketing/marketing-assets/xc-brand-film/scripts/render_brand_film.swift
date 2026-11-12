import AppKit
import AVFoundation
import CoreImage
import CoreMedia
import CoreVideo
import Foundation

let width = 1920
let height = 1080
let fps: Int32 = 30
let duration = 18.0
let frameCount = Int(duration * Double(fps))

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: render_brand_film <project-root>\n", stderr)
    exit(2)
}

let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let assets = root.appendingPathComponent("assets", isDirectory: true)
let output = root.appendingPathComponent("output", isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

let silentURL = output.appendingPathComponent("xc-brand-film-silent.mp4")
let finalURL = output.appendingPathComponent("xc-brand-film-1080p.mp4")
let audioURL = output.appendingPathComponent("xc-brand-film-soundtrack.wav")
let posterURL = output.appendingPathComponent("xc-brand-film-poster.png")

for url in [silentURL, finalURL, posterURL] {
    try? FileManager.default.removeItem(at: url)
}

func cgImage(named name: String) -> CGImage {
    let url = assets.appendingPathComponent(name)
    guard
        let image = NSImage(contentsOf: url),
        let cg = image.cgImage(forProposedRect: nil, context: nil, hints: nil)
    else {
        fatalError("Cannot load image: \(url.path)")
    }
    return cg
}

let logo = cgImage(named: "logo-glow.png")
let workbench = cgImage(named: "scene-02-workbench.png")
let document = cgImage(named: "scene-03-document.png")
let support = cgImage(named: "scene-03-support.png")
let report = cgImage(named: "scene-03-report.png")
let founder = cgImage(named: "scene-04-founder-team.png")

let colorSpace = CGColorSpaceCreateDeviceRGB()
let ice = NSColor(calibratedRed: 0.18, green: 0.79, blue: 1.0, alpha: 1.0)
let cyan = NSColor(calibratedRed: 0.0, green: 0.58, blue: 0.94, alpha: 1.0)
let white = NSColor(calibratedWhite: 0.98, alpha: 1.0)

func clamp(_ value: Double, _ low: Double = 0.0, _ high: Double = 1.0) -> Double {
    min(max(value, low), high)
}

func ease(_ value: Double) -> Double {
    let x = clamp(value)
    return x * x * (3.0 - 2.0 * x)
}

func easeOut(_ value: Double) -> Double {
    let x = clamp(value)
    return 1.0 - pow(1.0 - x, 3.0)
}

func hash(_ value: Int) -> Double {
    let x = sin(Double(value) * 91.337 + 17.171) * 43758.5453
    return x - floor(x)
}

func roundedPath(_ rect: CGRect, radius: CGFloat) -> CGPath {
    CGPath(
        roundedRect: rect,
        cornerWidth: radius,
        cornerHeight: radius,
        transform: nil
    )
}

func drawCover(
    _ image: CGImage,
    in ctx: CGContext,
    zoom: CGFloat = 1.0,
    panX: CGFloat = 0.0,
    panY: CGFloat = 0.0,
    alpha: CGFloat = 1.0
) {
    let imageRatio = CGFloat(image.width) / CGFloat(image.height)
    let targetRatio = CGFloat(width) / CGFloat(height)
    var drawWidth: CGFloat
    var drawHeight: CGFloat
    if imageRatio > targetRatio {
        drawHeight = CGFloat(height)
        drawWidth = drawHeight * imageRatio
    } else {
        drawWidth = CGFloat(width)
        drawHeight = drawWidth / imageRatio
    }
    drawWidth *= zoom
    drawHeight *= zoom
    let rect = CGRect(
        x: (CGFloat(width) - drawWidth) / 2.0 + panX,
        y: (CGFloat(height) - drawHeight) / 2.0 + panY,
        width: drawWidth,
        height: drawHeight
    )
    ctx.saveGState()
    ctx.setAlpha(alpha)
    ctx.interpolationQuality = .high
    ctx.draw(image, in: rect)
    ctx.restoreGState()
}

func drawVignette(_ ctx: CGContext, strength: CGFloat = 0.72) {
    let colors = [
        NSColor(calibratedWhite: 0.0, alpha: 0.0).cgColor,
        NSColor(calibratedWhite: 0.0, alpha: strength).cgColor,
    ] as CFArray
    let locations: [CGFloat] = [0.45, 1.0]
    guard let gradient = CGGradient(colorsSpace: colorSpace, colors: colors, locations: locations) else { return }
    ctx.drawRadialGradient(
        gradient,
        startCenter: CGPoint(x: width / 2, y: height / 2),
        startRadius: 80,
        endCenter: CGPoint(x: width / 2, y: height / 2),
        endRadius: 1120,
        options: [.drawsAfterEndLocation]
    )
}

func drawText(
    _ text: String,
    in rect: CGRect,
    font: NSFont,
    color: NSColor,
    alignment: NSTextAlignment = .center,
    tracking: CGFloat = 0.0
) {
    let style = NSMutableParagraphStyle()
    style.alignment = alignment
    style.lineBreakMode = .byWordWrapping
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.78)
    shadow.shadowBlurRadius = 16
    shadow.shadowOffset = NSSize(width: 0, height: -3)
    let attributes: [NSAttributedString.Key: Any] = [
        .font: font,
        .foregroundColor: color,
        .paragraphStyle: style,
        .kern: tracking,
        .shadow: shadow,
    ]
    NSAttributedString(string: text, attributes: attributes).draw(in: rect)
}

func drawSubtitle(_ ctx: CGContext, text: String, alpha: CGFloat = 1.0) {
    let font = NSFont(name: "PingFang SC Semibold", size: 58) ?? NSFont.boldSystemFont(ofSize: 58)
    let lineWidth: CGFloat = text.count > 13 ? 920 : 760
    let panel = CGRect(x: (CGFloat(width) - lineWidth) / 2, y: 66, width: lineWidth, height: 108)

    ctx.saveGState()
    ctx.setAlpha(alpha)
    ctx.setFillColor(NSColor(calibratedWhite: 0.0, alpha: 0.48).cgColor)
    ctx.addPath(roundedPath(panel, radius: 12))
    ctx.fillPath()
    ctx.setFillColor(ice.withAlphaComponent(0.92).cgColor)
    ctx.fill(CGRect(x: panel.minX + 34, y: panel.minY + 24, width: 5, height: 60))

    let graphics = NSGraphicsContext(cgContext: ctx, flipped: false)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = graphics
    drawText(
        text,
        in: CGRect(x: panel.minX + 50, y: panel.minY + 20, width: panel.width - 78, height: 75),
        font: font,
        color: white
    )
    NSGraphicsContext.restoreGraphicsState()
    ctx.restoreGState()
}

func drawLogo(_ ctx: CGContext, rect: CGRect, alpha: CGFloat, reveal: CGFloat = 1.0, glow: CGFloat = 1.0) {
    ctx.saveGState()
    ctx.clip(to: CGRect(x: rect.minX, y: rect.minY, width: rect.width * clamp(reveal), height: rect.height))
    if glow > 0.01 {
        for radius in stride(from: 34.0, through: 8.0, by: -7.0) {
            ctx.saveGState()
            ctx.setShadow(
                offset: .zero,
                blur: CGFloat(radius) * glow,
                color: ice.withAlphaComponent(CGFloat(0.055 + radius / 1300.0) * alpha).cgColor
            )
            ctx.setAlpha(alpha * 0.30)
            ctx.draw(logo, in: rect)
            ctx.restoreGState()
        }
    }
    ctx.setAlpha(alpha)
    ctx.draw(logo, in: rect)
    ctx.restoreGState()
}

func drawLightTrails(_ ctx: CGContext, t: Double, convergence: Double) {
    for index in 0..<26 {
        let lane = hash(index * 3)
        let phase = hash(index * 7 + 2)
        let fromLeft = index % 2 == 0
        let startX = fromLeft ? -220.0 : Double(width) + 220.0
        let startY = 120.0 + lane * 840.0
        let centerX = Double(width) * (0.48 + 0.05 * sin(Double(index)))
        let centerY = Double(height) * (0.48 + 0.13 * (phase - 0.5))
        let p = ease(clamp(convergence - phase * 0.28))
        let x = startX + (centerX - startX) * p
        let y = startY + (centerY - startY) * p
        let tail = 120.0 + 250.0 * hash(index + 11)
        let tailX = x + (fromLeft ? -tail : tail) * (1.0 - p * 0.35)
        let tailY = y + 20.0 * sin(t * 4.0 + Double(index))

        ctx.saveGState()
        ctx.setLineCap(.round)
        ctx.setStrokeColor(ice.withAlphaComponent(CGFloat(0.16 + 0.30 * phase)).cgColor)
        ctx.setLineWidth(CGFloat(1.0 + 2.4 * phase))
        ctx.setShadow(offset: .zero, blur: 12, color: cyan.withAlphaComponent(0.60).cgColor)
        ctx.move(to: CGPoint(x: tailX, y: tailY))
        ctx.addLine(to: CGPoint(x: x, y: y))
        ctx.strokePath()
        ctx.restoreGState()
    }
}

func drawDataArcs(_ ctx: CGContext, t: Double, alpha: CGFloat = 1.0) {
    for index in 0..<7 {
        let y = CGFloat(208 + index * 27)
        let offset = CGFloat(sin(t * 2.5 + Double(index)) * 22.0)
        let path = CGMutablePath()
        path.move(to: CGPoint(x: -60, y: y + offset))
        path.addCurve(
            to: CGPoint(x: CGFloat(width) + 60, y: y + offset + CGFloat(index * 3)),
            control1: CGPoint(x: 510, y: y + 120 + offset),
            control2: CGPoint(x: 1290, y: y - 100 + offset)
        )
        ctx.saveGState()
        ctx.setStrokeColor(ice.withAlphaComponent(alpha * CGFloat(0.10 + 0.035 * Double(index))).cgColor)
        ctx.setLineWidth(CGFloat(1 + index % 3))
        ctx.setShadow(offset: .zero, blur: 8, color: cyan.withAlphaComponent(alpha * 0.30).cgColor)
        ctx.addPath(path)
        ctx.strokePath()
        ctx.restoreGState()
    }
}

func drawTransitionFlash(_ ctx: CGContext, at t: Double, center: Double, duration: Double = 0.18) {
    let distance = abs(t - center)
    guard distance < duration else { return }
    let alpha = CGFloat((1.0 - distance / duration) * 0.32)
    ctx.setFillColor(ice.withAlphaComponent(alpha).cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
}

func drawScene1(_ ctx: CGContext, t: Double) {
    ctx.setFillColor(NSColor.black.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

    let gradient = CGGradient(
        colorsSpace: colorSpace,
        colors: [
            ice.withAlphaComponent(0.13).cgColor,
            NSColor.black.cgColor,
        ] as CFArray,
        locations: [0.0, 1.0]
    )!
    ctx.drawRadialGradient(
        gradient,
        startCenter: CGPoint(x: 965, y: 550),
        startRadius: 0,
        endCenter: CGPoint(x: 965, y: 550),
        endRadius: 720,
        options: [.drawsAfterEndLocation]
    )
    drawLightTrails(ctx, t: t, convergence: easeOut(t / 2.25))

    let baseWidth: CGFloat = 940
    let ratio = CGFloat(logo.height) / CGFloat(logo.width)
    var logoRect = CGRect(
        x: (CGFloat(width) - baseWidth) / 2,
        y: 315,
        width: baseWidth,
        height: baseWidth * ratio
    )
    var alpha = CGFloat(ease(t / 0.6))
    var reveal = CGFloat(ease((t - 0.18) / 1.72))

    if t > 2.48 {
        let zoomP = easeOut((t - 2.48) / 0.52)
        let scale = CGFloat(1.0 + 8.6 * zoomP)
        let portalCenter = CGPoint(x: 1085, y: 560)
        logoRect = CGRect(
            x: portalCenter.x + (logoRect.minX - portalCenter.x) * scale,
            y: portalCenter.y + (logoRect.minY - portalCenter.y) * scale,
            width: logoRect.width * scale,
            height: logoRect.height * scale
        )
        alpha = CGFloat(1.0 - 0.72 * zoomP)
        reveal = 1.0
    }
    drawLogo(ctx, rect: logoRect, alpha: alpha, reveal: reveal, glow: 1.0)

    let scanX = CGFloat(390 + 1140 * ease((t - 0.25) / 1.75))
    ctx.saveGState()
    ctx.setStrokeColor(white.withAlphaComponent(CGFloat(0.25 * (1.0 - clamp((t - 2.0) / 0.5)))).cgColor)
    ctx.setLineWidth(3)
    ctx.setShadow(offset: .zero, blur: 25, color: ice.withAlphaComponent(0.9).cgColor)
    ctx.move(to: CGPoint(x: scanX, y: 330))
    ctx.addLine(to: CGPoint(x: scanX, y: 760))
    ctx.strokePath()
    ctx.restoreGState()

    if t > 1.0 && t < 2.75 {
        drawSubtitle(ctx, text: "xiu-ci  修茈科技", alpha: CGFloat(ease((t - 1.0) / 0.35)))
    }
}

func drawScene2(_ ctx: CGContext, t: Double) {
    let local = t - 3.0
    let zoom = CGFloat(1.0 + 0.045 * clamp(local / 4.0))
    drawCover(workbench, in: ctx, zoom: zoom, panY: CGFloat(-12 + 18 * clamp(local / 4.0)))
    drawVignette(ctx, strength: 0.62)
    drawDataArcs(ctx, t: t, alpha: 0.75)

    let entering = CGFloat(ease(local / 0.42))
    if local < 0.58 {
        ctx.setFillColor(NSColor.black.withAlphaComponent(1.0 - entering).cgColor)
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
    }
    drawSubtitle(ctx, text: "把活，交给 AI 员工", alpha: CGFloat(ease((local - 0.25) / 0.35)))
}

func drawScene3Panel(_ image: CGImage, in ctx: CGContext, local: Double, panDirection: CGFloat) {
    let reveal = CGFloat(ease(local / 0.22))
    let zoom = CGFloat(1.045 - 0.025 * clamp(local / 1.35))
    ctx.saveGState()
    ctx.clip(to: CGRect(x: 0, y: 0, width: CGFloat(width) * reveal, height: CGFloat(height)))
    drawCover(image, in: ctx, zoom: zoom, panX: panDirection * CGFloat(38 * (1.0 - clamp(local / 1.35))))
    ctx.restoreGState()
}

func drawTriptych(_ ctx: CGContext, alpha: CGFloat) {
    let images = [document, support, report]
    let gutter: CGFloat = 8
    let panelWidth = (CGFloat(width) - gutter * 2) / 3
    ctx.saveGState()
    ctx.setAlpha(alpha)
    for (index, image) in images.enumerated() {
        let panel = CGRect(x: CGFloat(index) * (panelWidth + gutter), y: 0, width: panelWidth, height: CGFloat(height))
        ctx.saveGState()
        ctx.clip(to: panel)
        let imageRatio = CGFloat(image.width) / CGFloat(image.height)
        var drawWidth = panel.width
        var drawHeight = drawWidth / imageRatio
        if drawHeight < panel.height {
            drawHeight = panel.height
            drawWidth = drawHeight * imageRatio
        }
        let rect = CGRect(
            x: panel.midX - drawWidth / 2,
            y: panel.midY - drawHeight / 2,
            width: drawWidth,
            height: drawHeight
        )
        ctx.draw(image, in: rect)
        ctx.restoreGState()
    }
    ctx.restoreGState()
}

func drawScene3(_ ctx: CGContext, t: Double) {
    let local = t - 7.0
    if local < 1.35 {
        drawScene3Panel(document, in: ctx, local: local, panDirection: -1)
    } else if local < 2.70 {
        drawScene3Panel(support, in: ctx, local: local - 1.35, panDirection: 1)
    } else {
        drawScene3Panel(report, in: ctx, local: local - 2.70, panDirection: -1)
    }
    if local > 3.48 {
        drawTriptych(ctx, alpha: CGFloat(ease((local - 3.48) / 0.28)))
    }
    drawVignette(ctx, strength: 0.58)
    drawDataArcs(ctx, t: t, alpha: 0.55)
    drawSubtitle(ctx, text: "它，是真的能干活", alpha: CGFloat(ease((local - 0.18) / 0.30)))
    drawTransitionFlash(ctx, at: t, center: 8.35, duration: 0.10)
    drawTransitionFlash(ctx, at: t, center: 9.70, duration: 0.10)
}

func drawNodePulses(_ ctx: CGContext, t: Double) {
    let nodes = [
        CGPoint(x: 395, y: 620),
        CGPoint(x: 650, y: 840),
        CGPoint(x: 1210, y: 840),
        CGPoint(x: 1515, y: 670),
        CGPoint(x: 360, y: 390),
        CGPoint(x: 1555, y: 380),
    ]
    for (index, point) in nodes.enumerated() {
        let phase = (t - 11.0) * 0.85 + Double(index) * 0.16
        let wave = phase - floor(phase)
        let radius = CGFloat(44 + wave * 58)
        ctx.saveGState()
        ctx.setStrokeColor(ice.withAlphaComponent(CGFloat((1.0 - wave) * 0.42)).cgColor)
        ctx.setLineWidth(2)
        ctx.setShadow(offset: .zero, blur: 15, color: cyan.withAlphaComponent(0.42).cgColor)
        ctx.strokeEllipse(in: CGRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2))
        ctx.restoreGState()
    }
}

func drawScene4(_ ctx: CGContext, t: Double) {
    let local = t - 11.0
    drawCover(
        founder,
        in: ctx,
        zoom: CGFloat(1.01 + 0.035 * clamp(local / 3.0)),
        panY: CGFloat(-10 * clamp(local / 3.0))
    )
    drawVignette(ctx, strength: 0.48)
    drawNodePulses(ctx, t: t)
    drawSubtitle(ctx, text: "让一个人，成为一家公司", alpha: CGFloat(ease((local - 0.12) / 0.34)))
}

let websiteQR = cgImage(named: "website-qr.png")

func drawScene5(_ ctx: CGContext, t: Double) {
    let local = t - 14.0
    ctx.setFillColor(NSColor.black.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

    let pulse = exp(-3.4 * max(0.0, local - 3.0))
    let radial = CGGradient(
        colorsSpace: colorSpace,
        colors: [
            ice.withAlphaComponent(CGFloat(0.18 + 0.22 * pulse)).cgColor,
            NSColor.black.cgColor,
        ] as CFArray,
        locations: [0.0, 1.0]
    )!
    ctx.drawRadialGradient(
        radial,
        startCenter: CGPoint(x: 850, y: 580),
        startRadius: 10,
        endCenter: CGPoint(x: 850, y: 580),
        endRadius: 880,
        options: [.drawsAfterEndLocation]
    )

    let logoWidth: CGFloat = 720
    let logoHeight = logoWidth * CGFloat(logo.height) / CGFloat(logo.width)
    let logoRect = CGRect(x: 330, y: 405, width: logoWidth, height: logoHeight)
    let logoAlpha = CGFloat(ease(local / 0.55))
    drawLogo(ctx, rect: logoRect, alpha: logoAlpha, reveal: 1.0, glow: CGFloat(1.0 + 1.5 * pulse))

    let qrPanel = CGRect(x: 1325, y: 340, width: 300, height: 365)
    ctx.saveGState()
    ctx.setAlpha(CGFloat(ease((local - 0.45) / 0.45)))
    ctx.setFillColor(NSColor.white.cgColor)
    ctx.addPath(roundedPath(qrPanel, radius: 18))
    ctx.fillPath()
    ctx.interpolationQuality = .none
    ctx.draw(websiteQR, in: CGRect(x: qrPanel.minX + 38, y: qrPanel.minY + 82, width: 224, height: 224))
    ctx.restoreGState()

    let graphics = NSGraphicsContext(cgContext: ctx, flipped: false)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = graphics
    let titleFont = NSFont(name: "PingFang SC Semibold", size: 56) ?? NSFont.boldSystemFont(ofSize: 56)
    let websiteFont = NSFont(name: "Avenir Next Demi Bold", size: 36) ?? NSFont.boldSystemFont(ofSize: 36)
    drawText(
        "xiu-ci · AI 数字员工平台",
        in: CGRect(x: 280, y: 255, width: 840, height: 86),
        font: titleFont,
        color: white,
        tracking: 0.0
    )
    drawText(
        "xiu-ci.com",
        in: CGRect(x: qrPanel.minX + 20, y: qrPanel.minY + 22, width: qrPanel.width - 40, height: 50),
        font: websiteFont,
        color: NSColor.black
    )
    NSGraphicsContext.restoreGraphicsState()

    if local < 0.55 {
        drawCover(founder, in: ctx, zoom: CGFloat(1.05 + 0.18 * ease(local / 0.55)), alpha: CGFloat(1.0 - ease(local / 0.55)))
    }
}

func renderFrame(time t: Double, into ctx: CGContext) {
    ctx.setFillColor(NSColor.black.cgColor)
    ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))

    if t < 3.0 {
        drawScene1(ctx, t: t)
        if t > 2.78 {
            drawScene2(ctx, t: 3.0)
            ctx.setFillColor(NSColor.black.withAlphaComponent(CGFloat(1.0 - ease((t - 2.78) / 0.22))).cgColor)
        }
    } else if t < 7.0 {
        drawScene2(ctx, t: t)
    } else if t < 11.0 {
        drawScene3(ctx, t: t)
    } else if t < 14.0 {
        drawScene4(ctx, t: t)
    } else {
        drawScene5(ctx, t: t)
    }

    for transition in [3.0, 7.0, 11.0, 14.0] {
        drawTransitionFlash(ctx, at: t, center: transition)
    }
}

let writer = try AVAssetWriter(outputURL: silentURL, fileType: .mp4)
let videoSettings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: width,
    AVVideoHeightKey: height,
    AVVideoCompressionPropertiesKey: [
        AVVideoAverageBitRateKey: 12_000_000,
        AVVideoExpectedSourceFrameRateKey: Int(fps),
        AVVideoMaxKeyFrameIntervalKey: Int(fps) * 2,
        AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
    ],
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
input.expectsMediaDataInRealTime = false
let sourceAttributes: [String: Any] = [
    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
    kCVPixelBufferWidthKey as String: width,
    kCVPixelBufferHeightKey as String: height,
    kCVPixelBufferCGImageCompatibilityKey as String: true,
    kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
]
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: sourceAttributes
)
guard writer.canAdd(input) else {
    fatalError("Cannot add video input")
}
writer.add(input)
guard writer.startWriting() else {
    fatalError("Cannot start writer: \(writer.error?.localizedDescription ?? "unknown")")
}
writer.startSession(atSourceTime: .zero)

guard let pool = adaptor.pixelBufferPool else {
    fatalError("No pixel buffer pool")
}

for frame in 0..<frameCount {
    autoreleasepool {
        while !input.isReadyForMoreMediaData {
            Thread.sleep(forTimeInterval: 0.002)
        }
        var pixelBuffer: CVPixelBuffer?
        let status = CVPixelBufferPoolCreatePixelBuffer(nil, pool, &pixelBuffer)
        guard status == kCVReturnSuccess, let buffer = pixelBuffer else {
            fatalError("Cannot create pixel buffer: \(status)")
        }

        CVPixelBufferLockBaseAddress(buffer, [])
        guard
            let base = CVPixelBufferGetBaseAddress(buffer),
            let ctx = CGContext(
                data: base,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
                space: colorSpace,
                bitmapInfo: CGBitmapInfo.byteOrder32Little.rawValue
                    | CGImageAlphaInfo.premultipliedFirst.rawValue
            )
        else {
            fatalError("Cannot create frame context")
        }

        let time = Double(frame) / Double(fps)
        renderFrame(time: time, into: ctx)

        if frame == Int(17.0 * Double(fps)), let poster = ctx.makeImage() {
            let bitmap = NSBitmapImageRep(cgImage: poster)
            if let data = bitmap.representation(using: .png, properties: [:]) {
                try? data.write(to: posterURL)
            }
        }

        CVPixelBufferUnlockBaseAddress(buffer, [])
        let presentationTime = CMTime(value: CMTimeValue(frame), timescale: fps)
        guard adaptor.append(buffer, withPresentationTime: presentationTime) else {
            fatalError("Append failed: \(writer.error?.localizedDescription ?? "unknown")")
        }
    }
    if frame % 60 == 0 {
        print("Rendered \(frame)/\(frameCount) frames")
    }
}

input.markAsFinished()
let finishSemaphore = DispatchSemaphore(value: 0)
writer.finishWriting {
    finishSemaphore.signal()
}
finishSemaphore.wait()
guard writer.status == .completed else {
    fatalError("Video writer failed: \(writer.error?.localizedDescription ?? "unknown")")
}

let videoAsset = AVURLAsset(url: silentURL)
let audioAsset = AVURLAsset(url: audioURL)
let composition = AVMutableComposition()
guard
    let sourceVideo = videoAsset.tracks(withMediaType: .video).first,
    let sourceAudio = audioAsset.tracks(withMediaType: .audio).first,
    let videoTrack = composition.addMutableTrack(
        withMediaType: .video,
        preferredTrackID: kCMPersistentTrackID_Invalid
    ),
    let audioTrack = composition.addMutableTrack(
        withMediaType: .audio,
        preferredTrackID: kCMPersistentTrackID_Invalid
    )
else {
    fatalError("Cannot create composition tracks")
}

let range = CMTimeRange(start: .zero, duration: CMTime(seconds: duration, preferredTimescale: 600))
try videoTrack.insertTimeRange(range, of: sourceVideo, at: .zero)
try audioTrack.insertTimeRange(range, of: sourceAudio, at: .zero)
videoTrack.preferredTransform = sourceVideo.preferredTransform

guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
    fatalError("Cannot create exporter")
}
exporter.outputURL = finalURL
exporter.outputFileType = .mp4
exporter.shouldOptimizeForNetworkUse = true
let exportSemaphore = DispatchSemaphore(value: 0)
exporter.exportAsynchronously {
    exportSemaphore.signal()
}
exportSemaphore.wait()

guard exporter.status == .completed else {
    fatalError("Export failed: \(exporter.error?.localizedDescription ?? "unknown")")
}

try? FileManager.default.removeItem(at: silentURL)
print("Created \(finalURL.path)")
print("Created \(posterURL.path)")
