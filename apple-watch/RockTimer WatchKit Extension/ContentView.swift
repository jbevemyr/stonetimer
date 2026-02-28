//
//  ContentView.swift
//  RockTimer WatchKit Extension
//
//  Curling timing - Apple Watch app
//

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = TimerViewModel()
    
    var body: some View {
        TabView {
            // Main view with times
            TimesView(viewModel: viewModel)
            
            // Controls view
            ControlView(viewModel: viewModel)
        }
        .tabViewStyle(.carousel)
    }
}

// MARK: - Times View
struct TimesView: View {
    @ObservedObject var viewModel: TimerViewModel
    
    var body: some View {
        ScrollView {
            VStack(spacing: 8) {
                // Status
                StatusBadge(state: viewModel.systemState)
                
                // Total time - large display
                VStack(spacing: 2) {
                    Text("TOTAL")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(.secondary)
                    
                    Text(viewModel.totalTimeFormatted)
                        .font(.system(size: 36, weight: .bold, design: .monospaced))
                        .foregroundColor(.cyan)
                }
                .padding(.vertical, 8)
                
                // Splits
                HStack(spacing: 16) {
                    TimeBlock(
                        label: "T→H",
                        value: viewModel.teeToHogFormatted,
                        isComplete: viewModel.teeToHogMs != nil
                    )
                    
                    TimeBlock(
                        label: "H→H",
                        value: viewModel.hogToHogFormatted,
                        isComplete: viewModel.hogToHogMs != nil
                    )
                }
            }
            .padding()
        }
    }
}

// MARK: - Control View
struct ControlView: View {
    @ObservedObject var viewModel: TimerViewModel
    
    var body: some View {
        VStack(spacing: 16) {
            StatusBadge(state: viewModel.systemState)
            
            if viewModel.systemState == .idle || viewModel.systemState == .completed {
                Button(action: {
                    viewModel.armSystem()
                }) {
                    HStack {
                        Image(systemName: "target")
                        Text("Arm")
                    }
                    .font(.headline)
                }
                .buttonStyle(.borderedProminent)
                .tint(.green)
            } else {
                Button(action: {
                    viewModel.disarmSystem()
                }) {
                    HStack {
                        Image(systemName: "xmark.circle")
                        Text("Cancel")
                    }
                    .font(.headline)
                }
                .buttonStyle(.borderedProminent)
                .tint(.red)
            }
            
            // Connection status
            HStack {
                Circle()
                    .fill(viewModel.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)
                Text(viewModel.isConnected ? "Connected" : "Disconnected")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
    }
}

// MARK: - Supporting Views
struct StatusBadge: View {
    let state: SystemState
    
    var body: some View {
        Text(state.displayText)
            .font(.system(size: 11, weight: .semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 4)
            .background(state.color.opacity(0.2))
            .foregroundColor(state.color)
            .clipShape(Capsule())
    }
}

struct TimeBlock: View {
    let label: String
    let value: String
    let isComplete: Bool
    
    var body: some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.system(size: 9, weight: .medium))
                .foregroundColor(.secondary)
            
            Text(value)
                .font(.system(size: 16, weight: .bold, design: .monospaced))
                .foregroundColor(isComplete ? .green : .gray)
        }
        .frame(maxWidth: .infinity)
        .padding(8)
        .background(Color.gray.opacity(0.2))
        .cornerRadius(8)
    }
}

// MARK: - System State
enum SystemState: String, Codable {
    case idle
    case armed
    case measuring
    case completed
    
    var displayText: String {
        switch self {
        case .idle: return "READY"
        case .armed: return "ARMED"
        case .measuring: return "MEASURING..."
        case .completed: return "DONE"
        }
    }
    
    var color: Color {
        switch self {
        case .idle: return .gray
        case .armed: return .yellow
        case .measuring: return .cyan
        case .completed: return .green
        }
    }
}

// MARK: - Preview
struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}

