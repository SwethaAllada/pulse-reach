// PulseReach cinematic intro (00:00–00:40), rendered procedurally with CoreGraphics and encoded
// to H.264 with AVFoundation. Every frame is a pure function of time, so any range re-renders
// identically.
//
//   swiftc -O render.swift -o render
//   ./render out.mp4 [--clean] [--from SEC --to SEC]
//   ./render --stills out_dir t1,t2,...  [--clean]
//
// --clean omits the logo and titles (plate for post-production).

import AVFoundation
import CoreGraphics
import CoreImage
import CoreText
import CoreVideo
import Foundation
import ImageIO
import UniformTypeIdentifiers

let W = 1920.0, H = 1080.0
let FPS = 30
let DURATION = 40.0

// MARK: - Math

@inline(__always) func clamp(_ x: Double, _ a: Double = 0, _ b: Double = 1) -> Double { min(max(x, a), b) }
@inline(__always) func smooth(_ e0: Double, _ e1: Double, _ x: Double) -> Double {
    let t = clamp((x - e0) / (e1 - e0)); return t * t * (3 - 2 * t)
}
@inline(__always) func easeIO(_ t: Double) -> Double {
    let x = clamp(t); return x < 0.5 ? 4 * x * x * x : 1 - pow(-2 * x + 2, 3) / 2
}
@inline(__always) func lerp(_ a: Double, _ b: Double, _ t: Double) -> Double { a + (b - a) * t }

struct V3 { var x: Double; var y: Double; var z: Double }

struct RNG {
    var s: UInt64
    mutating func next() -> UInt64 {
        s &+= 0x9E37_79B9_7F4A_7C15
        var z = s
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
    mutating func f() -> Double { Double(next() >> 11) / Double(1 << 53) }
    mutating func r(_ a: Double, _ b: Double) -> Double { a + (b - a) * f() }
    mutating func gauss() -> Double { let u = max(f(), 1e-9), v = f(); return sqrt(-2 * log(u)) * cos(2 * .pi * v) }
}

// MARK: - Palette (PulseReach "Prevention Atlas" tokens)

struct RGB { var r: Double; var g: Double; var b: Double }
func hex(_ v: UInt32) -> RGB { RGB(r: Double((v >> 16) & 0xFF) / 255, g: Double((v >> 8) & 0xFF) / 255, b: Double(v & 0xFF) / 255) }
let MIDNIGHT = hex(0x05_14_17), MIDNIGHT_TEAL = hex(0x0A_26_2A), DEEP_TEAL = hex(0x0D_49_45), BRAND_LINE = hex(0x2B_6B_64)
let IVORY = hex(0xF5_F0_E6), PEARL = hex(0xE6_EC_E8), SEAFOAM = hex(0x5E_D6_CA), MINT = hex(0xA6_DC_D0)
let CORAL = hex(0xF0_78_5B), DAWN = hex(0xF6_C4_9A)

// Sprite indices.
let C_PEARL = 0, C_SEAFOAM = 1, C_MINT = 2, C_CORAL = 3, C_IVORY = 4, C_DAWN = 5
let SPRITE_COLORS = [PEARL, SEAFOAM, MINT, CORAL, IVORY, DAWN]

let SRGB = CGColorSpace(name: CGColorSpace.sRGB)!
func cg(_ c: RGB, _ a: Double = 1) -> CGColor { CGColor(colorSpace: SRGB, components: [c.r, c.g, c.b, a])! }
func mix(_ a: RGB, _ b: RGB, _ t: Double) -> RGB { RGB(r: lerp(a.r, b.r, t), g: lerp(a.g, b.g, t), b: lerp(a.b, b.b, t)) }

func bitmap(_ w: Int, _ h: Int) -> CGContext {
    CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: SRGB,
              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
}

func radialImage(_ size: Int, _ c: RGB, _ core: RGB, locations: [CGFloat], alphas: [Double]) -> CGImage {
    let ctx = bitmap(size, size)
    var colors: [CGColor] = []
    for (i, a) in alphas.enumerated() { colors.append(cg(i == 0 ? core : c, a)) }
    let g = CGGradient(colorsSpace: SRGB, colors: colors as CFArray, locations: locations)!
    let ctr = CGPoint(x: Double(size) / 2, y: Double(size) / 2)
    ctx.drawRadialGradient(g, startCenter: ctr, startRadius: 0, endCenter: ctr, endRadius: CGFloat(size) / 2, options: [])
    return ctx.makeImage()!
}

// Glow sprite: the core occupies ~1/9 of the half-width.
let GLOW = SPRITE_COLORS.map { c in
    radialImage(128, c, mix(c, RGB(r: 1, g: 1, b: 1), 0.55), locations: [0, 0.07, 0.11, 0.22, 0.5, 1], alphas: [1, 0.95, 0.6, 0.16, 0.035, 0])
}
// Out-of-focus disc for shallow depth of field.
let BOKEH = SPRITE_COLORS.map { c in
    radialImage(128, c, c, locations: [0, 0.72, 0.9, 1], alphas: [0.28, 0.34, 0.2, 0])
}

// MARK: - Drawing helpers

final class Painter {
    let ctx: CGContext
    var fade = 1.0
    init(_ ctx: CGContext) { self.ctx = ctx }

