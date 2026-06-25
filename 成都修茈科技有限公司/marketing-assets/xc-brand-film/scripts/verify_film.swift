import AppKit
import AVFoundation
import Foundation
import Vision

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: verify_film <project-root>\n", stderr)
    exit(2)
}

let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let videoURL = root.appendingPathComponent("output/xc-brand-film-1080p.mp4")
let framesURL = root.appendingPathComponent("output/verification-frames", isDirectory: true)
try FileManager.default.createDirectory(at: framesURL, withIntermediateDirectories: true)

let asset = AVURLAsset(url: videoURL)
let duration = CMTimeGetSeconds(asset.duration)
let videoTracks = asset.tracks(withMediaType: .video)
let audioTracks = asset.tracks(withMediaType: .audio)

guard let videoTrack = videoTracks.first else {
    fatalError("Missing video track")
}

let size = videoTrack.naturalSize.applying(videoTrack.preferredTransform)
let subtype = videoTrack.formatDescriptions
    .first
    .map { CMFormatDescriptionGetMediaSubType($0 as! CMFormatDescription) } ?? 0
let codec = String(
    bytes: [
        UInt8((subtype >> 24) & 0xff),
        UInt8((subtype >> 16) & 0xff),
        UInt8((subtype >> 8) & 0xff),
        UInt8(subtype & 0xff),
    ],
    encoding: .ascii
) ?? "unknown"
print("duration=\(String(format: "%.3f", duration))")
print("video_tracks=\(videoTracks.count)")
print("audio_tracks=\(audioTracks.count)")
print("dimensions=\(Int(abs(size.width)))x\(Int(abs(size.height)))")
print("codec=\(codec)")

let generator = AVAssetImageGenerator(asset: asset)
generator.appliesPreferredTrackTransform = true
generator.requestedTimeToleranceBefore = .zero
generator.requestedTimeToleranceAfter = .zero

let checkpoints: [(String, Double)] = [
    ("scene-01", 1.8),
    ("scene-02", 4.8),
    ("scene-03a", 7.7),
    ("scene-03b", 9.0),
    ("scene-03c", 10.3),
    ("scene-04", 12.4),
    ("scene-05", 17.0),
]

var finalFrame: CGImage?
for (name, seconds) in checkpoints {
    let time = CMTime(seconds: seconds, preferredTimescale: 600)
    let image = try generator.copyCGImage(at: time, actualTime: nil)
    let bitmap = NSBitmapImageRep(cgImage: image)
    let data = bitmap.representation(using: .png, properties: [:])!
    try data.write(to: framesURL.appendingPathComponent("\(name).png"))
    if name == "scene-05" {
        finalFrame = image
    }
}

guard let finalFrame else {
    fatalError("Missing final verification frame")
}

let request = VNDetectBarcodesRequest()
request.symbologies = [.qr]
let handler = VNImageRequestHandler(cgImage: finalFrame, options: [:])
try handler.perform([request])
let payloads = (request.results ?? []).compactMap(\.payloadStringValue)
print("qr_payloads=\(payloads.joined(separator: ","))")

guard duration >= 17.9 && duration <= 18.1 else {
    fatalError("Unexpected duration")
}
guard videoTracks.count == 1, audioTracks.count == 1 else {
    fatalError("Unexpected track count")
}
guard Int(abs(size.width)) == 1920, Int(abs(size.height)) == 1080 else {
    fatalError("Unexpected dimensions")
}
guard codec == "avc1" else {
    fatalError("Unexpected codec")
}
guard payloads.contains("https://xiu-ci.com") else {
    fatalError("QR code was not readable")
}

print("verification=passed")
