import SwiftUI

@main
struct RockTimerIOSApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

struct RootView: View {
    @StateObject private var state = RockTimerState()
    @StateObject private var client: RockTimerClient

    init() {
        let s = RockTimerState()
        _state = StateObject(wrappedValue: s)
        _client = StateObject(wrappedValue: RockTimerClient(state: s))
    }

    var body: some View {
        ContentView()
            .environmentObject(state)
            .environmentObject(client)
    }
}
