"""MagiCAM v2: camera virtuale iPhone (ARKit) -> UDP -> Maya.

Solo `magicam.maya_bridge` e `magicam.ui` importano `maya` / `PySide6`; tutto il resto e' Python puro e si prova
fuori da Maya con `magicam.simulator`.
"""

__version__ = "2.0.0a0"
PROTOCOL_VERSION = 2
