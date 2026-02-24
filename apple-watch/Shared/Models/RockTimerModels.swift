// Shared models for RockTimer iOS and watchOS apps

import Foundation
import SwiftUI

// MARK: - System State

public enum SystemState: String, Codable, Sendable {
    case idle
    case armed
    case measuring
    case completed

    public var displayText: String {
        switch self {
        case .idle:       return "Ready"
        case .armed:      return "Armed"
        case .measuring:  return "Measuring…"
        case .completed:  return "Done"
        }
    }

    public var color: Color {
        switch self {
        case .idle:       return .gray
        case .armed:      return .yellow
        case .measuring:  return .blue
        case .completed:  return .green
        }
    }
}

// MARK: - API Response Models

public struct StatusResponse: Codable, Sendable {
    public let state: String
    public let session: SessionData
}

public struct SessionData: Codable, Sendable {
    public let tee_to_hog_close_ms: Double?
    public let hog_to_hog_ms: Double?
    public let total_ms: Double?
}

public struct SensorInfo: Codable, Sendable, Identifiable {
    public let device_id: String
    public let label: String
    public let status: String
    public let last_seen_s_ago: Double?
    public var id: String { device_id }
}

public struct TimesRecord: Codable, Sendable, Identifiable {
    public let id: Int
    public let timestamp: String?
    public let tee_to_hog_close_ms: Double?
    public let hog_to_hog_ms: Double?
    public let total_ms: Double?

    public var teeHogFormatted: String {
        guard let ms = tee_to_hog_close_ms, ms > 0 else { return "--" }
        return String(format: "%.2f", ms / 1000)
    }

    public var hogHogFormatted: String {
        guard let ms = hog_to_hog_ms, ms > 0 else { return "--" }
        return String(format: "%.2f", ms / 1000)
    }
}

// MARK: - Timer State (shared observable)

@MainActor
public final class RockTimerState: ObservableObject {
    @Published public var systemState: SystemState = .idle
    @Published public var teeToHogMs: Double?
    @Published public var hogToHogMs: Double?
    @Published public var isConnected: Bool = false
    @Published public var sensors: [SensorInfo] = []
    @Published public var history: [TimesRecord] = []

    public var teeHogFormatted: String {
        guard let ms = teeToHogMs, ms > 0 else { return "--" }
        return String(format: "%.2f", ms / 1000)
    }

    public var hogHogFormatted: String {
        guard let ms = hogToHogMs, ms > 0 else { return "--" }
        return String(format: "%.2f", ms / 1000)
    }

    public init() {}
}