    func dot(_ c: Int, _ x: Double, _ y: Double, _ r: Double, _ a: Double) {
        let al = a * fade
        if al < 0.004 || x < -80 || x > W + 80 || y < -80 || y > H + 80 { return }
        let s = r * 9
        ctx.setAlpha(CGFloat(min(al, 1)))
        ctx.draw(GLOW[c], in: CGRect(x: x - s, y: y - s, width: 2 * s, height: 2 * s))
    }

    func bokeh(_ c: Int, _ x: Double, _ y: Double, _ r: Double, _ a: Double) {
        let al = a * fade
        if al < 0.004 || x < -120 || x > W + 120 || y < -120 || y > H + 120 { return }
        ctx.setAlpha(CGFloat(min(al, 1)))
        ctx.draw(BOKEH[c], in: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r))
    }
}

/// Batches line segments by colour/alpha/width so thousands of edges stroke in a few calls.
final class Lines {
    var paths: [Int: CGMutablePath] = [:]
    func add(_ c: Int, _ a: Double, _ w: Double, _ x0: Double, _ y0: Double, _ x1: Double, _ y1: Double) {
        if a < 0.004 { return }
        if max(x0, x1) < -10 || min(x0, x1) > W + 10 || max(y0, y1) < -10 || min(y0, y1) > H + 10 { return }
        let ab = min(47, Int(a * 48)), wb = min(15, Int(w * 4))
        let key = c * 10000 + ab * 100 + wb
        let p = paths[key] ?? CGMutablePath()
        p.move(to: CGPoint(x: x0, y: y0)); p.addLine(to: CGPoint(x: x1, y: y1))
        paths[key] = p
    }
    func dashed(_ c: Int, _ a: Double, _ w: Double, _ x0: Double, _ y0: Double, _ x1: Double, _ y1: Double, dash: Double = 9, gap: Double = 8) {
        let len = hypot(x1 - x0, y1 - y0)
        if len < 1 { return }
        var s = 0.0
        while s < len {
            let e = min(len, s + dash)
            add(c, a, w, x0 + (x1 - x0) * s / len, y0 + (y1 - y0) * s / len, x0 + (x1 - x0) * e / len, y0 + (y1 - y0) * e / len)
            s += dash + gap
        }
    }
    func flush(_ p: Painter) {
        let ctx = p.ctx
        ctx.setAlpha(1)
        ctx.setLineCap(.round)
        for (key, path) in paths {
            let c = key / 10000, ab = (key / 100) % 100, wb = key % 100
            let a = (Double(ab) + 0.5) / 48 * p.fade
            if a < 0.004 { continue }
            ctx.setStrokeColor(cg(SPRITE_COLORS[c], min(a, 1)))
            ctx.setLineWidth(CGFloat(max(0.35, Double(wb) / 4 + 0.125)))
            ctx.addPath(path)
            ctx.strokePath()
        }
        paths.removeAll(keepingCapacity: true)
    }
}

func radialFill(_ ctx: CGContext, _ x: Double, _ y: Double, _ radius: Double, _ c: RGB, _ a: Double) {
    if a < 0.003 { return }
    let g = CGGradient(colorsSpace: SRGB, colors: [cg(c, a), cg(c, a * 0.45), cg(c, 0)] as CFArray, locations: [0, 0.45, 1])!
    ctx.setAlpha(1)
    ctx.drawRadialGradient(g, startCenter: CGPoint(x: x, y: y), startRadius: 0, endCenter: CGPoint(x: x, y: y),
                           endRadius: CGFloat(radius), options: [])
}

func knn(_ pts: [V3], k: Int, maxDist: Double) -> [(Int, Int)] {
    var set = Set<Int>()
    var out: [(Int, Int)] = []
    let n = pts.count
    let md2 = maxDist * maxDist
    for i in 0..<n {
        var best: [(Double, Int)] = []
        let p = pts[i]
        for j in 0..<n where j != i {
            let q = pts[j]
            let d2 = (p.x - q.x) * (p.x - q.x) + (p.y - q.y) * (p.y - q.y) + (p.z - q.z) * (p.z - q.z)
            if d2 > md2 { continue }
            if best.count < k { best.append((d2, j)); best.sort { $0.0 < $1.0 } } else if d2 < best[k - 1].0 {
                best[k - 1] = (d2, j); best.sort { $0.0 < $1.0 }
            }
        }
        for (_, j) in best {
            let key = min(i, j) * n + max(i, j)
            if set.insert(key).inserted { out.append((min(i, j), max(i, j))) }
        }
    }
    return out
}

// MARK: - Shots 1–2: live-action footage (Pexels, free licence; see demo-video/FOOTAGE_CREDITS.md)

let CI = CIContext(options: [.workingColorSpace: SRGB, .outputColorSpace: SRGB])

/// Streams decoded frames of one source clip. Requests are normally increasing in time, so a single
/// AVAssetReader is reused; a backwards request (stills mode) restarts it at the requested time.
final class Clip {
    let asset: AVURLAsset
    let track: AVAssetTrack
    var reader: AVAssetReader?
    var output: AVAssetReaderTrackOutput?
    var pending: CMSampleBuffer?
    var current: CMSampleBuffer?
    var currentPTS = -1.0
    var cached: (Double, CGImage)?

