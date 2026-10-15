import sys
import os
import types
import pytest

# Ensure maya package path is importable (add the 'maya' folder to sys.path)
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Add project root so 'maya' package (folder) is importable as 'maya'
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Ensure a minimal maya.cmds exists at import time so importing maya.maya_receiver works during collection
_fake_module = types.ModuleType('maya.cmds')

def _xform_query(*args, **kwargs):
    return [1.0,0.0,0.0,0.0, 0.0,1.0,0.0,0.0, 0.0,0.0,1.0,0.0, 0.0,0.0,0.0,1.0]

def _evalDeferred(fn):
    try:
        fn()
    except Exception:
        pass

setattr(_fake_module, 'xform', _xform_query)
setattr(_fake_module, 'warning', lambda msg: None)
setattr(_fake_module, 'evalDeferred', _evalDeferred)
setattr(_fake_module, 'objExists', lambda name: True)

# Create a simple 'maya' package and place cmds submodule
maya_mod = types.ModuleType('maya')
# mark as package and set path to the 'maya' folder so submodules can be imported
maya_mod.__path__ = [os.path.join(ROOT, 'maya')]
maya_mod.cmds = _fake_module
sys.modules['maya'] = maya_mod
sys.modules['maya.cmds'] = _fake_module

# Provide a minimal maya.api and maya.api.OpenMaya shim used by the receiver
_openmaya = types.ModuleType('maya.api.OpenMaya')
_sys_api = types.ModuleType('maya.api')
_sys_api.OpenMaya = _openmaya
sys.modules['maya.api'] = _sys_api
sys.modules['maya.api.OpenMaya'] = _openmaya

class MMatrix:
    def __init__(self, lst=None):
        self.lst = list(lst) if lst is not None else [1.0,0.0,0.0,0.0,
                                                      0.0,1.0,0.0,0.0,
                                                      0.0,0.0,1.0,0.0,
                                                      0.0,0.0,0.0,1.0]
    def __iter__(self):
        return iter(self.lst)
    def __mul__(self, other):
        b = list(other)
        a = self.lst
        res = [0.0] * 16
        for i in range(4):
            for j in range(4):
                s = 0.0
                for k in range(4):
                    s += a[i*4 + k] * b[k*4 + j]
                res[i*4 + j] = s
        return MMatrix(res)
    def inverse(self):
        # Not a real inverse, but sufficient for tests that only need a placeholder
        return MMatrix(self.lst)

class MTransformationMatrix:
    def __init__(self, m):
        self.m = MMatrix(m)
    def asMatrix(self):
        return self.m

_openmaya.MMatrix = MMatrix
_openmaya.MTransformationMatrix = MTransformationMatrix
sys.modules['maya.api.OpenMaya'] = _openmaya

# Provide a fake minimal maya.cmds module for tests (more featureful per-test fixture)
class FakeCmds(types.SimpleNamespace):
    def __init__(self):
        super().__init__()
        self._last = [1.0,0.0,0.0,0.0,
                      0.0,1.0,0.0,0.0,
                      0.0,0.0,1.0,0.0,
                      0.0,0.0,0.0,1.0]
        self.xform_calls = []

    def xform(self, *args, **kwargs):
        # Query
        if kwargs.get('q', False) or (len(args) >= 2 and args[1] == 'q'):
            return self._last
        # Set matrix
        if 'matrix' in kwargs:
            self._last = kwargs['matrix']
            self.xform_calls.append(('matrix', kwargs['matrix']))
        elif len(args) >= 2 and isinstance(args[1], (list, tuple)):
            self._last = args[1]
            self.xform_calls.append(('matrix', args[1]))
        return None

    def objExists(self, name):
        # In tests we assume the camera exists
        return True

    def warning(self, msg):
        # print to see warnings in test output
        print('[maya.cmds.warning]', msg)

    def evalDeferred(self, fn):
        # Execute immediately for tests
        try:
            fn()
        except Exception as e:
            print('evalDeferred error:', e)

@pytest.fixture(autouse=True)
def fake_maya_cmds(monkeypatch):
    fake = FakeCmds()
    # insert into sys.modules as a module-like object
    monkeypatch.setitem(sys.modules, 'maya.cmds', fake)
    # also update any already-imported receiver module to use our fake cmds
    try:
        import importlib
        mr = importlib.import_module('maya.maya_receiver')
        mr.cmds = fake
    except Exception:
        pass
    yield fake
