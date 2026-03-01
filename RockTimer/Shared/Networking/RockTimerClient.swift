//
//  RockTimerClient.swift
//  RockTimer
//
//  Created by Katrin Boberg Bevemyr on 24/2/2026.
//


// RockTimerClient – handles REST polling and WebSocket updates
// Used by both iOS and watchOS targets.

import Foundation
import Combine

@MainActor
public final class RockTimerClient: ObservableObject {

    // MARK: - Configuration

    /// Base URL to the RockTimer server. Change to match your Pi's address/port.
    public var serverBase: String {
        get { _serverBase }
        set { _serverBase = newValue; reconnectWebSocket() }
    }

    private var _serverBase: String
    private let state: RockTimerState

    // MARK: - WebSocket

    private var webSocketTask: URLSessionWebSocketTask?
    private var webSocketActive = false

    // MARK: - Polling fallback (watchOS doesn't support WebSocket well)

    private var pollTimer: Timer?
    private let usePollFallback: Bool

    // MARK: - Init

    public init(state: RockTimerState, serverBase: String = "http://192.168.50.1:8080", usePolling: Bool = false) {
        self.state = state
        self._serverBase = serverBase
        self.usePollFallback = usePolling

        if usePolling {
            startPolling()
        } else {
            connectWebSocket()
        }
        Task { await fetchHistory() }
        Task { await fetchSensors() }
        startHistoryPolling()
    }

    deinit {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        pollTimer?.invalidate()
    }

    // MARK: - WebSocket

    private func connectWebSocket() {
        guard !usePollFallback else { return }
        let wsBase = _serverBase
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
        guard let url = URL(string: "\(wsBase)/ws") else { return }

        webSocketTask?.cancel(with: .goingAway, reason: nil)
        let session = URLSession(configuration: .default)
        webSocketTask = session.webSocketTask(with: url)
        webSocketTask?.resume()
        webSocketActive = true
        receiveWebSocket()
    }

    private func receiveWebSocket() {
        guard webSocketActive else { return }
        webSocketTask?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let message):
                if case .string(let text) = message {
                    Task { @MainActor in self.handleWebSocketMessage(text) }
                }
                self.receiveWebSocket()
            case .failure:
                Task { @MainActor in
                    self.state.isConnected = false
                    // Reconnect after delay
                    try? await Task.sleep(for: .seconds(3))
                    self.connectWebSocket()
                }
            }
        }
    }

    private func handleWebSocketMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let obj = try? JSONDecoder().decode(WebSocketMessage.self, from: data),
              obj.type == "state_update",
              let payload = obj.data
        else { return }

        applyStatusPayload(payload)
        state.isConnected = true
    }

    private func reconnectWebSocket() {
        guard !usePollFallback else { return }
        webSocketActive = false
        connectWebSocket()
    }

    // MARK: - Polling

    private func startPolling() {
        pollTimer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { await self.fetchStatus() }
        }
        Task { await fetchStatus() }
    }

    private func startHistoryPolling() {
        Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { await self.fetchHistory() }
        }
    }

    // MARK: - REST API

    public func fetchStatus() async {
        guard let url = URL(string: "\(_serverBase)/api/status") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(for: request(url))
            let response = try JSONDecoder().decode(StatusResponse.self, from: data)
            applyStatusPayload(response)
            state.isConnected = true
        } catch {
            state.isConnected = false
        }
    }

    public func arm() async {
        await postAction("arm")
        await fetchStatus()
    }

    public func disarm() async {
        await postAction("disarm")
        await fetchStatus()
    }

    public func fetchHistory() async {
        guard let url = URL(string: "\(_serverBase)/api/times?limit=20") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(for: request(url))
            let records = try JSONDecoder().decode([TimesRecord].self, from: data)
            state.history = records
        } catch {}
    }

    public func fetchSensors() async {
        guard let url = URL(string: "\(_serverBase)/api/sensors") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(for: request(url))
            let sensors = try JSONDecoder().decode([SensorInfo].self, from: data)
            state.sensors = sensors
        } catch {}
    }

    public func fetchSettings() async {
        guard let url = URL(string: "\(_serverBase)/api/settings") else { return }
        do {
            let (data, _) = try await URLSession.shared.data(for: request(url))
            let settings = try JSONDecoder().decode(ServerSettings.self, from: data)
            state.settings = settings
        } catch {}
    }

    public func saveSettings(_ settings: ServerSettings) async {
        guard let url = URL(string: "\(_serverBase)/api/settings") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 5
        req.httpBody = try? JSONEncoder().encode(settings)
        _ = try? await URLSession.shared.data(for: req)
        await fetchSettings()
    }

    public func clearHistory() async {
        guard let url = URL(string: "\(_serverBase)/api/clear") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 5
        _ = try? await URLSession.shared.data(for: req)
        await fetchHistory()
    }

    // MARK: - Helpers

    private func applyStatusPayload(_ response: StatusResponse) {
        let newState = SystemState(rawValue: response.state) ?? .idle
        let wasCompleted = state.systemState != .completed && newState == .completed
        state.systemState = newState
        state.teeToHogMs = response.session.tee_to_hog_close_ms
        state.hogToHogMs = response.session.hog_to_hog_ms
        if wasCompleted {
            Task { await fetchHistory() }
        }
    }

    private func postAction(_ action: String) async {
        guard let url = URL(string: "\(_serverBase)/api/\(action)") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 5
        _ = try? await URLSession.shared.data(for: req)
    }

    private func request(_ url: URL) -> URLRequest {
        var req = URLRequest(url: url)
        req.timeoutInterval = 5
        return req
    }
}

// MARK: - WebSocket message envelope

private struct WebSocketMessage: Codable {
    let type: String
    let data: StatusResponse?
}