    init(_ id: Int) {
        let url = Titles.dir.deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("stock/px_\(id).mp4")
        asset = AVURLAsset(url: url)
        guard let tr = asset.tracks(withMediaType: .video).first else { fatalError("missing footage \(url.path)") }
        track = tr
    }

    private func start(at s: Double) {
        reader?.cancelReading()
        let r = try! AVAssetReader(asset: asset)
        let o = AVAssetReaderTrackOutput(track: track, outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA])
        o.alwaysCopiesSampleData = false
        r.timeRange = CMTimeRange(start: CMTime(seconds: max(0, s), preferredTimescale: 600), duration: .positiveInfinity)
        r.add(o)
        r.startReading()
        reader = r; output = o; pending = nil; current = nil; currentPTS = -1
    }

    func frame(at s: Double) -> CGImage? {
        if reader == nil || s < currentPTS - 0.002 { start(at: s) }
        while true {
            if pending == nil { pending = output?.copyNextSampleBuffer() }
            guard let nb = pending else { break }
            let pts = CMSampleBufferGetPresentationTimeStamp(nb).seconds
            if current == nil || pts <= s + 0.0005 { current = nb; currentPTS = pts; pending = nil } else { break }
        }
        guard let cur = current, let pb = CMSampleBufferGetImageBuffer(cur) else { return cached?.1 }
        if let c = cached, c.0 == currentPTS { return c.1 }
        var img = CIImage(cvPixelBuffer: pb)
        let k = 2400 / img.extent.width
        img = img.transformed(by: CGAffineTransform(scaleX: k, y: k))
        // Grade: restrained saturation, slightly lifted contrast, teal shadows and warm highlights.
        img = img.applyingFilter("CIColorControls", parameters: [kCIInputSaturationKey: 0.74, kCIInputContrastKey: 1.07, kCIInputBrightnessKey: -0.025])
        img = img.applyingFilter("CIVignetteEffect", parameters: [kCIInputCenterKey: CIVector(x: img.extent.midX, y: img.extent.midY),
                                                                  kCIInputRadiusKey: img.extent.width * 0.62, kCIInputIntensityKey: 0.35])
        guard let cg = CI.createCGImage(img, from: img.extent, format: .RGBA8, colorSpace: SRGB) else { return nil }
        cached = (currentPTS, cg)
        return cg
    }
}

struct Shot {
    let clip: Clip
    let t0: Double, t1: Double   // timeline in/out (overlapping the next shot by the dissolve)
    let src: Double, rate: Double
    let s0: Double, s1: Double   // push-in scale
    let a0: (Double, Double), a1: (Double, Double)  // crop anchor (0…1), animated
}

final class Footage {
    let shots: [Shot]

    init() {
        func shot(_ id: Int, _ t0: Double, _ t1: Double, src: Double, rate: Double = 1, s: (Double, Double),
                  a0: (Double, Double) = (0.5, 0.5), a1: (Double, Double) = (0.5, 0.5)) -> Shot {
            Shot(clip: Clip(id), t0: t0, t1: t1, src: src, rate: rate, s0: s.0, s1: s.1, a0: a0, a1: a1)
        }
        shots = [
            // Clip 1 — the problem: city at sunrise → morning commute → care building → staff starting the day.
            shot(35645604, 0.0, 3.9, src: 1.5, rate: 0.9, s: (1.0, 1.07), a1: (0.5, 0.42)),
            shot(31879749, 3.2, 6.2, src: 4.0, s: (1.05, 1.11), a0: (0.3, 0.5), a1: (0.62, 0.5)),
            shot(34261641, 5.5, 8.0, src: 4.0, rate: 0.9, s: (1.42, 1.48), a0: (0.05, 1.0), a1: (0.1, 1.0)),
            shot(6997942, 7.3, 10.6, src: 0.5, s: (1.04, 1.1)),
            // Clip 2 — fragmented care: clinician at screens → nurses coordinating → waiting area → clinician at laptop.
            shot(6236753, 9.9, 12.9, src: 3.0, s: (1.12, 1.18), a0: (0.2, 0.5), a1: (0.28, 0.5)),
            shot(4487286, 12.2, 15.2, src: 2.0, s: (1.0, 1.06), a0: (0.5, 0.6), a1: (0.5, 0.45)),
            shot(3197799, 14.5, 17.5, src: 1.0, s: (1.22, 1.28), a0: (1.0, 0.5), a1: (1.0, 0.45)),
            shot(5030437, 16.8, 20.6, src: 1.0, rate: 0.9, s: (1.03, 1.1), a0: (0.45, 0.5), a1: (0.55, 0.5)),
        ]
    }

