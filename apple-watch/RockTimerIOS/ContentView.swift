import SwiftUI

struct ContentView: View {
    @EnvironmentObject var state: RockTimerState
    @Environment(\.horizontalSizeClass) var hSizeClass

    var body: some View {
        GeometryReader { geo in
            let isLandscape = geo.size.width > geo.size.height
            Group {
                if isLandscape {
                    LandscapeView()
                } else {
                    PortraitView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.black.ignoresSafeArea())
        }
    }
}

// MARK: - Portrait

struct PortraitView: View {
    @EnvironmentObject var state: RockTimerState
    @EnvironmentObject var client: RockTimerClient

    var body: some View {
        VStack(spacing: 0) {
            HeaderBar()
                .padding(.horizontal)
                .padding(.top, 8)

            VStack(spacing: 12) {
                HStack(spacing: 12) {
                    TimeCardView(
                        label: "Tee–Hog",
                        value: state.teeHogFormatted,
                        color: .pink
                    )
                    TimeCardView(
                        label: "Hog–Hog",
                        value: state.hogHogFormatted,
                        color: .orange
                    )
                }
                .padding(.horizontal)

                RearmButton()
                    .padding(.horizontal)
            }
            .padding(.top, 16)

            Divider()
                .background(Color.gray.opacity(0.3))
                .padding(.top, 12)

            HistoryView()
        }
        .foregroundColor(.white)
    }
}

// MARK: - Landscape

struct LandscapeView: View {
    @EnvironmentObject var state: RockTimerState

    var body: some View {
        HStack(spacing: 0) {
            // Left: time cards + rearm
            VStack(spacing: 12) {
                HeaderBar()
                HStack(spacing: 12) {
                    TimeCardView(label: "Tee–Hog", value: state.teeHogFormatted, color: .pink)
                    TimeCardView(label: "Hog–Hog", value: state.hogHogFormatted, color: .orange)
                }
                RearmButton()
            }
            .padding()
            .frame(maxWidth: .infinity)

            Divider()
                .background(Color.gray.opacity(0.3))

            // Right: history
            HistoryView()
                .frame(maxWidth: .infinity)
        }
        .foregroundColor(.white)
    }
}

// MARK: - Header Bar

struct HeaderBar: View {
    @EnvironmentObject var state: RockTimerState

    var body: some View {
        HStack(spacing: 8) {
            HourglassLogo()
            Text("Rock Timer")
                .font(.headline)
                .fontWeight(.bold)
                .foregroundColor(.white)

            Spacer()

            SensorDots()

            StatusDot(state: state.systemState)
        }
    }
}

// MARK: - Hourglass Logo

struct HourglassLogo: View {
    var body: some View {
        VStack(spacing: 2) {
            // Upper half-circle (pink, flat side down)
            HalfCircle(flipped: false)
                .fill(Color.pink)
                .frame(width: 22, height: 11)
            // Lower half-circle (orange, flat side up)
            HalfCircle(flipped: true)
                .fill(Color.orange)
                .frame(width: 22, height: 11)
        }
    }
}

struct HalfCircle: Shape {
    var flipped: Bool
    func path(in rect: CGRect) -> Path {
        var p = Path()
        let flat = flipped ? rect.minY : rect.maxY
        let curved = flipped ? rect.maxY : rect.minY
        p.move(to: CGPoint(x: rect.minX, y: flat))
        p.addLine(to: CGPoint(x: rect.maxX, y: flat))
        p.addArc(
            center: CGPoint(x: rect.midX, y: flat),
            radius: rect.width / 2,
            startAngle: .degrees(0),
            endAngle: .degrees(180),
            clockwise: !flipped
        )
        p.closeSubpath()
        return p
    }
}

// MARK: - Status Dot

struct StatusDot: View {
    let state: SystemState
    @State private var pulse = false

