//
//  RockTimerModels.swift
//  RockTimer
//
//  Created by Katrin Boberg Bevemyr on 24/2/2026.
//

// Shared models for RockTimer iOS and watchOS apps

import Foundation
import SwiftUI
import Observation
import Combine

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
    /// false when the sensor's clock is out of sync with the server (times unreliable).
    public let clock_ok: Bool?
    public var id: String { device_id }
}

/// Envelope returned by GET /api/sensors
public struct SensorsResponse: Codable, Sendable {
    public let sensors: [SensorInfo]
}

public struct TimesRecord: Codable, Sendable, Identifiable {
    public let id: Int
    public let timestamp: String?
    public let tee_to_hog_close_ms: Double?
    public let hog_to_hog_ms: Double?
    public let total_ms: Double?

    public var teeHogFormatted: String {
        guard let ms = tee_to_hog_close_ms, ms > 0 else { return "--.--" }
        return String(format: "%.2f", ms / 1000)
    }

    public var hogHogFormatted: String {
        guard let ms = hog_to_hog_ms, ms > 0 else { return "--.--" }
        return String(format: "%.2f", ms / 1000)
    }
}

// MARK: - Server Settings

public struct ServerSettings: Codable, Sendable, Equatable {
    public var speech_enabled: Bool
    public var speak_ready: Bool
    public var speak_tee_hog: Bool
    public var speak_hog_hog: Bool
    public var auto_rearm_enabled: Bool
    public var auto_rearm_after_s: Double

    public static var defaultSettings: ServerSettings {
        ServerSettings(
            speech_enabled: false,
            speak_ready: false,
            speak_tee_hog: false,
            speak_hog_hog: false,
            auto_rearm_enabled: false,
            auto_rearm_after_s: 120
        )
    }

    public var autoRearmMinutes: Double {
        get { auto_rearm_after_s / 60 }
        set { auto_rearm_after_s = newValue * 60 }
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
    @Published public var settings: ServerSettings = .defaultSettings

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

