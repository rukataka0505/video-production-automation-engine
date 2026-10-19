# Neo2 RX Observer

This distinct iPhone app records incoming accessory bytes. Native Swift tests,
Swift/Python file interoperability and the unsigned iPhone build passed in
[CI](https://github.com/rukataka0505/video-production-automation-engine/actions/runs/39210050289)
for source commit `353a3a5ed59a24d059686f869235b8933025081a`.
**Owner signing, installation and hardware behavior are not verified yet.**
It does not unlock Manual mode and is not a firmware/control implementation.

The app has no command profiles, transmit API, bootstrap, serial poll,
keepalive, network client, automatic connection or settings controls. It opens
only the selected accessory's `com.dji.logiclink` input stream after Start.
This establishes absence of application-level writes in the reviewed source;
it does not measure MFi/system traffic or prove that an uninitialised RC will
deliver data. Zero received bytes is an inconclusive observation.

The protocol string is grounded in the previously saved iPhone Fly session and
the transport research in this workspace. No FreeFCC implementation code or
configuration profiles are included. This app is a separate observation surface.

## Build status and CI

This folder is a self-contained repository. A source ZIP can be made
without any aircraft logs, individual IDs, account credentials or the parent
workspace. `.github/workflows/build.yml` runs writer tests, the source guard,
an actual Swift-writer/Python-reader fixture check and an unsigned iPhone build.
The workflow has read-only repository permissions and does not sign or deploy.
The three native writer tests, source guard, actual cross-language fixture and
unsigned arm64 iPhone build passed on 2026-10-19. The CI artifact includes the
IPA, source commit and its SHA256. The original source-only preparation archive
predates that successful build; later documentation updates do not alter the
compiled Swift code. Repository contents were replaced with the owner's consent;
the retired project remains in Git history.

```sh
swift test --package-path Core
python3 ci/verify_source.py
swift run --package-path Core CaptureFixture /tmp/observer-fixture
python3 ci/verify_fixture.py /tmp/observer-fixture
brew install xcodegen
xcodegen generate
xcodebuild build -project Neo2Observer.xcodeproj -scheme Neo2Observer \
  -sdk iphoneos -configuration Release -derivedDataPath build \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" DEVELOPMENT_TEAM=""
```

Xcode is needed for the iPhone build; a hosted macOS CI runner can provide it.
The owner does not need to own a Mac. Windows can be the source/retrieval host
and a signing host using the owner's chosen signing tool, but signing and its
host dependencies are a later, separate step. Do not put Apple ID credentials
in the source or CI. An unsigned IPA is not installable as-is.

## Before an actual capture

These are preparation requirements, **not a hardware test request**:

1. Pass the actual iOS compile and Swift fixture checks, retain source commit
   and artifact hash, then independently verify the source/artifact connection.
2. Have the owner sign/install the reviewed build. Preserve the existing Apple
   Devices environment unless a specific approved dependency change is needed.
3. Prepare one test sheet with current power/cabling, normal radio link,
   purpose, expected success/refutation/inconclusive outcomes and stop/return.
   Do not connect aircraft USB during a normal-radio observation.
4. Establish how closing Fly and opening this same accessory protocol affects
   session ownership. Do not assume coexistence or normal RC authority.
5. The first stage sends no application commands. No data must not trigger an
   automatic retry, handshake, mode/profile change, getter or settings write.

Stop closes the input stream, unschedules it, releases the session, invalidates
the timer and flushes/closes the local file on the same main run loop. No worker
thread or transmit queue exists. Backgrounding, disconnect and read/write
errors also terminate the observation. IOS process termination/storage failure
may leave the initial incomplete manifest: the reader must reject that run.

## Archive format

Each run creates `Documents/Captures/<random UUID>/capture.n2rx` and
`manifest.json`. Apple Devices File Sharing / the Files app can retrieve the
whole folder; two Share buttons also expose the files separately. File sharing
configuration is prepared but has not been observed on the owner's iPhone.

- Binary magic: ASCII `N2RX0001` (8 bytes).
- Each record: little-endian UInt64 elapsed nanoseconds, UInt32 byte count,
  then that exact number of raw input bytes. No prefix/sample truncation.
- Time is the host monotonic time immediately before the read, not FC
  generation time. Frames can span records. Duplicate payloads are retained.
- Maximum RX payload 32 MiB, each read 16 KiB, at most 65,536 records; read
  starts are limited to 30 seconds. Bounded record overhead is additional.
- Metadata retains model/firmware and a hash of accessory identity; raw serial
  is not exported. It does not independently confirm a formal RC-N3 identity.
- A success manifest requires file flush, file close and transport close.
  Its counters and zero-TX declaration still require independent verification;
  they are not proof of radio control, Manual entry, restoration or safety.

The parent workspace's `tools/ios_rx_capture.py` validates the archive and
extracts CRC-valid DUML candidates. It retains byte69 without pretending a new
mobile route proves the target layout. Existing 130/571 runtime tools and
strict USB/RC OSD decoder allowlists remain unchanged.

Current objective remains stock Manual use on Neo 2 + RC-N3, including input,
return and stock protection. This observer is only preparation to obtain
missing evidence for that objective. No motor, flight or firmware operation is
authorised or implemented by this source package.
