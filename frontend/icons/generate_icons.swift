// Reproducible PWA icon generator for Dengbêj AI.
//
// The repository has no approved portrait or historical image. These icons use
// only the existing approved DENGBÊJ wordmark and established site palette
// (#7a3b10 accent, #faf9f7 page background). No new cultural imagery is added.
// Run on macOS: swift frontend/icons/generate_icons.swift

import AppKit
import Foundation

let outputDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let background = NSColor(calibratedRed: 122.0 / 255.0, green: 59.0 / 255.0, blue: 16.0 / 255.0, alpha: 1.0)
let foreground = NSColor(calibratedRed: 250.0 / 255.0, green: 249.0 / 255.0, blue: 247.0 / 255.0, alpha: 1.0)
let wordmark = "DENGBÊJ"

func renderIcon(size: Int) throws {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: size,
        pixelsHigh: size,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 0,
        bitsPerPixel: 0
    ) else { throw NSError(domain: "DengbejIcon", code: 1) }

    NSGraphicsContext.saveGraphicsState()
    guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
        NSGraphicsContext.restoreGraphicsState()
        throw NSError(domain: "DengbejIcon", code: 2)
    }
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    context.shouldAntialias = true

    background.setFill()
    NSBezierPath(rect: NSRect(x: 0, y: 0, width: size, height: size)).fill()

    let paragraph = NSMutableParagraphStyle()
    paragraph.alignment = .center
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: CGFloat(size) * 0.115, weight: .bold),
        .foregroundColor: foreground,
        .paragraphStyle: paragraph,
        .kern: CGFloat(size) * 0.006
    ]
    let measured = wordmark.size(withAttributes: attributes)
    let rect = NSRect(
        x: CGFloat(size) * 0.06,
        y: (CGFloat(size) - measured.height) / 2.0,
        width: CGFloat(size) * 0.88,
        height: measured.height
    )
    wordmark.draw(in: rect, withAttributes: attributes)
    context.flushGraphics()
    NSGraphicsContext.restoreGraphicsState()

    guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw NSError(domain: "DengbejIcon", code: 3)
    }
    try png.write(to: outputDirectory.appendingPathComponent("dengbej-\(size).png"))
}

for size in [192, 512] {
    try renderIcon(size: size)
}
