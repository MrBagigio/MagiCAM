// Copy of ContentView for Xcode-ready project
import SwiftUI

struct ContentView: View {
    @StateObject var manager = ARSessionManager()
    @State var host: String = "192.168.1.100"
    @State var port: String = "9000"
    @State var isRunning = false

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Connection")) {
                    TextField("Host", text: $host)
                        .keyboardType(.numbersAndPunctuation)
                    TextField("Port", text: $port)
                        .keyboardType(.numberPad)
                    HStack {
                        Button(isRunning ? "Stop" : "Start") {
                            if isRunning {
                                manager.stop(); isRunning = false
                            } else {
                                let p = UInt16(port) ?? 9000
                                manager.start(host: host, port: p); isRunning = true
                            }
                        }
                        .foregroundColor(.white)
                        .padding()
                        .background(isRunning ? Color.red : Color.green)
                        .cornerRadius(8)

                        Button("Calibrate") {
                            manager.sendCalibrationOnce()
                        }
                        .padding()
                    }
                }

                Section(header: Text("Info")) {
                    Text("ARKit → UDP JSON (type: 'pose' or 'calib')")
                    Text("Ensure device and Maya machine are on same Wi‑Fi")
                }
            }
            .navigationTitle("MagiCAM Sender")
        }
    }
}

struct ContentView_Previews: PreviewProvider {
    static var previews: some View {
        ContentView()
    }
}
