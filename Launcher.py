import sys
import os
import shutil
import tempfile
import importlib
from pathlib import Path

sys.path.append(r"C:\Users\alexg\Documents\maya\scripts\MagiCAM\maya")
import maya_receiver


def clear_magicam_cache():
    """Stop server, clear runtime state and remove temp logs/dirs so Maya doesn't need restart."""
    global maya_receiver
    try:
        # Stop any running server
        try:
            if getattr(maya_receiver, 'SERVER_RUNNING', False):
                maya_receiver.stop_server()
        except Exception:
            pass

        try:
            maya_receiver.disable_logging()
        except Exception:
            pass

        # Reset in-memory state (includes additional state variables)
        for name in ('RECEIVED_FRAMES', 'DROPPED_FRAMES', 'LAST_MATRIX', 'CALIB_MATRIX', 
                     'TARGET_MATRIX', 'LAST_QUAT', 'LAST_POS', 'LAST_RECEIVE_TIME'):
            if hasattr(maya_receiver, name):
                try:
                    if name in ('RECEIVED_FRAMES', 'DROPPED_FRAMES'):
                        setattr(maya_receiver, name, 0)
                    elif name == 'LAST_RECEIVE_TIME':
                        setattr(maya_receiver, name, 0.0)
                    else:
                        setattr(maya_receiver, name, None)
                except Exception:
                    pass

        # Remove known log file
        try:
            log_path = Path('C:/temp/magicam_log.csv')
            if log_path.exists():
                log_path.unlink()
        except Exception:
            pass

        # Remove temporary stress dirs created by runner
        tmpdir = Path(tempfile.gettempdir())
        for p in tmpdir.iterdir():
            try:
                if p.name.startswith('magicam_stress_'):
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
            except Exception:
                pass

        # Remove local tmp folders used during IPA work
        for d in ('tmp_extract', 'tmp_check_repack'):
            try:
                p = Path(d)
                if p.exists() and p.is_dir():
                    shutil.rmtree(p)
            except Exception:
                pass

        # Reload module to clear any cached state - update global reference
        try:
            maya_receiver = importlib.reload(maya_receiver)
        except Exception:
            pass

        print('MagiCAM cache cleared.')
    except Exception as e:
        print('Error clearing MagiCAM cache:', e)


# Clear cache automatically to avoid needing to restart Maya
clear_magicam_cache()

# Open the UI (use the reloaded module)
maya_receiver.show_ui()   # apre la finestra: premi "Start"

# --- DEBUG HELPERS (temporary) ---
# If you want to auto-enable logging and set the Faithful preset when Launcher
# is executed inside Maya (useful for quick debugging), set DEBUG_ON_START = True.
DEBUG_ON_START = True
if DEBUG_ON_START:
    try:
        maya_receiver.enable_logging('C:/temp/magicam_log.csv')
    except Exception as e:
        print('Debug: enable_logging failed:', e)
    try:
        maya_receiver.reset_calibration()
    except Exception as e:
        print('Debug: reset_calibration failed:', e)
    try:
        # apply faithful preset (no smoothing, direct 1:1)
        maya_receiver._apply_preset_faithful()
    except Exception as e:
        print('Debug: apply_preset_faithful failed:', e)
    print('Debug startup: logging enabled, calibration reset, faithful preset applied')
# --- END DEBUG HELPERS ---