    var body: some View {
        Circle()
            .fill(state.color)
            .frame(width: 12, height: 12)
            .scaleEffect(pulse ? 1.15 : 1.0)
            .opacity(pulse ? 0.6 : 1.0)
            .animation(
                state == .armed || state == .measuring
                    ? .easeInOut(duration: 0.8).repeatForever()
                    : .default,
                value: pulse
            )
            .onAppear { pulse = state == .armed || state == .measuring }
            .onChange(of: state) { _, new in
                pulse = new == .armed || new == .measuring
            }
    }
}

// MARK: - Sensor Dots

struct SensorDots: View {
    @EnvironmentObject var state: RockTimerState

    var body: some View {
        HStack(spacing: 6) {
            ForEach(state.sensors) { sensor in
                Circle()
                    .fill(sensor.status == "online" ? Color.green : Color.red)
                    .frame(width: 10, height: 10)
                    .help(sensor.label)
            }
        }
    }
}

// MARK: - Time Card

struct TimeCardView: View {
    let label: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 6) {
            Text(label)
                .font(.subheadline)
                .fontWeight(.medium)
                .opacity(0.85)
            Text(value)
                .font(.system(size: 52, weight: .bold, design: .monospaced))
                .minimumScaleFactor(0.4)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 110)
        .padding(.vertical, 16)
        .padding(.horizontal, 10)
        .foregroundColor(.white)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(
                    LinearGradient(
                        colors: [color, color.opacity(0.7)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
        )
    }
}

// MARK: - Rearm Button

struct RearmButton: View {
    @EnvironmentObject var state: RockTimerState
    @EnvironmentObject var client: RockTimerClient

    var body: some View {
        Button {
            Task { await client.arm() }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "arrow.counterclockwise")
                    .font(.system(size: 17, weight: .semibold))
                Text("Rearm")
                    .font(.system(size: 16, weight: .semibold))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .background(
                LinearGradient(
                    colors: [Color(red: 0.13, green: 0.76, blue: 0.76),
                             Color(red: 0.18, green: 0.80, blue: 0.44)],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .foregroundColor(.white)
            .clipShape(RoundedRectangle(cornerRadius: 14))
        }
        .disabled(state.systemState == .measuring)
        .opacity(state.systemState == .measuring ? 0.5 : 1)
    }
}

// MARK: - History View

struct HistoryView: View {
    @EnvironmentObject var state: RockTimerState
    @EnvironmentObject var client: RockTimerClient

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("History")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundColor(.gray)
                Spacer()
                Button("Clear") {
                    Task { await client.clearHistory() }
                }
                .font(.caption)
                .foregroundColor(.red)
            }
            .padding(.horizontal)
            .padding(.vertical, 8)

            if state.history.isEmpty {
                Text("No measurements yet")
                    .foregroundColor(.gray)
                    .font(.caption)
                    .padding()
            } else {
                List(state.history) { record in
                    HStack {
                        Text(formattedTime(record.timestamp))
                            .font(.caption)
                            .foregroundColor(.gray)
                            .frame(width: 60, alignment: .leading)
                        Spacer()
                        Text(record.teeHogFormatted)
                            .font(.system(.body, design: .monospaced))
                            .fontWeight(.bold)
                            .foregroundColor(.pink)
                        Spacer()
                        Text(record.hogHogFormatted)
                            .font(.system(.body, design: .monospaced))
                            .fontWeight(.bold)
                            .foregroundColor(.orange)
                    }
                    .listRowBackground(Color.black)
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .task {
            await client.fetchHistory()
        }
    }

    private func formattedTime(_ iso: String?) -> String {
        guard let iso else { return "--" }
        let df = ISO8601DateFormatter()
        df.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        guard let date = df.date(from: iso) else { return "--" }
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f.string(from: date)
    }
}

// MARK: - Preview

#Preview {
    ContentView()
        .environmentObject(RockTimerState())
        .environmentObject(RockTimerClient(state: RockTimerState()))
}
