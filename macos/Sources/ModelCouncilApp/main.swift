import AppKit
import Darwin
import Foundation
import SwiftUI
import WebKit

struct StartupFailure: Error {
    let title: String
    let message: String
    let details: String
    let remediation: String
}

enum AppPhase {
    case launching(String)
    case failed(StartupFailure)
    case ready(URL)
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var onTerminate: (() -> Void)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard
            let resourceURL = Bundle.main.resourceURL,
            let image = NSImage(contentsOf: resourceURL.appendingPathComponent("AppIcon-1024.png"))
        else {
            return
        }
        NSApplication.shared.applicationIconImage = image
    }

    func applicationWillTerminate(_ notification: Notification) {
        onTerminate?()
    }
}

@MainActor
final class AppModel: ObservableObject {
    @Published var phase: AppPhase = .launching("Preparing desktop environment…")

    private var backendProcess: Process?
    private var started = false

    func startIfNeeded() {
        guard !started else {
            return
        }
        started = true
        Task {
            await start()
        }
    }

    func retry() {
        shutdown()
        started = true
        Task {
            await start()
        }
    }

    func shutdown() {
        guard let backendProcess else {
            return
        }
        if backendProcess.isRunning {
            backendProcess.terminate()
            DispatchQueue.global().asyncAfter(deadline: .now() + 1.0) {
                if backendProcess.isRunning {
                    kill(backendProcess.processIdentifier, SIGKILL)
                }
            }
        }
        self.backendProcess = nil
    }

    private func start() async {
        do {
            let resources = try AppResources.resolve()
            phase = .launching("Checking required local CLIs…")
            try RequirementChecker.verifyAll()
            phase = .launching("Starting bundled backend…")
            let launch = try BackendLauncher.launch(resources: resources)
            backendProcess = launch.process
            phase = .launching("Waiting for local server…")
            try await BackendLauncher.waitForHealth(url: launch.url, process: launch.process)
            phase = .ready(launch.url)
        } catch let failure as StartupFailure {
            phase = .failed(failure)
        } catch {
            phase = .failed(
                StartupFailure(
                    title: "Desktop startup failed",
                    message: "The macOS wrapper could not finish launching.",
                    details: String(describing: error),
                    remediation: "Rebuild the app bundle and try again."
                )
            )
        }
    }
}

struct AppResources {
    let python: URL
    let frontendDist: URL
    let dataDirectory: URL

    static func resolve() throws -> AppResources {
        guard let resourcesRoot = Bundle.main.resourceURL else {
            throw StartupFailure(
                title: "App bundle is incomplete",
                message: "The macOS app could not resolve its bundled resources.",
                details: "Bundle.main.resourceURL was nil.",
                remediation: "Rebuild the app bundle."
            )
        }

        let python = resourcesRoot.appendingPathComponent("python/bin/python3")
        let frontendDist = resourcesRoot.appendingPathComponent("frontend-dist")
        guard FileManager.default.fileExists(atPath: python.path) else {
            throw StartupFailure(
                title: "Bundled Python runtime is missing",
                message: "This app bundle does not contain its packaged Python runtime.",
                details: python.path,
                remediation: "Run the macOS build script again so it recreates the bundle."
            )
        }
        guard FileManager.default.fileExists(atPath: frontendDist.path) else {
            throw StartupFailure(
                title: "Bundled frontend is missing",
                message: "This app bundle does not contain the built web UI.",
                details: frontendDist.path,
                remediation: "Rebuild the frontend and package the app again."
            )
        }

        let dataDirectory = try FileLocations.ensureAppSupportDirectory()
        return AppResources(python: python, frontendDist: frontendDist, dataDirectory: dataDirectory)
    }
}

enum FileLocations {
    static func ensureAppSupportDirectory() throws -> URL {
        let fm = FileManager.default
        let base = try fm.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        let root = base.appendingPathComponent("Model Council", isDirectory: true)
        let conversations = root.appendingPathComponent("conversations", isDirectory: true)
        let debug = root.appendingPathComponent("debug", isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: true)
        try fm.createDirectory(at: conversations, withIntermediateDirectories: true)
        try fm.createDirectory(at: debug, withIntermediateDirectories: true)
        return root
    }
}

struct RequirementChecker {
    struct Requirement {
        let name: String
        let installHint: String
        let command: [String]
    }

    static func verifyAll() throws {
        let environment = DesktopEnvironment.processEnvironment()
        let checks = [
            Requirement(
                name: "Claude Code",
                installHint: "Install Claude Code and run `claude auth status` until it succeeds.",
                command: ["claude", "auth", "status"]
            ),
            Requirement(
                name: "Gemini CLI",
                installHint: "Install Gemini CLI and confirm `gemini --version` works in Terminal.",
                command: ["gemini", "--version"]
            ),
            Requirement(
                name: "Codex CLI",
                installHint: "Install Codex CLI and run `codex login status` until it succeeds.",
                command: ["codex", "login", "status"]
            ),
        ]

        for requirement in checks {
            try verify(requirement, environment: environment)
        }
    }

