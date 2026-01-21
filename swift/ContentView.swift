import SwiftUI

// Custom colors compatible with iOS 14
extension Color {
    static let cyanCompat = Color(red: 0.0, green: 0.8, blue: 0.95)
    static let darkBg1 = Color(red: 0.05, green: 0.05, blue: 0.15)
    static let darkBg2 = Color(red: 0.1, green: 0.1, blue: 0.25)
}

struct ContentView: View {
    @StateObject var manager = ARSessionManager()
    @StateObject var streamReceiver = ViewportStreamReceiver()
    @State var host: String = "192.168.1.100"
    @State var port: String = "9000"
    @State var streamPort: String = "9001"
    @State var isRunning = false
    @State var showSettings = false
    @State var showViewport = false
    @State var frameCount: Int = 0
    
    // Environment to detect orientation
    @Environment(\.horizontalSizeClass) var horizontalSizeClass
    @Environment(\.verticalSizeClass) var verticalSizeClass
    
    // Timer for updating frame count
    let timer = Timer.publish(every: 0.5, on: .main, in: .common).autoconnect()
    
    var isLandscape: Bool {
        verticalSizeClass == .compact
    }

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Background gradient (iOS 14 compatible)
                LinearGradient(
                    gradient: Gradient(colors: [Color.darkBg1, Color.darkBg2]),
                    startPoint: .top,
                    endPoint: .bottom
                )
                .edgesIgnoringSafeArea(.all)
                
                // Viewport stream overlay (when active)
                if showViewport, let frame = streamReceiver.currentFrame {
                    viewportOverlay(image: frame, geometry: geometry)
                }
                