    func draw(_ ctx: CGContext, _ t: Double) {
        var any = false
        ctx.setBlendMode(.normal)
        for (i, sh) in shots.enumerated() where t >= sh.t0 && t < sh.t1 {
            let a = i == 0 ? smooth(0, 1.0, t) : smooth(sh.t0, sh.t0 + 0.7, t)
            let u = easeIO((t - sh.t0) / (sh.t1 - sh.t0)) * 0.6 + 0.4 * (t - sh.t0) / (sh.t1 - sh.t0)
            let s = lerp(sh.s0, sh.s1, u)
            let ax = lerp(sh.a0.0, sh.a1.0, u), ay = lerp(sh.a0.1, sh.a1.1, u)
            guard let img = sh.clip.frame(at: sh.src + (t - sh.t0) * sh.rate) else { continue }
            let w = W * s, h = H * s
            ctx.setAlpha(CGFloat(a))
            ctx.interpolationQuality = .high
            ctx.draw(img, in: CGRect(x: -(w - W) * ax, y: -(h - H) * (1 - ay), width: w, height: h))
            any = true
        }
        ctx.setAlpha(1)
        if !any { return }
        let full = CGRect(x: 0, y: 0, width: W, height: H)
        // Palette grade: teal through the shadows and mids, a soft warm key from the upper right.
        ctx.setBlendMode(.softLight)
        ctx.setFillColor(cg(DEEP_TEAL, 0.62)); ctx.fill(full)
        ctx.setBlendMode(.multiply)
        ctx.setFillColor(cg(mix(MIDNIGHT_TEAL, SEAFOAM, 0.15), 0.14)); ctx.fill(full)
        ctx.setBlendMode(.softLight)
        radialFill(ctx, W * 0.82, H * 0.86, 1300, DAWN, 0.32)
        ctx.setBlendMode(.normal)
        // Dissolve toward the constellation.
        let dim = smooth(18.4, 20.4, t)
        if dim > 0 { ctx.setFillColor(cg(MIDNIGHT, 0.92 * dim)); ctx.fill(full) }
    }
}

// MARK: - Shots 3–4: connecting the information, then the organised constellation reveal

final class ShotField {
    var p3: [V3] = [], tgt: [V3] = [], ring: [Int] = [], cols: [Int] = [], ph: [Double] = [], delay: [Double] = []
    var edges: [(Int, Int)] = [], edgeT: [Double] = [], act: [Double] = []
    var ringNeighbours: [(Int, Int)] = []
    let ringZ = 8.0
    let radii = [2.4, 2.9, 3.45, 4.1, 4.9, 5.9]

    init() {
        var g = RNG(s: 33)
        let n = 2600
        for _ in 0..<n {
            p3.append(V3(x: g.r(-5.8, 5.8), y: g.r(-3.4, 3.4), z: g.r(3.0, 13.0)))
            let u = g.f()
            cols.append(u < 0.07 ? C_CORAL : u < 0.26 ? C_SEAFOAM : u < 0.47 ? C_MINT : u < 0.52 ? C_IVORY : C_PEARL)
            ph.append(g.r(0, 2 * .pi))
            delay.append(g.r(0, 1.2))
        }
        edges = knn(p3, k: 3, maxDist: 1.15)
        let o = V3(x: 0.2, y: 0, z: 7.5)
        func dist(_ a: V3, _ b: V3) -> Double { sqrt((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) + (a.z - b.z) * (a.z - b.z)) }
        var maxD = 0.0
        for (a, b) in edges { maxD = max(maxD, dist(V3(x: (p3[a].x + p3[b].x) / 2, y: (p3[a].y + p3[b].y) / 2, z: (p3[a].z + p3[b].z) / 2), o)) }
        act = Array(repeating: 1e9, count: n)
        for (a, b) in edges {
            let m = V3(x: (p3[a].x + p3[b].x) / 2, y: (p3[a].y + p3[b].y) / 2, z: (p3[a].z + p3[b].z) / 2)
            let te = 20.5 + 6.8 * pow(dist(m, o) / maxD, 0.9) + g.r(0, 0.45)
            edgeT.append(te)
            act[a] = min(act[a], te); act[b] = min(act[b], te)
        }
        // Organised formation: concentric survey rings plus the cross-hair axes of the logo mark.
        var targets: [(V3, Int)] = []
        let circ = radii.map { 2 * .pi * $0 }, total = circ.reduce(0, +)
        let onAxes = Int(Double(n) * 0.06)
        for (ri, r) in radii.enumerated() {
            let cnt = Int(Double(n - onAxes) * circ[ri] / total)
            for k in 0..<cnt {
                let a = 2 * .pi * (Double(k) + g.r(-0.2, 0.2)) / Double(cnt)
                let rr = r + g.r(-0.01, 0.01)
                targets.append((V3(x: rr * cos(a), y: rr * sin(a), z: ringZ + g.r(-0.03, 0.03)), ri))
            }
        }
        while targets.count < n {
            let r = g.r(2.4, 6.4), side = Int(g.r(0, 4))
            let a = Double(side) * .pi / 2
            targets.append((V3(x: r * cos(a) + g.r(-0.02, 0.02), y: r * sin(a) + g.r(-0.02, 0.02), z: ringZ + g.r(-0.1, 0.1)), -1))
        }
        let srcOrder = (0..<n).sorted { atan2(p3[$0].y, p3[$0].x) < atan2(p3[$1].y, p3[$1].x) }
        let dstOrder = (0..<n).sorted { atan2(targets[$0].0.y, targets[$0].0.x) < atan2(targets[$1].0.y, targets[$1].0.x) }
        tgt = Array(repeating: V3(x: 0, y: 0, z: 0), count: n)
        ring = Array(repeating: -1, count: n)
        for k in 0..<n { tgt[srcOrder[k]] = targets[dstOrder[k]].0; ring[srcOrder[k]] = targets[dstOrder[k]].1 }
        for ri in 0..<radii.count {
            let members = (0..<n).filter { ring[$0] == ri }.sorted { atan2(tgt[$0].y, tgt[$0].x) < atan2(tgt[$1].y, tgt[$1].x) }
            for k in 0..<members.count { ringNeighbours.append((members[k], members[(k + 1) % members.count])) }
        }
    }

