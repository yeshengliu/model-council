import AppKit
import CoreImage
import CoreImage.CIFilterBuiltins
import Foundation

struct IconRenderer {
    let inputURL: URL
    let outputURL: URL

    let canvasSize = CGSize(width: 1024, height: 1024)
    let outerRect = CGRect(x: 36, y: 36, width: 952, height: 952)
    let outerRadius: CGFloat = 230
    let artInset: CGFloat = 74
    let artRadius: CGFloat = 176

    func run() throws {
        guard
            let sourceImage = NSImage(contentsOf: inputURL),
            let sourceCG = sourceImage.cgImage(forProposedRect: nil, context: nil, hints: nil)
        else {
            throw NSError(domain: "IconRenderer", code: 1, userInfo: [NSLocalizedDescriptionKey: "Failed to load source image"])
        }

        guard
            let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil,
                pixelsWide: Int(canvasSize.width),
                pixelsHigh: Int(canvasSize.height),
                bitsPerSample: 8,
                samplesPerPixel: 4,
                hasAlpha: true,
                isPlanar: false,
                colorSpaceName: .deviceRGB,
                bytesPerRow: 0,
                bitsPerPixel: 0
            )
        else {
            throw NSError(domain: "IconRenderer", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to allocate bitmap"])
        }

        rep.size = canvasSize
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        let context = NSGraphicsContext(bitmapImageRep: rep)
        NSGraphicsContext.current = context

        guard let cg = context?.cgContext else {
            throw NSError(domain: "IconRenderer", code: 3, userInfo: [NSLocalizedDescriptionKey: "Failed to acquire graphics context"])
        }

        cg.setAllowsAntialiasing(true)
        cg.interpolationQuality = .high

        drawBase(in: cg)
        try drawAmbientArtwork(source: sourceCG, in: cg)
        drawPanel(in: cg)
        drawArtwork(source: sourceCG, in: cg)
        drawHighlights(in: cg)

        guard let png = rep.representation(using: .png, properties: [:]) else {
            throw NSError(domain: "IconRenderer", code: 4, userInfo: [NSLocalizedDescriptionKey: "Failed to encode PNG"])
        }
        try png.write(to: outputURL)
    }

    private func drawBase(in cg: CGContext) {
        let path = CGPath(roundedRect: outerRect, cornerWidth: outerRadius, cornerHeight: outerRadius, transform: nil)
        cg.saveGState()
        cg.setShadow(offset: CGSize(width: 0, height: -18), blur: 52, color: NSColor.black.withAlphaComponent(0.34).cgColor)
        cg.addPath(path)
        cg.setFillColor(NSColor(calibratedRed: 0.08, green: 0.13, blue: 0.20, alpha: 1).cgColor)
        cg.fillPath()
        cg.restoreGState()

        cg.saveGState()
        cg.addPath(path)
        cg.clip()

        let colors = [
            NSColor(calibratedRed: 0.18, green: 0.30, blue: 0.44, alpha: 1).cgColor,
            NSColor(calibratedRed: 0.07, green: 0.11, blue: 0.16, alpha: 1).cgColor,
        ] as CFArray
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 1])!
        cg.drawLinearGradient(gradient, start: CGPoint(x: 112, y: 968), end: CGPoint(x: 900, y: 72), options: [])
        cg.restoreGState()
    }

    private func drawAmbientArtwork(source: CGImage, in cg: CGContext) throws {
        let ciContext = CIContext(options: nil)
        let ciInput = CIImage(cgImage: source)
        let blur = CIFilter.gaussianBlur()
        blur.inputImage = ciInput
        blur.radius = 26
        guard let blurred = blur.outputImage else {
            return
        }

        let crop = blurred.cropped(to: CGRect(origin: .zero, size: CGSize(width: source.width, height: source.height)))
        guard let blurredCG = ciContext.createCGImage(crop, from: crop.extent) else {
            return
        }

        let ambientRect = outerRect.insetBy(dx: -54, dy: -54)
        let clipPath = CGPath(roundedRect: outerRect, cornerWidth: outerRadius, cornerHeight: outerRadius, transform: nil)

        cg.saveGState()
        cg.addPath(clipPath)
        cg.clip()
        cg.setAlpha(0.44)
        cg.draw(blurredCG, in: ambientRect)
        cg.restoreGState()
    }

    private func drawPanel(in cg: CGContext) {
        let panelRect = outerRect.insetBy(dx: 18, dy: 18)
        let panelPath = CGPath(roundedRect: panelRect, cornerWidth: outerRadius - 18, cornerHeight: outerRadius - 18, transform: nil)

        cg.saveGState()
        cg.addPath(panelPath)
        cg.setStrokeColor(NSColor.white.withAlphaComponent(0.14).cgColor)
        cg.setLineWidth(2)
        cg.strokePath()
        cg.restoreGState()
    }

    private func drawArtwork(source: CGImage, in cg: CGContext) {
        let artRect = outerRect.insetBy(dx: artInset, dy: artInset)
        let artPath = CGPath(roundedRect: artRect, cornerWidth: artRadius, cornerHeight: artRadius, transform: nil)

        cg.saveGState()
        cg.setShadow(offset: CGSize(width: 0, height: -10), blur: 24, color: NSColor.black.withAlphaComponent(0.26).cgColor)
        cg.addPath(artPath)
        cg.setFillColor(NSColor(calibratedWhite: 1, alpha: 0.09).cgColor)
        cg.fillPath()
        cg.restoreGState()

        cg.saveGState()
        cg.addPath(artPath)
        cg.clip()
        let drawRect = artRect.insetBy(dx: -12, dy: -12)
        cg.draw(source, in: drawRect)
        cg.restoreGState()

        cg.saveGState()
        cg.addPath(artPath)
        cg.setStrokeColor(NSColor.white.withAlphaComponent(0.18).cgColor)
        cg.setLineWidth(2)
        cg.strokePath()
        cg.restoreGState()
    }

    private func drawHighlights(in cg: CGContext) {
        let glossRect = CGRect(x: outerRect.minX + 52, y: outerRect.midY + 116, width: outerRect.width - 104, height: 246)
        let glossPath = CGPath(roundedRect: glossRect, cornerWidth: 120, cornerHeight: 120, transform: nil)
        cg.saveGState()
        cg.addPath(glossPath)
        cg.clip()
        let colors = [
            NSColor.white.withAlphaComponent(0.22).cgColor,
            NSColor.white.withAlphaComponent(0.02).cgColor,
            NSColor.white.withAlphaComponent(0.0).cgColor,
        ] as CFArray
        let gradient = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.58, 1])!
        cg.drawLinearGradient(
            gradient,
            start: CGPoint(x: glossRect.midX, y: glossRect.maxY),
            end: CGPoint(x: glossRect.midX, y: glossRect.minY),
            options: []
        )
        cg.restoreGState()

        let spec = CGRect(x: outerRect.minX + 120, y: outerRect.maxY - 200, width: 210, height: 76)
        let specPath = CGPath(ellipseIn: spec, transform: nil)
        cg.saveGState()
        cg.addPath(specPath)
        cg.setFillColor(NSColor.white.withAlphaComponent(0.16).cgColor)
        cg.fillPath()
        cg.restoreGState()
    }
}

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    fputs("Usage: render_macos26_icon.swift <input-image> <output-png>\n", stderr)
    exit(1)
}

do {
    let renderer = IconRenderer(
        inputURL: URL(fileURLWithPath: arguments[1]),
        outputURL: URL(fileURLWithPath: arguments[2])
    )
    try renderer.run()
} catch {
    fputs("error: \(error.localizedDescription)\n", stderr)
    exit(1)
}