                // Main content - adapts to orientation
                if isLandscape {
                    landscapeLayout(geometry: geometry)
                } else {
                    portraitLayout(geometry: geometry)
                }
            }
        }
        .preferredColorScheme(.dark)
        .onReceive(timer) { _ in
            if isRunning {
                frameCount += 1
            }
        }
    }
    
    // MARK: - Portrait Layout
    func portraitLayout(geometry: GeometryProxy) -> some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(spacing: 0) {
                // Header
                headerView(compact: false)
                
                Spacer().frame(height: 20)
                
                // Main content
                VStack(spacing: 24) {
                    // Status indicator
                    statusView(compact: false)
                    
                    // Connection fields
                    connectionFieldsView(compact: false)
                    
                    // Control buttons
                    controlButtonsView(compact: false)
                    
                    // Viewport stream button
                    viewportButtonView
                    
                    // Stats
                    if isRunning {
                        statsView(compact: false)
                    }
                }
                .padding(.horizontal, 30)
                
                Spacer().frame(height: 20)
                
                // Footer info
                footerView
            }
            .frame(minHeight: geometry.size.height)
        }
    }
    
    // MARK: - Landscape Layout
    func landscapeLayout(geometry: GeometryProxy) -> some View {
        HStack(spacing: 0) {
            // Left side - Status and controls
            VStack(spacing: 12) {
                headerView(compact: true)
                
                statusView(compact: true)
                
                controlButtonsView(compact: true)
                
                if isRunning {
                    statsView(compact: true)
                }
            }
            .frame(width: geometry.size.width * 0.45)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            
            // Divider
            Rectangle()
                .fill(Color.white.opacity(0.1))
                .frame(width: 1)
                .padding(.vertical, 20)
            
            // Right side - Connection fields and viewport
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 16) {
                    connectionFieldsView(compact: true)
                    
                    viewportButtonView
                    
                    footerView
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
            }
            .frame(width: geometry.size.width * 0.55 - 1)
        }
    }
    
    // MARK: - Viewport Overlay (FULLSCREEN)
    func viewportOverlay(image: UIImage, geometry: GeometryProxy) -> some View {
        ZStack {
            // Full black background
            Color.black
                .edgesIgnoringSafeArea(.all)
            
            // Fullscreen viewport image
            Image(uiImage: image)
                .resizable()
                .aspectRatio(contentMode: .fill)
                .frame(width: geometry.size.width, height: geometry.size.height)
                .clipped()
                .edgesIgnoringSafeArea(.all)
            
            // Overlay controls (top bar)
            VStack {
                HStack {
                    // FPS indicator
                    if streamReceiver.isConnected {
                        HStack(spacing: 4) {
                            Circle()
                                .fill(Color.green)
                                .frame(width: 8, height: 8)
                            Text("\(streamReceiver.fps) FPS")
                                .font(.system(size: 12, weight: .bold, design: .monospaced))
                                .foregroundColor(.green)
                        }
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.black.opacity(0.6))
                        .cornerRadius(8)
                    }
                    
                    Spacer()
                    
                    // Close button
                    Button(action: {
                        withAnimation(.spring()) {
                            showViewport = false
                            streamReceiver.stop()
                        }
                    }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 32))
                            .foregroundColor(.white.opacity(0.8))
                            .shadow(color: .black.opacity(0.5), radius: 4)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, isLandscape ? 10 : 50)
                
                Spacer()
                
                // Bottom hint
                Text("Maya Camera View")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(.white.opacity(0.6))
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(Color.black.opacity(0.4))
                    .cornerRadius(8)
                    .padding(.bottom, isLandscape ? 10 : 30)
            }
        }
        .transition(.opacity)
    }
    
    // MARK: - Header
    func headerView(compact: Bool) -> some View {
        VStack(spacing: compact ? 4 : 8) {
            HStack {
                Image(systemName: "camera.viewfinder")
                    .font(.system(size: compact ? 24 : 32, weight: .light))
                    .foregroundColor(Color.cyanCompat)
                
                Text("MagiCAM")
                    .font(.system(size: compact ? 28 : 36, weight: .bold, design: .rounded))
                    .foregroundColor(Color.cyanCompat)
            }
            
            if !compact {
                Text("ARKit Camera Tracking")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(.gray)
            }
        }
        .padding(.top, compact ? 8 : 60)
        .padding(.bottom, compact ? 8 : 20)
    }
    
    // MARK: - Status View
    func statusView(compact: Bool) -> some View {
        let size: CGFloat = compact ? 80 : 120
        let innerSize: CGFloat = compact ? 66 : 100
        let iconSize: CGFloat = compact ? 24 : 36
        
        return VStack(spacing: compact ? 8 : 12) {
            ZStack {
                // Outer ring
                Circle()
                    .stroke(
                        isRunning ? Color.green.opacity(0.3) : Color.gray.opacity(0.2),
                        lineWidth: compact ? 3 : 4
                    )
                    .frame(width: size, height: size)
                
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
                            style: StrokeStyle(lineWidth: compact ? 3 : 4, lineCap: .round)
                        )
                        .frame(width: size, height: size)
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
                            endRadius: innerSize / 2
                        )
                    )
                    .frame(width: innerSize, height: innerSize)
                
                // Icon
                Image(systemName: isRunning ? "wave.3.right" : "antenna.radiowaves.left.and.right.slash")
                    .font(.system(size: iconSize))
                    .foregroundColor(isRunning ? .green : .gray)
            }
            
            Text(isRunning ? "STREAMING" : "OFFLINE")
                .font(.system(size: compact ? 12 : 16, weight: .bold, design: .monospaced))
                .foregroundColor(isRunning ? .green : .gray)
                .tracking(compact ? 2 : 4)
        }
    }
    
    // MARK: - Connection Fields
    func connectionFieldsView(compact: Bool) -> some View {
        VStack(spacing: compact ? 10 : 16) {
            // Host field
            HStack {
                Image(systemName: "network")
                    .foregroundColor(Color.cyanCompat)
                    .frame(width: compact ? 24 : 30)
                
                TextField("Host IP", text: $host)
                    .keyboardType(.numbersAndPunctuation)
                    .autocapitalization(.none)
                    .foregroundColor(.white)
                    .font(.system(size: compact ? 14 : 17))
            }
            .padding(compact ? 10 : 16)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.white.opacity(0.08))
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(Color.cyanCompat.opacity(0.3), lineWidth: 1)
                    )
            )
            
            HStack(spacing: compact ? 8 : 12) {
                // Port field
                HStack {
                    Image(systemName: "number")
                        .foregroundColor(.purple)
                        .frame(width: 24)
                    
                    TextField("Port", text: $port)
                        .keyboardType(.numberPad)
                        .foregroundColor(.white)
                        .font(.system(size: compact ? 14 : 17))
                }
                .padding(compact ? 10 : 16)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.white.opacity(0.08))
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.purple.opacity(0.3), lineWidth: 1)
                        )
                )
                
                // Stream port field
                HStack {
                    Image(systemName: "video")
                        .foregroundColor(.orange)
                        .frame(width: 24)
                    
                    TextField("Stream", text: $streamPort)
                        .keyboardType(.numberPad)
                        .foregroundColor(.white)
                        .font(.system(size: compact ? 14 : 17))
                }
                .padding(compact ? 10 : 16)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.white.opacity(0.08))
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(Color.orange.opacity(0.3), lineWidth: 1)
                        )
                )
            }
        }
    }
    
    // MARK: - Control Buttons
    func controlButtonsView(compact: Bool) -> some View {
        let buttonWidth: CGFloat = compact ? 110 : 140
        let buttonHeight: CGFloat = compact ? 44 : 56
        let fontSize: CGFloat = compact ? 14 : 16
        let iconSize: CGFloat = compact ? 14 : 18
        
        return HStack(spacing: compact ? 12 : 20) {
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
                HStack(spacing: compact ? 6 : 10) {
                    Image(systemName: isRunning ? "stop.fill" : "play.fill")
                        .font(.system(size: iconSize, weight: .bold))
                    
                    Text(isRunning ? "STOP" : "START")
                        .font(.system(size: fontSize, weight: .bold, design: .rounded))
                }
                .foregroundColor(.white)
                .frame(width: buttonWidth, height: buttonHeight)
                .background(
                    RoundedRectangle(cornerRadius: compact ? 12 : 16)
                        .fill(
                            LinearGradient(
                                gradient: Gradient(colors: isRunning ? [.red, .orange] : [.green, Color.cyanCompat]),
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .shadow(color: isRunning ? Color.red.opacity(0.4) : Color.green.opacity(0.4), radius: compact ? 6 : 10, y: compact ? 3 : 5)
                )
            }
            
            // Calibrate button
            Button(action: {
                manager.sendCalibrationOnce()
                let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                impactFeedback.impactOccurred()
            }) {
                HStack(spacing: compact ? 4 : 8) {
                    Image(systemName: "scope")
                        .font(.system(size: iconSize, weight: .medium))
                    
                    Text("CALIBRATE")
                        .font(.system(size: compact ? 11 : 14, weight: .bold, design: .rounded))
                }
                .foregroundColor(.white)
                .frame(width: buttonWidth, height: buttonHeight)
                .background(
                    RoundedRectangle(cornerRadius: compact ? 12 : 16)
                        .fill(
                            LinearGradient(
                                gradient: Gradient(colors: [.blue, .purple]),
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .shadow(color: Color.purple.opacity(0.3), radius: compact ? 6 : 10, y: compact ? 3 : 5)
                )
            }
            .disabled(!isRunning)
            .opacity(isRunning ? 1.0 : 0.5)
        }
    }
    
    // MARK: - Viewport Button
    var viewportButtonView: some View {
        Button(action: {
            if showViewport {
                streamReceiver.stop()
                withAnimation(.spring()) {
                    showViewport = false
                }
            } else {
                let sp = UInt16(streamPort) ?? 9001
                streamReceiver.start(host: host, port: sp)
                withAnimation(.spring()) {
                    showViewport = true
                }
            }
            let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
            impactFeedback.impactOccurred()
        }) {
            HStack(spacing: 10) {
                Image(systemName: showViewport ? "eye.slash.fill" : "eye.fill")
                    .font(.system(size: isLandscape ? 14 : 18, weight: .medium))
                
                Text(showViewport ? "HIDE VIEWPORT" : "SHOW VIEWPORT")
                    .font(.system(size: isLandscape ? 12 : 14, weight: .bold, design: .rounded))
            }
            .foregroundColor(.white)
            .frame(maxWidth: .infinity)
            .frame(height: isLandscape ? 40 : 50)
            .background(
                RoundedRectangle(cornerRadius: isLandscape ? 10 : 14)
                    .fill(
                        LinearGradient(
                            gradient: Gradient(colors: showViewport ? [.orange, .red] : [.orange, .yellow]),
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .shadow(color: Color.orange.opacity(0.3), radius: isLandscape ? 4 : 8, y: isLandscape ? 2 : 4)
            )
        }
        .disabled(!isRunning)
        .opacity(isRunning ? 1.0 : 0.5)
    }
    
    // MARK: - Stats View
    func statsView(compact: Bool) -> some View {
        HStack(spacing: compact ? 12 : 30) {
            StatBox(icon: "arrow.up.arrow.down", label: "RATE", value: "60 Hz", color: Color.cyanCompat, compact: compact)
            StatBox(icon: "cube.transparent", label: "SCALE", value: "×100", color: .purple, compact: compact)
            StatBox(icon: "checkmark.circle", label: "STATUS", value: "OK", color: .green, compact: compact)
        }
        .padding(.top, compact ? 4 : 10)
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
                    .font(.system(size: isLandscape ? 10 : 12))
                    .foregroundColor(.gray)
            }
            .padding(.vertical, isLandscape ? 6 : 12)
        }
    }
}

// MARK: - Stat Box Component
struct StatBox: View {
    let icon: String
    let label: String
    let value: String
    let color: Color
    var compact: Bool = false
    
    var body: some View {
        VStack(spacing: compact ? 3 : 6) {
            Image(systemName: icon)
                .font(.system(size: compact ? 12 : 16))
                .foregroundColor(color)
            
            Text(value)
                .font(.system(size: compact ? 11 : 14, weight: .bold, design: .monospaced))
                .foregroundColor(.white)
            
            Text(label)
                .font(.system(size: compact ? 8 : 10, weight: .medium))
                .foregroundColor(.gray)
                .tracking(1)
        }
        .frame(width: compact ? 60 : 80)
        .padding(.vertical, compact ? 8 : 12)
        .background(
            RoundedRectangle(cornerRadius: compact ? 8 : 12)
                .fill(Color.white.opacity(0.05))
                .overlay(
                    RoundedRectangle(cornerRadius: compact ? 8 : 12)
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
