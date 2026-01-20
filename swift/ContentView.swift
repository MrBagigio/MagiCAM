import SwiftUI

// Custom colors compatible with iOS 14
extension Color {
    static let cyanCompat = Color(red: 0.0, green: 0.8, blue: 0.95)
    static let darkBg1 = Color(red: 0.05, green: 0.05, blue: 0.15)
    static let darkBg2 = Color(red: 0.1, green: 0.1, blue: 0.25)
}

struct ContentView: View {
    @StateObject var manager = ARSessionManager()
    @State var host: String = "192.168.1.100"
    @State var port: String = "9000"
    @State var isRunning = false
    @State var showSettings = false
    @State var frameCount: Int = 0
    
    // Timer for updating frame count
    let timer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            // Background gradient (iOS 14 compatible)
            LinearGradient(
                gradient: Gradient(colors: [Color.darkBg1, Color.darkBg2]),
                startPoint: .top,
                endPoint: .bottom
            )
            .edgesIgnoringSafeArea(.all)
            
            VStack(spacing: 0) {
                // Header
                headerView
                
                Spacer()
                
                // Main content
                VStack(spacing: 30) {
                    // Status indicator
                    statusView
                    
                    // Connection fields
                    connectionFieldsView
                    
                    // Control buttons
                    controlButtonsView
                    
                    // Stats
                    if isRunning {
                        statsView
                    }
                }
                .padding(.horizontal, 30)
                
                Spacer()
                
                // Footer info
                footerView
            }
        }
        .preferredColorScheme(.dark)
        .onReceive(timer) { _ in
            if isRunning {
                frameCount += 1
            }
        }
    }
    
    // MARK: - Header
    var headerView: some View {
        VStack(spacing: 8) {
            HStack {
                Image(systemName: "camera.viewfinder")
                    .font(.system(size: 32, weight: .light))
                    .foregroundColor(Color.cyanCompat)
                
                Text("MagiCAM")
                    .font(.system(size: 36, weight: .bold, design: .rounded))
                    .foregroundColor(Color.cyanCompat)
            }
            
            Text("ARKit Camera Tracking")
                .font(.system(size: 14, weight: .medium))
                .foregroundColor(.gray)
        }
        .padding(.top, 60)
        .padding(.bottom, 20)
    }
    
    // MARK: - Status View
    var statusView: some View {
        VStack(spacing: 12) {
            ZStack {
                // Outer ring
                Circle()
                    .stroke(
                        isRunning ? Color.green.opacity(0.3) : Color.gray.opacity(0.2),
                        lineWidth: 4
                    )
                    .frame(width: 120, height: 120)
                
                // Animated ring when running
                if isRunning {
                    Circle()
                        .trim(from: 0, to: 0.7)
                        .stroke(
                            LinearGradient(
                                gradient: Gradient(colors: [.green, Color.cyanCompat]),
                                startPoint: .leading,
                                endPoint: .trailing
                            ),
                            style: StrokeStyle(lineWidth: 4, lineCap: .round)
                        )
                        .frame(width: 120, height: 120)
                        .rotationEffect(.degrees(Double(frameCount) * 10))
                        .animation(.linear(duration: 0.5))
                }
                
                // Inner circle
                Circle()
                    .fill(
                        RadialGradient(
                            gradient: Gradient(colors: isRunning ? [Color.green.opacity(0.3), Color.clear] : [Color.gray.opacity(0.1), Color.clear]),
                            center: .center,
                            startRadius: 0,
                            endRadius: 50
                        )
                    )
                    .frame(width: 100, height: 100)
                
                // Icon
                Image(systemName: isRunning ? "wave.3.right" : "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: 36))
                    .foregroundColor(isRunning ? .green : .gray)
            }
            
            Text(isRunning ? "STREAMING" : "OFFLINE")
                .font(.system(size: 16, weight: .bold, design: .monospaced))
                .foregroundColor(isRunning ? .green : .gray)
                .tracking(4)
        }
    }
    
    // MARK: - Connection Fields
    var connectionFieldsView: some View {
        VStack(spacing: 16) {
            // Host field
            HStack {
                Image(systemName: "network")
                    .foregroundColor(Color.cyanCompat)
                    .frame(width: 30)
                
                TextField("Host IP", text: $host)
                    .keyboardType(.numbersAndPunctuation)
                    .autocapitalization(.none)
                    .foregroundColor(.white)
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.white.opacity(0.08))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.cyanCompat.opacity(0.3), lineWidth: 1)
                    )
            )
            
            // Port field
            HStack {
                Image(systemName: "number")
                    .foregroundColor(.purple)
                    .frame(width: 30)
                
                TextField("Port", text: $port)
                    .keyboardType(.numberPad)
                    .foregroundColor(.white)
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.white.opacity(0.08))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.purple.opacity(0.3), lineWidth: 1)
                    )
            )
        }
    }
    
    // MARK: - Control Buttons
    var controlButtonsView: some View {
        HStack(spacing: 20) {
            // Start/Stop button
            Button(action: {
                withAnimation(.spring(response: 0.4, dampingFraction: 0.7)) {
                    if isRunning {
                        manager.stop()
                        isRunning = false
                        frameCount = 0
                    } else {
                        let p = UInt16(port) ?? 9000
                        manager.start(host: host, port: p)
                        isRunning = true
                    }
                }
            }) {
                HStack(spacing: 10) {
                    Image(systemName: isRunning ? "stop.fill" : "play.fill")
                        .font(.system(size: 18, weight: .bold))
                    
                    Text(isRunning ? "STOP" : "START")
                        .font(.system(size: 16, weight: .bold, design: .rounded))
                }
                .foregroundColor(.white)
                .frame(width: 140, height: 56)
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(
                            LinearGradient(
                                gradient: Gradient(colors: isRunning ? [.red, .orange] : [.green, Color.cyanCompat]),
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .shadow(color: isRunning ? Color.red.opacity(0.4) : Color.green.opacity(0.4), radius: 10, y: 5)
                )
            }
            
            // Calibrate button
            Button(action: {
                manager.sendCalibrationOnce()
                // Haptic feedback
                let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                impactFeedback.impactOccurred()
            }) {
                HStack(spacing: 8) {
                    Image(systemName: "scope")
                        .font(.system(size: 18, weight: .medium))
                    
                    Text("CALIBRATE")
                        .font(.system(size: 14, weight: .bold, design: .rounded))
                }
                .foregroundColor(.white)
                .frame(width: 140, height: 56)
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(
                            LinearGradient(
                                gradient: Gradient(colors: [.blue, .purple]),
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .shadow(color: Color.purple.opacity(0.3), radius: 10, y: 5)
                )
            }
            .disabled(!isRunning)
            .opacity(isRunning ? 1.0 : 0.5)
        }
    }
    
    // MARK: - Stats View
    var statsView: some View {
        HStack(spacing: 30) {
            StatBox(icon: "arrow.up.arrow.down", label: "RATE", value: "60 Hz", color: Color.cyanCompat)
            StatBox(icon: "cube.transparent", label: "SCALE", value: "×100", color: .purple)
            StatBox(icon: "checkmark.circle", label: "STATUS", value: "OK", color: .green)
        }
        .padding(.top, 10)
        .transition(.opacity.combined(with: .scale(scale: 0.9)))
    }
    
    // MARK: - Footer
    var footerView: some View {
        VStack(spacing: 8) {
            Divider()
                .background(Color.gray.opacity(0.3))
            
            HStack(spacing: 6) {
                Image(systemName: "wifi")
                    .foregroundColor(.gray)
                    .font(.system(size: 12))
                
                Text("Ensure device and Maya are on same network")
                    .font(.system(size: 12))
                    .foregroundColor(.gray)
            }
            .padding(.vertical, 12)
        }
    }
}

// MARK: - Stat Box Component
struct StatBox: View {
    let icon: String
    let label: String
    let value: String
    let color: Color
    
    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundColor(color)
            
            Text(value)
                .font(.system(size: 14, weight: .bold, design: .monospaced))
                .foregroundColor(.white)
            
            Text(label)
                .font(.system(size: 10, weight: .medium))
                .foregroundColor(.gray)
                .tracking(1)
        }
        .frame(width: 80)
        .padding(.vertical, 12)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.white.opacity(0.05))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(color.opacity(0.2), lineWidth: 1)
                )
        )
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
