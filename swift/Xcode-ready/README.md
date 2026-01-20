MagiCAM — Xcode quickstart

1. In Xcode, create a new project (App, SwiftUI, iOS target).
2. Replace the default `ContentView.swift`, `App` file, and add `ARSessionManager.swift` from this repo (`swift/ContentView.swift`, `swift/ARKitSenderApp.swift`, `swift/ARSessionManager.swift`).
3. Copy `Info.plist` from this folder into the project (or add the NSCameraUsageDescription string to your project's Info.plist).
4. Set a valid development team in the project signing to run on a device.
5. Build and run on device (not simulator) and ensure the iPhone and your Maya machine are on the same Wi‑Fi. Use the Host/Port fields to point to your Maya machine IP and port (default 9000).

Tips:
- If you want to use OSC instead of JSON-UDP, start the Maya receiver with `use_osc=True` and install `python-osc` in the Maya Python environment.
- The built-in "Calibrate" button sends a single `type:'calib'` message; call `maya_receiver.calibrate()` in Maya beforehand to set the desired camera target.