    private static func verify(_ requirement: Requirement, environment: [String: String]) throws {
        guard let executable = resolveExecutable(requirement.command[0], environment: environment) else {
            throw StartupFailure(
                title: "\(requirement.name) is missing",
                message: "This app depends on the local \(requirement.name) executable.",
                details: "Command not found on PATH: \(requirement.command[0])",
                remediation: requirement.installHint
            )
        }

        let result = run([executable] + requirement.command.dropFirst(), environment: environment)
        guard result.status == 0 else {
            let detail = [result.stdout, result.stderr]
                .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
                .joined(separator: "\n")
            throw StartupFailure(
                title: "\(requirement.name) needs setup",
                message: "The local \(requirement.name) CLI is installed but not ready for use.",
                details: detail.isEmpty ? "Command failed: \(requirement.command.joined(separator: " "))" : detail,
                remediation: requirement.installHint
            )
        }
    }

    private static func resolveExecutable(_ name: String, environment: [String: String]) -> String? {
        let shellResult = run(
            ["/bin/zsh", "-ilc", "command -v \(shellEscape(name))"],
            environment: environment,
            useEnvWrapper: false
        )
        let shellPath = shellResult.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        if shellResult.status == 0, !shellPath.isEmpty {
            return shellPath
        }

        let pathValue = environment["PATH"] ?? ""
        for part in pathValue.split(separator: ":") {
            let candidate = URL(fileURLWithPath: String(part)).appendingPathComponent(name).path
            if FileManager.default.isExecutableFile(atPath: candidate) {
                return candidate
            }
        }
        return nil
    }

    @discardableResult
    private static func run(
        _ command: [String],
        environment: [String: String],
        useEnvWrapper: Bool = true
    ) -> CommandResult {
        precondition(!command.isEmpty)
        let process = Process()
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        process.environment = environment
        if useEnvWrapper {
            process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
            process.arguments = command
        } else {
            process.executableURL = URL(fileURLWithPath: command[0])
            process.arguments = Array(command.dropFirst())
        }

        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return CommandResult(status: 127, stdout: "", stderr: String(describing: error))
        }

        let stdout = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let stderr = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return CommandResult(status: process.terminationStatus, stdout: stdout, stderr: stderr)
    }
}

struct CommandResult {
    let status: Int32
    let stdout: String
    let stderr: String
}

enum DesktopEnvironment {
    static func processEnvironment() -> [String: String] {
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = resolvedPath(basePath: environment["PATH"])
        return environment
    }

    private static func resolvedPath(basePath: String?) -> String {
        var ordered: [String] = []
        var seen = Set<String>()

        func append(_ value: String?) {
            guard let value, !value.isEmpty else {
                return
            }
            for raw in value.split(separator: ":") {
                let expanded = NSString(string: String(raw)).expandingTildeInPath
                guard !expanded.isEmpty else {
                    continue
                }
                if seen.insert(expanded).inserted {
                    ordered.append(expanded)
                }
            }
        }

        append(basePath)
        append(loginShellPath())
        append([
            "~/.local/bin",
            "~/.nvm/versions/node/current/bin",
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            "/Library/Frameworks/Python.framework/Versions/3.11/bin",
        ].joined(separator: ":"))

        return ordered.joined(separator: ":")
    }

    private static func loginShellPath() -> String? {
        let shell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        let result = shellCommand(shell: shell, command: "echo -n $PATH")
        let value = result.stdout.trimmingCharacters(in: .whitespacesAndNewlines)
        guard result.status == 0, !value.isEmpty else {
            return nil
        }
        return value
    }

