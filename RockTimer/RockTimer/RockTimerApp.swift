//
//  RockTimerApp.swift
//  RockTimer
//
//  Created by Katrin Boberg Bevemyr on 24/2/2026.
//

import SwiftUI

@main
struct RockTimerApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

struct RootView: View {
    @StateObject private var state = RockTimerState()
    @StateObject private var client: RockTimerClient
    @StateObject private var speech: SpeechManager

    init() {
        let s = RockTimerState()
        _state = StateObject(wrappedValue: s)
        _client = StateObject(wrappedValue: RockTimerClient(state: s))
        _speech = StateObject(wrappedValue: SpeechManager(state: s))
    }

    var body: some View {
        ContentView()
            .environmentObject(state)
            .environmentObject(client)
    }
}

