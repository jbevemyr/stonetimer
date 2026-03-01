//
//  SpeechManager.swift
//  RockTimer
//
//  Reads out times locally on iPhone using AVSpeechSynthesizer.
//

import AVFoundation
import SwiftUI
import Combine

@MainActor
final class SpeechManager: ObservableObject {
    private let synthesizer = AVSpeechSynthesizer()
    private var cancellables = Set<AnyCancellable>()

    // Track previous values to only speak when they first appear
    private var lastState: SystemState = .idle
    private var lastTeeHogMs: Double? = nil
    private var lastHogHogMs: Double? = nil

    init(state: RockTimerState) {
        // Configure audio session so speech works with silent switch and mixes with music
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: .duckOthers)
        try? AVAudioSession.sharedInstance().setActive(true)

        // Observe state changes
        state.$systemState
            .combineLatest(state.$teeToHogMs, state.$hogToHogMs, state.$settings)
            .receive(on: RunLoop.main)
            .sink { [weak self] newState, teeMs, hogMs, settings in
                guard let self else { return }
                self.handle(
                    newState: newState,
                    teeMs: teeMs,
                    hogMs: hogMs,
                    settings: settings
                )
            }
            .store(in: &cancellables)
    }

    private func handle(
        newState: SystemState,
        teeMs: Double?,
        hogMs: Double?,
        settings: ServerSettings
    ) {
        guard settings.speech_enabled else { return }

        // "Ready to go" on armed transition
        if newState == .armed && lastState != .armed {
            if settings.speak_ready {
                speak("Ready to go", interrupt: true)
            }
            // Reset trackers so we detect new times in the upcoming run
            lastTeeHogMs = nil
            lastHogHogMs = nil
        }

        // Reset trackers when server clears the times (new run started)
        if teeMs == nil || teeMs! <= 0 { lastTeeHogMs = nil }
        if hogMs == nil || hogMs! <= 0 { lastHogHogMs = nil }

        // Only announce times during measuring or completed – not while still showing old session values at arming
        if newState == .measuring || newState == .completed {
            // Tee–Hog: announce once when first available
            if settings.speak_tee_hog,
               let ms = teeMs, ms > 0,
               lastTeeHogMs == nil {
                speak(formatSeconds(ms / 1000))
            }

            // Hog–Hog: announce once when first available
            if settings.speak_hog_hog,
               let ms = hogMs, ms > 0,
               lastHogHogMs == nil {
                speak(formatSeconds(ms / 1000))
            }
        }

        lastState = newState
        lastTeeHogMs = teeMs
        lastHogHogMs = hogMs
    }

    private func speak(_ text: String, interrupt: Bool = false) {
        if interrupt { synthesizer.stopSpeaking(at: .immediate) }
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = 0.48
        utterance.pitchMultiplier = 1.0
        synthesizer.speak(utterance)
    }

    /// Formats seconds like "3 point 18", "3 point oh 6"
    private func formatSeconds(_ seconds: Double) -> String {
        let formatted = String(format: "%.2f", seconds)
        let parts = formatted.split(separator: ".")
        guard parts.count == 2 else { return formatted }
        let whole = String(parts[0])
        let dec = String(parts[1])
        let decSpoken: String
        if dec == "00" {
            decSpoken = "00"
        } else if dec.hasPrefix("0") {
            decSpoken = "oh \(dec.dropFirst())"
        } else {
            decSpoken = dec
        }
        return "\(whole) point \(decSpoken)"
    }
}