    private static func shellCommand(shell: String, command: String) -> CommandResult {
        let shellPath = FileManager.default.isExecutableFile(atPath: shell) ? shell : "/bin/zsh"
        let process = Process()
        let outPipe = Pipe()
        let errPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = errPipe
        process.executableURL = URL(fileURLWithPath: shellPath)
        process.arguments = ["-ilc", command]
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return CommandResult(status: 127, stdout: "", stderr: String(describing: error))
        }
        let stdout = String(data: outPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        let stderr = String(data: errPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return CommandResult(status: process.terminationStatus, stdout: stdout, stderr: stderr)
    }
}

private func shellEscape(_ value: String) -> String {
    "'" + value.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

enum BackendLauncher {
    struct LaunchResult {
        let process: Process
        let url: URL
    }

    static func launch(resources: AppResources) throws -> LaunchResult {
        let port = try findOpenPort()
        let baseURL = URL(string: "http://127.0.0.1:\(port)")!
        let logURL = try prepareLogFile(in: resources.dataDirectory)
        var environment = DesktopEnvironment.processEnvironment()

        let process = Process()
        process.executableURL = resources.python
        process.arguments = [
            "-m", "uvicorn",
            "backend.main:app",
            "--host", "127.0.0.1",
            "--port", "\(port)",
        ]
        environment["MODEL_COUNCIL_DATA_DIR"] = resources.dataDirectory.path
        environment["MODEL_COUNCIL_FRONTEND_DIST"] = resources.frontendDist.path
        environment["MODEL_COUNCIL_HOST"] = "127.0.0.1"
        environment["MODEL_COUNCIL_PORT"] = "\(port)"
        environment["MODEL_COUNCIL_DESKTOP_MODE"] = "1"
        process.environment = environment

        let handle = try FileHandle(forWritingTo: logURL)
        handle.seekToEndOfFile()
        process.standardOutput = handle
        process.standardError = handle

        do {
            try process.run()
        } catch {
            throw StartupFailure(
                title: "Backend failed to start",
                message: "The bundled Python backend could not be launched.",
                details: String(describing: error),
                remediation: "Rebuild the app bundle. If the problem persists, inspect the latest desktop log in Application Support/Model Council."
            )
        }

        return LaunchResult(process: process, url: baseURL)
    }

    static func waitForHealth(url: URL, process: Process) async throws {
        let healthURL = url.appending(path: "api/health")
        let deadline = Date().addingTimeInterval(12)
        while Date() < deadline {
            if !process.isRunning {
                throw StartupFailure(
                    title: "Backend exited early",
                    message: "The bundled backend stopped before the app became ready.",
                    details: "Check the latest desktop log under Application Support/Model Council.",
                    remediation: "Rebuild the app bundle and try again."
                )
            }

            var request = URLRequest(url: healthURL)
            request.timeoutInterval = 1
            do {
                let (_, response) = try await URLSession.shared.data(for: request)
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    return
                }
            } catch {
                try? await Task.sleep(nanoseconds: 300_000_000)
            }
        }

        throw StartupFailure(
            title: "Backend readiness timed out",
            message: "The local backend did not respond in time.",
            details: healthURL.absoluteString,
            remediation: "Quit the app and try again. If it keeps failing, inspect the desktop log in Application Support/Model Council."
        )
    }

    private static func prepareLogFile(in dataDirectory: URL) throws -> URL {
        let logsDirectory = dataDirectory.appendingPathComponent("logs", isDirectory: true)
        try FileManager.default.createDirectory(at: logsDirectory, withIntermediateDirectories: true)
        let stamp = ISO8601DateFormatter().string(from: Date()).replacingOccurrences(of: ":", with: "-")
        let logURL = logsDirectory.appendingPathComponent("desktop-\(stamp).log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: Data())
        }
        return logURL
    }

    private static func findOpenPort() throws -> Int {
        for candidate in 8765...8865 {
            if isPortAvailable(candidate) {
                return candidate
            }
        }
        throw StartupFailure(
            title: "No local port available",
            message: "The desktop wrapper could not find a free localhost port for the backend.",
            details: "Tried ports 8765 through 8865.",
            remediation: "Close other local servers and try again."
        )
    }

    private static func isPortAvailable(_ port: Int) -> Bool {
        let socketFD = socket(AF_INET, SOCK_STREAM, 0)
        if socketFD == -1 {
            return false
        }
        defer { close(socketFD) }

        var value: Int32 = 1
        setsockopt(socketFD, SOL_SOCKET, SO_REUSEADDR, &value, socklen_t(MemoryLayout<Int32>.size))

        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))

        return withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) == 0
            }
        }
    }
}

struct WebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.setValue(false, forKey: "drawsBackground")
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        if nsView.url != url {
            nsView.load(URLRequest(url: url))
        }
    }
}

struct RootView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        Group {
            switch model.phase {
            case .launching(let message):
                VStack(spacing: 16) {
                    ProgressView()
                        .controlSize(.large)
                    Text("Model Council")
                        .font(.system(size: 28, weight: .semibold))
                    Text(message)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(40)

            case .failed(let failure):
                VStack(alignment: .leading, spacing: 16) {
                    Text(failure.title)
                        .font(.system(size: 28, weight: .semibold))
                    Text(failure.message)
                        .foregroundStyle(.secondary)
                    GroupBox("Details") {
                        ScrollView {
                            Text(failure.details)
                                .font(.system(.body, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .textSelection(.enabled)
                        }
                        .frame(minHeight: 120)
                    }
                    GroupBox("How to fix it") {
                        Text(failure.remediation)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    HStack {
                        Button("Retry") {
                            model.retry()
                        }
                        .keyboardShortcut(.defaultAction)
                        Spacer()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .padding(28)

            case .ready(let url):
                WebView(url: url)
            }
        }
        .frame(minWidth: 1080, minHeight: 760)
        .task {
            model.startIfNeeded()
        }
    }
}

@main
struct ModelCouncilDesktopApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("Model Council") {
            RootView(model: model)
                .onAppear {
                    appDelegate.onTerminate = {
                        model.shutdown()
                    }
                }
        }
        .windowResizability(.contentSize)
    }
}