    func position(_ i: Int, _ t: Double) -> V3 {
        let p = p3[i]
        let dr = V3(x: p.x + 0.045 * sin(0.5 * t + ph[i]), y: p.y + 0.045 * cos(0.43 * t + ph[i] * 1.3), z: p.z)
        let s = 30.0 + delay[i]
        let e = easeIO((t - s) / 3.0)
        if e <= 0 { return dr }
        let rot = 0.035 * (t - 30)
        let tp = tgt[i]
        let tx = tp.x * cos(rot) - tp.y * sin(rot), ty = tp.x * sin(rot) + tp.y * cos(rot)
        let x = lerp(dr.x, tx, e), y = lerp(dr.y, ty, e), z = lerp(dr.z, tp.z, e)
        let tw = (1 - e) * e * 1.2  // gentle spiral while organising
        return V3(x: x * cos(tw) - y * sin(tw), y: x * sin(tw) + y * cos(tw), z: z)
    }

    func cam(_ t: Double) -> (Double, Double, Double) {
        if t < 30.5 {
            let e = easeIO((t - 19.5) / 11.0)
            return (0.6 * (1 - e), -0.25 * (1 - e), 2.6 * e)
        }
        return (0, 0, 2.6 + 0.4 * easeIO((t - 30.5) / 9.5))
    }

    func draw(_ P: Painter, _ t: Double, titles: Bool) {
        let ctx = P.ctx
        let f = 1000.0
        let (cx, cy, cz) = cam(t)
        let organise = smooth(30, 34, t)
        radialFill(ctx, W * 0.5, H * 0.5, 1150, DEEP_TEAL, (0.38 + 0.12 * smooth(20, 30, t)) * P.fade)
        radialFill(ctx, W * 0.18, H * 0.82, 700, MIDNIGHT_TEAL, 0.5 * P.fade)

        let n = p3.count
        var scr = [(Double, Double, Double, Double)](repeating: (0, 0, 0, -1), count: n)
        for i in 0..<n {
            let p = position(i, t)
            let d = p.z - cz
            if d < 0.3 { continue }
            let s = f / d
            scr[i] = (W / 2 + (p.x - cx) * s, H / 2 + (p.y - cy) * s, s, d)
        }
        let L = Lines()
        let edgeFade = 1 - smooth(30.2, 32.2, t)
        if edgeFade > 0 {
            for (k, (a, b)) in edges.enumerated() {
                let te = edgeT[k]
                if t < te { continue }
                let pa = scr[a], pb = scr[b]
                if pa.3 < 0 || pb.3 < 0 { continue }
                let fog = exp(-max(0, (pa.3 + pb.3) / 2 - 4) * 0.08)
                let grow = smooth(te, te + 0.6, t)
                let c = (cols[a] == C_CORAL || cols[b] == C_CORAL) ? C_CORAL : C_SEAFOAM
                let ex = pa.0 + (pb.0 - pa.0) * grow, ey = pa.1 + (pb.1 - pa.1) * grow
                L.add(c, 0.3 * fog * edgeFade, 1.0, pa.0, pa.1, ex, ey)
                if grow < 1 { P.ctx.setBlendMode(.plusLighter); P.dot(C_IVORY, ex, ey, 1.4, 0.8 * fog * (1 - grow)) }
            }
        }
        let ringFade = smooth(33.4, 35.4, t)
        if ringFade > 0 {
            for (a, b) in ringNeighbours {
                let pa = scr[a], pb = scr[b]
                if pa.3 < 0 || pb.3 < 0 || hypot(pa.0 - pb.0, pa.1 - pb.1) > 120 { continue }
                L.add(cols[a] == C_CORAL ? C_CORAL : C_MINT, 0.2 * ringFade, 1.0, pa.0, pa.1, pb.0, pb.1)
            }
        }
        ctx.setBlendMode(.plusLighter)
        L.flush(P)

        // Cross-hair axes and the dashed survey arc from the logo mark.
        let ringS = f / (ringZ - cz)
        let ctr = (W / 2 - cx * ringS, H / 2 - cy * ringS)
        if ringFade > 0 {
            let rot = 0.035 * (t - 30)
            let inner = radii[0] * ringS
            ctx.setBlendMode(.normal)
            ctx.setStrokeColor(cg(BRAND_LINE, 0.55 * ringFade * P.fade))
            ctx.setLineWidth(1)
            for k in 0..<4 {
                let a = rot + Double(k) * .pi / 2
                ctx.move(to: CGPoint(x: ctr.0 + cos(a) * (inner + 12), y: ctr.1 + sin(a) * (inner + 12)))
                ctx.addLine(to: CGPoint(x: ctr.0 + cos(a) * 2400, y: ctr.1 + sin(a) * 2400))
            }
            ctx.strokePath()
            let arcA = smooth(34.0, 35.6, t)
            let start = 0.55 + 0.32 * (t - 34)
            let span: Double = 2 * Double.pi * 16 / 60
            ctx.setBlendMode(.plusLighter)
            for (w, a) in [(9.0, 0.08), (2.6, 0.85)] {
                ctx.setStrokeColor(cg(MINT, a * arcA * P.fade))
                ctx.setLineWidth(w)
                ctx.setLineCap(.round)
                ctx.addArc(center: CGPoint(x: ctr.0, y: ctr.1), radius: inner, startAngle: start, endAngle: start + span, clockwise: false)
                ctx.strokePath()
            }
        }

        ctx.setBlendMode(.plusLighter)
        for i in 0..<n {
            let (sx, sy, s, d) = scr[i]
            if d < 0 { continue }
            let fog = exp(-max(0, d - 4) * 0.08)
            let on = smooth(act[i], act[i] + 0.5, t)
            var a = lerp(0.32, 0.9, on)
            var r = clamp(s * 0.016, 0.6, 3.4)
            if cols[i] == C_CORAL {
                a = on > 0 ? lerp(0.45, 0.95, on) : 0.4 + 0.25 * sin(3 * t + ph[i])
                r *= 1.25
            }
            a *= 0.85 + 0.15 * sin(1.9 * t + ph[i])
            a = lerp(a, max(a, 0.75), organise)
            P.dot(cols[i], sx, sy, r, a * fog)
        }
        ctx.setBlendMode(.normal)

        // Negative space at the centre for the logo.
        let clear = smooth(32.5, 35.0, t)
        if clear > 0 {
            let g = CGGradient(colorsSpace: SRGB, colors: [cg(MIDNIGHT, 0.78 * clear * P.fade), cg(MIDNIGHT, 0.55 * clear * P.fade), cg(MIDNIGHT, 0)] as CFArray,
                               locations: [0, 0.6, 1])!
            ctx.drawRadialGradient(g, startCenter: CGPoint(x: ctr.0, y: ctr.1), startRadius: 0, endCenter: CGPoint(x: ctr.0, y: ctr.1),
                                   endRadius: CGFloat(radii[0] * ringS * 0.96), options: [])
        }
        if titles { Titles.draw(ctx, t, center: ctr) }
    }
}

