// Contact sheet (2×2 frames at 10/35/60/85 %) plus metadata for each input clip.
//   swiftc -O contact.swift -o contact && ./contact out_dir clip1.mp4 clip2.mp4 ...
import AVFoundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

let outDir = URL(fileURLWithPath: CommandLine.arguments[1])
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
for path in CommandLine.arguments.dropFirst(2) {
    let asset = AVURLAsset(url: URL(fileURLWithPath: path))
    let sem = DispatchSemaphore(value: 0)
    Task {
        defer { sem.signal() }
        do {
            let d = try await asset.load(.duration).seconds
            guard let tr = try await asset.loadTracks(withMediaType: .video).first else { print("\(path): no video"); return }
            let (size, fps, xf) = try await tr.load(.naturalSize, .nominalFrameRate, .preferredTransform)
            let r = CGRect(origin: .zero, size: size).applying(xf)
            print(String(format: "%@  %.2fs  %dx%d  %.2ffps", (path as NSString).lastPathComponent, d, Int(abs(r.width)), Int(abs(r.height)), fps))
            let gen = AVAssetImageGenerator(asset: asset)
            gen.appliesPreferredTrackTransform = true
            gen.maximumSize = CGSize(width: 960, height: 960)
            gen.requestedTimeToleranceBefore = .zero; gen.requestedTimeToleranceAfter = .zero
            let ctx = CGContext(data: nil, width: 1920, height: 1080, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
            for (i, f) in [0.1, 0.35, 0.6, 0.85].enumerated() {
                let (img, _) = try await gen.image(at: CMTime(seconds: d * f, preferredTimescale: 600))
                let x = Double(i % 2) * 960, y = Double(1 - i / 2) * 540
                let s = min(960 / Double(img.width), 540 / Double(img.height))
                let w = Double(img.width) * s, h = Double(img.height) * s
                ctx.draw(img, in: CGRect(x: x + (960 - w) / 2, y: y + (540 - h) / 2, width: w, height: h))
            }
            let url = outDir.appendingPathComponent(((path as NSString).lastPathComponent as NSString).deletingPathExtension + ".png")
            let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
            CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
            CGImageDestinationFinalize(dest)
        } catch { print("\(path): \(error)") }
    }
    sem.wait()
}
