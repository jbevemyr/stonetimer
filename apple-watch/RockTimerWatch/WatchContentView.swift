import SwiftUI
import WatchKit

struct WatchContentView: View {
    @EnvironmentObject var state: RockTimerState

    var body: some View {
        TabView {
            WatchTimesView()
            WatchControlView()
        }
        .tabViewStyle(.carousel)
    }
}

// MARK: - Times View

struct WatchTimesView: View {
    @EnvironmentObject var state: RockTimerState

    var body: some View {
        VStack(spacing: 6) {
            WatchStatusBadge(state: state.systemState)

            HStack(spacing: 8) {
                WatchTimeBlock(label: "T→H", value: state.teeHogFormatted, color: .pink)
                WatchTimeBlock(label: "H→H", value: state.hogHogFormatted, color: .orange)
            }

            HStack(spacing: 4) {
                Circle()
                    .fill(state.isConnected ? Color.green : Color.red)
                    .frame(width: 6, height: 6)
                Text(state.isConnected ? "Connected" : "Offline")
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)
            }
        }
        .padding(8)
    }
}

// MARK: - Control View

struct WatchControlView: View {
    @EnvironmentObject var state: RockTimerState
    @EnvironmentObject var client: RockTimerClient

    var body: some View {
        VStack(spacing: 12) {
            WatchStatusBadge(state: state.systemState)

            if state.systemState == .measuring {
                Button {
                    Task {
                        await client.disarm()
                        WKInterfaceDevice.current().play(.failure)
                    }
                } label: {
                    Label("Cancel", systemImage: "xmark.circle")
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
            } else {
                Button {
                    Task {
                        await client.arm()
                        WKInterfaceDevice.current().play(.click)
                    }
                } label: {
                    Label("Rearm", systemImage: "arrow.counterclockwise")
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
            }
        }
        .padding(8)
    }
}

// MARK: - Supporting Views

struct WatchStatusBadge: View {
    let state: SystemState

    var body: some View {
        Text(state.displayText)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(state.color.opacity(0.25))
            .foregroundColor(state.color)
            .clipShape(Capsule())
    }
}

struct WatchTimeBlock: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.system(size: 9, weight: .medium))
                .foregroundColor(.secondary)
            Text(value)
                .font(.system(size: 18, weight: .bold, design: .monospaced))
                .foregroundColor(color)
                .minimumScaleFactor(0.6)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity)
        .padding(8)
        .background(color.opacity(0.15))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Preview

#Preview {
    WatchContentView()
        .environmentObject(RockTimerState())
        .environmentObject(RockTimerClient(state: RockTimerState(), usePolling: true))
}