// MARK: - Brand titles (logo mark geometry mirrors frontend/components/shell/logo.tsx)

enum Titles {
    static let dir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent().appendingPathComponent("fonts")

    static func font(_ file: String, size: Double, axes: [Int: Double]) -> CTFont {
        let url = dir.appendingPathComponent(file)
        guard let descs = CTFontManagerCreateFontDescriptorsFromURL(url as CFURL) as? [CTFontDescriptor], let d0 = descs.first else {
            fatalError("missing font \(url.path)")
        }
        var vars: [NSNumber: NSNumber] = [:]
        for (k, v) in axes { vars[NSNumber(value: k)] = NSNumber(value: v) }
        let d = CTFontDescriptorCreateCopyWithAttributes(d0, [kCTFontVariationAttribute: vars] as CFDictionary)
        return CTFontCreateWithFontDescriptor(d, CGFloat(size), nil)
    }

    static let WGHT = 0x7767_6874, OPSZ = 0x6F70_737A, SOFT = 0x534F_4654
    static let display = font("Fraunces.ttf", size: 104, axes: [WGHT: 460, OPSZ: 96, SOFT: 30])
    static let displayItalic = font("Fraunces-Italic.ttf", size: 104, axes: [WGHT: 460, OPSZ: 96, SOFT: 30])
    static let ui = font("Geist-Regular.ttf", size: 29, axes: [:])

    static func line(_ runs: [(String, CTFont, RGB)], kern: Double, alpha: Double) -> CTLine {
        let s = NSMutableAttributedString()
        for (text, f, c) in runs {
            s.append(NSAttributedString(string: text, attributes: [
                NSAttributedString.Key(kCTFontAttributeName as String): f,
                NSAttributedString.Key(kCTForegroundColorAttributeName as String): cg(c, alpha),
                NSAttributedString.Key(kCTKernAttributeName as String): kern,
            ]))
        }
        return CTLineCreateWithAttributedString(s)
    }

    static func drawCentered(_ ctx: CGContext, _ l: CTLine, x: Double, y: Double, trailingKern: Double) {
        let w = CTLineGetTypographicBounds(l, nil, nil, nil) - trailingKern
        ctx.textMatrix = .identity
        ctx.textPosition = CGPoint(x: x - w / 2, y: y)
        CTLineDraw(l, ctx)
    }

