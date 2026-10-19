"""Independent reader of the fixture produced by the actual Swift writer in CI."""
import json
import struct
import sys
from pathlib import Path

path = Path(sys.argv[1])
raw = (path / 'capture.n2rx').read_bytes()
assert raw[:8] == b'N2RX0001'
offset, records = 8, []
while offset < len(raw):
    time, size = struct.unpack_from('<QI', raw, offset)
    offset += 12
    assert 0 < size <= 16384 and offset + size <= len(raw)
    records.append((time, raw[offset:offset + size]))
    offset += size
assert records == [(100, bytes.fromhex('0055ff')), (200, bytes.fromhex('80010203'))]
manifest = json.loads((path / 'manifest.json').read_bytes())
assert manifest['context']['data_kind'] == 'synthetic'
assert manifest['rx_bytes'] == 7 and manifest['chunks'] == 2
assert manifest['capture_complete'] is True and manifest['tx_attempts'] == 0
assert manifest['transport_closed'] is True and manifest['file_flushed'] is True
print(json.dumps({'cross_language_fixture': 'pass', 'bytes': 7, 'records': 2, 'device_io': 0}))
