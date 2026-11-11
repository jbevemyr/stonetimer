//
//  SettingsView.swift
//  RockTimer
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var state: RockTimerState
    @EnvironmentObject var client: RockTimerClient
    @Environment(\.dismiss) var dismiss

    @State private var draft: ServerSettings = .defaultSettings
    @State private var autoRearmMinutes: Double = 2
    // Stored on this iPhone only; does not touch the server's speaker setting.
    @AppStorage(SpeechManager.enabledKey) private var phoneSpeechEnabled = false

    var body: some View {
        NavigationStack {
            Form {
                // MARK: Connection
                Section {
                    HStack {
                        Label("Server", systemImage: "network")
                        Spacer()
                        Text(client.serverBase)
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }
                    HStack(spacing: 6) {
                        Circle()
                            .fill(state.isConnected ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        Text(state.isConnected ? "Connected" : "Not connected")
                            .foregroundStyle(.secondary)
                            .font(.caption)
                    }
                } header: {
                    Text("Connection")
                }

                // MARK: iPhone Voice
                Section {
                    Toggle(isOn: $phoneSpeechEnabled) {
                        Label("Read times on iPhone", systemImage: "iphone.radiowaves.left.and.right")
                    }

                    Toggle(isOn: $draft.speech_enabled) {
                        Label("Read times on timer speaker", systemImage: "speaker.wave.2")
                    }

                    if phoneSpeechEnabled || draft.speech_enabled {
                        Toggle(isOn: $draft.speak_ready) {
                            Text("Say ready to go when armed")
                        }
                        .padding(.leading, 8)

                        Toggle(isOn: $draft.speak_tee_hog) {
                            Text("Announce Tee–Hog time")
                        }
                        .padding(.leading, 8)

                        Toggle(isOn: $draft.speak_hog_hog) {
                            Text("Announce Hog–Hog time")
                        }
                        .padding(.leading, 8)
                    }
                } header: {
                    Text("Voice")
                } footer: {
                    Text("The iPhone switch only affects this phone (headphones or speaker). The timer speaker and what gets announced are shared by everyone.")
                }

                // MARK: Auto-rearm
                Section {
                    Toggle(isOn: $draft.auto_rearm_enabled) {
                        Label("Auto-rearm if stuck", systemImage: "arrow.counterclockwise.circle")
                    }

                    if draft.auto_rearm_enabled {
                        HStack {
                            Text("After (minutes)")
                                .padding(.leading, 8)
                            Spacer()
                            TextField("2", value: $autoRearmMinutes, format: .number)
                                .keyboardType(.decimalPad)
                                .multilineTextAlignment(.trailing)
                                .frame(width: 60)
                        }
                    }
                } header: {
                    Text("Auto-rearm")
                } footer: {
                    if draft.auto_rearm_enabled {
                        Text("If no completion is detected after \(autoRearmMinutes, format: .number) min, RockTimer returns to Armed automatically.")
                    }
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        draft.autoRearmMinutes = autoRearmMinutes
                        Task {
                            await client.saveSettings(draft)
                            dismiss()
                        }
                    }
                }
            }
            .task {
                await client.fetchSettings()
                draft = state.settings
                autoRearmMinutes = state.settings.autoRearmMinutes
            }
            .onChange(of: state.settings) { _, new in
                draft = new
                autoRearmMinutes = new.autoRearmMinutes
            }
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(RockTimerState())
        .environmentObject(RockTimerClient(state: RockTimerState()))
}