    static func mark(_ ctx: CGContext, cx: Double, cy: Double, side: Double, alpha: Double) {
        ctx.saveGState()
        ctx.setAlpha(CGFloat(alpha))
        ctx.beginTransparencyLayer(auxiliaryInfo: nil)
        ctx.translateBy(x: cx - side / 2, y: cy + side / 2)
        ctx.scaleBy(x: side / 32, y: -side / 32)
        ctx.addPath(CGPath(roundedRect: CGRect(x: 0.5, y: 0.5, width: 31, height: 31), cornerWidth: 8, cornerHeight: 8, transform: nil))
        ctx.setFillColor(cg(DEEP_TEAL))
        ctx.fillPath()
        ctx.setStrokeColor(cg(MINT, 0.4)); ctx.setLineWidth(1)
        ctx.addEllipse(in: CGRect(x: 6.5, y: 6.5, width: 19, height: 19)); ctx.strokePath()
        ctx.setStrokeColor(cg(BRAND_LINE)); ctx.setLineWidth(0.8)
        ctx.move(to: CGPoint(x: 6.5, y: 16)); ctx.addLine(to: CGPoint(x: 25.5, y: 16))
        ctx.move(to: CGPoint(x: 16, y: 6.5)); ctx.addLine(to: CGPoint(x: 16, y: 25.5)); ctx.strokePath()
        ctx.setStrokeColor(cg(MINT)); ctx.setLineWidth(1.4); ctx.setLineCap(.round)
        ctx.setLineDash(phase: 0, lengths: [16, 44])
        ctx.addArc(center: CGPoint(x: 16, y: 16), radius: 9.5, startAngle: 0, endAngle: 2 * .pi, clockwise: false); ctx.strokePath()
        ctx.setLineDash(phase: 0, lengths: [])
        for (x, y, r, c) in [(12.0, 13.0, 2.1, CORAL), (19.5, 18.5, 1.6, MINT), (18.0, 11.5, 1.0, IVORY), (12.5, 20.0, 1.0, IVORY)] {
            ctx.setFillColor(cg(c)); ctx.addEllipse(in: CGRect(x: x - r, y: y - r, width: 2 * r, height: 2 * r)); ctx.fillPath()
        }
        ctx.endTransparencyLayer()
        ctx.restoreGState()
    }

    static func draw(_ ctx: CGContext, _ t: Double, center: (Double, Double)) {
        ctx.setBlendMode(.normal)
        let m = easeIO((t - 34.1) / 1.0)
        if m > 0 {
            let side = 128 * (0.93 + 0.07 * m)
            radialFill(ctx, center.0, center.1 + 92, 190, SEAFOAM, 0.10 * m)
            mark(ctx, cx: center.0, cy: center.1 + 92, side: side, alpha: m)
        }
        let w = easeIO((t - 34.9) / 1.1)
        if w > 0 {
            let kern = 16.0
            let l = line([("PULSE", display, IVORY), ("REACH", displayItalic, CORAL)], kern: kern, alpha: w)
            drawCentered(ctx, l, x: center.0, y: center.1 - 64 - 14 * (1 - w), trailingKern: kern)
        }
        let s = easeIO((t - 35.9) / 1.1)
        if s > 0 {
            let kern = 2.2
            let l = line([("From insight to preventive action.", ui, PEARL)], kern: kern, alpha: 0.88 * s)
            drawCentered(ctx, l, x: center.0, y: center.1 - 140 - 10 * (1 - s), trailingKern: kern)
        }
    }
}

// MARK: - Film finish

func makeVignette() -> CGImage {
    let ctx = bitmap(Int(W), Int(H))
    let g = CGGradient(colorsSpace: SRGB, colors: [cg(MIDNIGHT, 0), cg(MIDNIGHT, 0.12), cg(MIDNIGHT, 0.62)] as CFArray, locations: [0, 0.55, 1])!
    ctx.drawRadialGradient(g, startCenter: CGPoint(x: W / 2, y: H / 2), startRadius: 0, endCenter: CGPoint(x: W / 2, y: H / 2),
                           endRadius: CGFloat(hypot(W, H) / 2), options: [.drawsAfterEndLocation])
    return ctx.makeImage()!
}

func makeGrain(_ seed: UInt64) -> CGImage {
    let n = 512
    var g = RNG(s: seed)
    var px = [UInt8](repeating: 0, count: n * n * 4)
    for i in 0..<(n * n) {
        let v = UInt8(g.f() * 255)
        let a = UInt8(255)
        px[i * 4] = v; px[i * 4 + 1] = v; px[i * 4 + 2] = v; px[i * 4 + 3] = a
    }
    let ctx = CGContext(data: &px, width: n, height: n, bitsPerComponent: 8, bytesPerRow: n * 4, space: SRGB,
                        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    return ctx.makeImage()!
}

let VIGNETTE = makeVignette()
let GRAIN = (0..<4).map { makeGrain(UInt64(100 + $0)) }

// MARK: - Frame composition

let footage = Footage(), field = ShotField()

func renderFrame(_ ctx: CGContext, _ t: Double, titles: Bool, frameIndex: Int) {
    ctx.setBlendMode(.normal)
    ctx.setAlpha(1)
    ctx.setFillColor(cg(MIDNIGHT))
    ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
    let P = Painter(ctx)
    // Live-action footage 00:00–00:20, dissolving into the constellation from 18.8 s.
    if t < 20.6 { footage.draw(ctx, t) }
    if t > 18.8 { P.fade = smooth(18.8, 20.6, t); field.draw(P, t, titles: titles) }

    ctx.setBlendMode(.normal)
    ctx.setAlpha(1)
    ctx.draw(VIGNETTE, in: CGRect(x: 0, y: 0, width: W, height: H))
    ctx.setBlendMode(.softLight)
    ctx.setAlpha(0.06)
    let gi = GRAIN[frameIndex % GRAIN.count]
    let ox = Double((frameIndex * 137) % 512), oy = Double((frameIndex * 271) % 512)
    var y = -oy
    while y < H { var x = -ox; while x < W { ctx.draw(gi, in: CGRect(x: x, y: y, width: 512, height: 512)); x += 512 }; y += 512 }
    ctx.setBlendMode(.normal)
    ctx.setAlpha(1)
    // Final transition to the application's ivory canvas.
    let out = smooth(38.7, 39.95, t)
    if out > 0 { ctx.setFillColor(cg(IVORY, out)); ctx.fill(CGRect(x: 0, y: 0, width: W, height: H)) }
}

// MARK: - Output

func writeStills(dir: String, times: [Double], titles: Bool) {
    try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
    for t in times {
        let ctx = bitmap(Int(W), Int(H))
        renderFrame(ctx, t, titles: titles, frameIndex: Int(t * Double(FPS)))
        let url = URL(fileURLWithPath: dir).appendingPathComponent(String(format: "still_%05.2f.png", t))
        let dest = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)!
        CGImageDestinationAddImage(dest, ctx.makeImage()!, nil)
        CGImageDestinationFinalize(dest)
        print(url.path)
    }
}

