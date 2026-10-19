"""Fail the build if this distinct RX configuration acquires a transmit surface.

This is a narrow source guard, not a Swift compiler or proof of framework IO.
"""
import hashlib
import json
import plistlib
from pathlib import Path

root = Path(__file__).resolve().parents[1]
paths = sorted((root / 'ObserverApp').glob('*.swift')) + sorted((root / 'Core/Sources/ObserverCore').glob('*.swift'))
for path in paths:
    text = path.read_text(encoding='utf8')
    for forbidden in ['outputStream', 'OutputStream', 'sendKeepalive', 'sendBootstrap',
                      'URLSession', 'UserDefaults', 'import Network', 'serialPoll', 'CFWriteStream']:
        assert forbidden not in text, (path.name, forbidden)
plist = plistlib.loads((root / 'ObserverApp/Info.plist').read_bytes())
assert plist['UISupportedExternalAccessoryProtocols'] == ['com.dji.logiclink']
assert plist['UIFileSharingEnabled'] is True
assert 'UIBackgroundModes' not in plist
controller = (root / 'ObserverApp/ObserverController.swift').read_text(encoding='utf8')
assert 'stream.schedule(in: .main, forMode: .common)' in controller
assert 'input?.close()' in controller and 'session = nil' in controller
assert 'timer?.invalidate()' in controller
assert 'stream.read(&buffer, maxLength: size)' in controller
assert 'self.input === current' in controller
core = (root / 'Core/Sources/ObserverCore/CaptureWriter.swift').read_text(encoding='utf8')
assert '32 * 1024 * 1024' in core and '30_000_000_000' in core and '65_536' in core
assert 'try file.write(contentsOf: record)' in core
assert 'complete: successful && transportClosed && flushed && fileClosed' in core
print(json.dumps({'source_guard': 'pass', 'swift_files': len(paths), 'tx_api_surface_found': False,
                  'source_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
                  'limitation': 'Source guard only. Requires actual Swift/iOS build and device observation.'}))