func writeMovie(path: String, from: Double, to: Double, titles: Bool) throws {
    let url = URL(fileURLWithPath: path)
    try? FileManager.default.removeItem(at: url)
    let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
    let settings: [String: Any] = [
        AVVideoCodecKey: AVVideoCodecType.h264,
        AVVideoWidthKey: Int(W), AVVideoHeightKey: Int(H),
        AVVideoCompressionPropertiesKey: [
            AVVideoAverageBitRateKey: 28_000_000,
            AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel,
            AVVideoMaxKeyFrameIntervalKey: FPS,
            AVVideoExpectedSourceFrameRateKey: FPS,
        ],
        AVVideoColorPropertiesKey: [
            AVVideoColorPrimariesKey: AVVideoColorPrimaries_ITU_R_709_2,
            AVVideoTransferFunctionKey: AVVideoTransferFunction_ITU_R_709_2,
            AVVideoYCbCrMatrixKey: AVVideoYCbCrMatrix_ITU_R_709_2,
        ],
    ]
    let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
    input.expectsMediaDataInRealTime = false
    let adaptor = AVAssetWriterInputPixelBufferAdaptor(assetWriterInput: input, sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
        kCVPixelBufferWidthKey as String: Int(W), kCVPixelBufferHeightKey as String: Int(H),
        kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
    ])
    writer.add(input)
    guard writer.startWriting() else { throw writer.error ?? NSError(domain: "render", code: 1) }
    writer.startSession(atSourceTime: .zero)
    let first = Int((from * Double(FPS)).rounded()), last = Int((to * Double(FPS)).rounded())
    for fi in first..<last {
        while !input.isReadyForMoreMediaData { usleep(2000) }
        var pb: CVPixelBuffer?
        CVPixelBufferPoolCreatePixelBuffer(nil, adaptor.pixelBufferPool!, &pb)
        guard let buf = pb else { throw NSError(domain: "render", code: 2) }
        CVPixelBufferLockBaseAddress(buf, [])
        let ctx = CGContext(data: CVPixelBufferGetBaseAddress(buf), width: Int(W), height: Int(H), bitsPerComponent: 8,
                            bytesPerRow: CVPixelBufferGetBytesPerRow(buf), space: SRGB,
                            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue)!
        renderFrame(ctx, Double(fi) / Double(FPS), titles: titles, frameIndex: fi)
        CVPixelBufferUnlockBaseAddress(buf, [])
        if !adaptor.append(buf, withPresentationTime: CMTime(value: Int64(fi - first), timescale: CMTimeScale(FPS))) {
            throw writer.error ?? NSError(domain: "render", code: 3)
        }
        if (fi - first) % 60 == 0 { print("frame \(fi)/\(last)"); fflush(stdout) }
    }
    input.markAsFinished()
    let done = DispatchSemaphore(value: 0)
    writer.finishWriting { done.signal() }
    done.wait()
    if writer.status != .completed { throw writer.error ?? NSError(domain: "render", code: 4) }
    print("wrote \(path)")
}

var args = Array(CommandLine.arguments.dropFirst())
let titles = !args.contains("--clean")
args.removeAll { $0 == "--clean" }
func opt(_ name: String) -> Double? {
    guard let i = args.firstIndex(of: name), i + 1 < args.count else { return nil }
    return Double(args[i + 1])
}
if let i = args.firstIndex(of: "--stills"), i + 2 < args.count + 0 || i + 2 == args.count {
    let times = args[i + 2].split(separator: ",").compactMap { Double($0) }
    writeStills(dir: args[i + 1], times: times, titles: titles)
} else if let out = args.first {
    try writeMovie(path: out, from: opt("--from") ?? 0, to: opt("--to") ?? DURATION, titles: titles)
} else {
    print("usage: render out.mp4 [--clean] [--from S --to S] | render --stills DIR t1,t2,... [--clean]")
}
