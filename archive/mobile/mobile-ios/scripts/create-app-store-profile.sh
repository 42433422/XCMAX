#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  bash scripts/create-app-store-profile.sh \
    --scheme XCAGIMobile|XCAGIMobilePersonal \
    --profile-name <name> \
    [--cert-index 2] \
    [--browser "Microsoft Edge"] \
    [--download-dir "$HOME/Downloads"]

Notes:
  - Requires a logged-in Apple Developer session in the target browser.
  - Requires macOS Accessibility permission for the terminal that runs this script.
  - The script creates an App Store Connect provisioning profile and downloads it.
EOF
}

scheme=""
profile_name=""
cert_index=2
browser="Microsoft Edge"
download_dir="${HOME}/Downloads"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scheme) scheme="${2:-}"; shift 2 ;;
    --profile-name) profile_name="${2:-}"; shift 2 ;;
    --cert-index) cert_index="${2:-}"; shift 2 ;;
    --browser) browser="${2:-}"; shift 2 ;;
    --download-dir) download_dir="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "${scheme}" || -z "${profile_name}" ]]; then
  usage >&2
  exit 2
fi

case "${scheme}" in
  XCAGIMobile) app_search_term="com.xiuci.xcagi.mobile.enterprise" ;;
  XCAGIMobilePersonal) app_search_term="com.xiuci.xcagi.mobile.personal" ;;
  *)
    echo "Unknown scheme: ${scheme}" >&2
    exit 2
    ;;
esac

if ! [[ "${cert_index}" =~ ^[1-9][0-9]*$ ]]; then
  echo "--cert-index must be a positive integer" >&2
  exit 2
fi

before_latest="$(find "${download_dir}" -maxdepth 1 -type f -name '*.mobileprovision' -print0 | xargs -0 ls -t 2>/dev/null | head -1 || true)"
before_epoch="$(date +%s)"

osascript -e "tell application \"${browser}\" to activate"
osascript -e "tell application \"${browser}\" to set URL of active tab of window 1 to \"https://developer.apple.com/account/resources/profiles/add\""
sleep 2

swift - <<'SWIFT'
import AppKit
import ApplicationServices

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func title(_ e: AXUIElement) -> String { (attr(e, kAXTitleAttribute) as? String) ?? "" }

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func find(_ e: AXUIElement, matcher: (AXUIElement) -> Bool) -> AXUIElement? {
    if matcher(e) { return e }
    for child in children(e) {
        if let hit = find(child, matcher: matcher) {
            return hit
        }
    }
    return nil
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

guard
    let radio = find(ax, matcher: { role($0) == "AXRadioButton" && title($0).hasPrefix("App Store Connect Create a distribution provisioning profile") }),
    let button = find(ax, matcher: { role($0) == "AXButton" && title($0) == "Continue" })
else {
    fputs("Unable to find profile type controls.\n", stderr)
    exit(1)
}

guard AXUIElementPerformAction(radio, "AXPress" as CFString) == .success else {
    fputs("Failed to select App Store Connect profile type.\n", stderr)
    exit(1)
}

Thread.sleep(forTimeInterval: 0.3)
guard AXUIElementPerformAction(button, "AXPress" as CFString) == .success else {
    fputs("Failed to continue from profile type step.\n", stderr)
    exit(1)
}
SWIFT

sleep 2

swift - <<'SWIFT'
import AppKit
import ApplicationServices
import CoreGraphics

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func value(_ e: AXUIElement) -> String { (attr(e, kAXValueAttribute) as? String) ?? "" }

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func frame(_ e: AXUIElement) -> CGRect? {
    var v: CFTypeRef?
    guard AXUIElementCopyAttributeValue(e, "AXFrame" as CFString, &v) == .success,
          let raw = v,
          CFGetTypeID(raw) == AXValueGetTypeID()
    else {
        return nil
    }
    let ax = raw as! AXValue
    guard AXValueGetType(ax) == .cgRect else { return nil }
    var rect = CGRect.zero
    AXValueGetValue(ax, .cgRect, &rect)
    return rect
}

func findSelectPlaceholder(_ e: AXUIElement) -> AXUIElement? {
    if role(e) == "AXStaticText" && value(e) == "Select..." {
        return e
    }
    for child in children(e) {
        if let hit = findSelectPlaceholder(child) {
            return hit
        }
    }
    return nil
}

func click(_ p: CGPoint) {
    let src = CGEventSource(stateID: .combinedSessionState)
    let down = CGEvent(mouseEventSource: src, mouseType: .leftMouseDown, mouseCursorPosition: p, mouseButton: .left)
    let up = CGEvent(mouseEventSource: src, mouseType: .leftMouseUp, mouseCursorPosition: p, mouseButton: .left)
    down?.post(tap: .cghidEventTap)
    up?.post(tap: .cghidEventTap)
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

guard let placeholder = findSelectPlaceholder(ax), let rect = frame(placeholder) else {
    fputs("Unable to find App ID selector.\n", stderr)
    exit(1)
}

click(CGPoint(x: rect.midX, y: rect.midY))
SWIFT

sleep 1

osascript <<APPLESCRIPT
tell application "System Events"
  keystroke "${app_search_term}"
  delay 0.6
  key code 36
end tell
APPLESCRIPT

sleep 1

swift - <<'SWIFT'
import AppKit
import ApplicationServices

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func title(_ e: AXUIElement) -> String { (attr(e, kAXTitleAttribute) as? String) ?? "" }

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func find(_ e: AXUIElement) -> AXUIElement? {
    if role(e) == "AXButton" && title(e) == "Continue" {
        return e
    }
    for child in children(e) {
        if let hit = find(child) {
            return hit
        }
    }
    return nil
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

guard let button = find(ax) else {
    fputs("Unable to find App ID continue button.\n", stderr)
    exit(1)
}

guard AXUIElementPerformAction(button, "AXPress" as CFString) == .success else {
    fputs("Failed to continue from App ID step.\n", stderr)
    exit(1)
}
SWIFT

sleep 2

CERT_INDEX="${cert_index}" swift - <<'SWIFT'
import AppKit
import ApplicationServices
import Foundation

let certIndex = Int(ProcessInfo.processInfo.environment["CERT_INDEX"] ?? "2") ?? 2

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func title(_ e: AXUIElement) -> String { (attr(e, kAXTitleAttribute) as? String) ?? "" }

func frameY(_ e: AXUIElement) -> CGFloat {
    var v: CFTypeRef?
    guard AXUIElementCopyAttributeValue(e, "AXFrame" as CFString, &v) == .success,
          let raw = v,
          CFGetTypeID(raw) == AXValueGetTypeID()
    else {
        return -1
    }
    let ax = raw as! AXValue
    guard AXValueGetType(ax) == .cgRect else { return -1 }
    var rect = CGRect.zero
    AXValueGetValue(ax, .cgRect, &rect)
    return rect.origin.y
}

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func gatherRadios(_ e: AXUIElement, into radios: inout [AXUIElement]) {
    if role(e) == "AXRadioButton" && title(e) == "jialong Li (iOS Distribution)Jun 25, 2027" {
        radios.append(e)
    }
    for child in children(e) {
        gatherRadios(child, into: &radios)
    }
}

func findContinue(_ e: AXUIElement) -> AXUIElement? {
    if role(e) == "AXButton" && title(e) == "Continue" {
        return e
    }
    for child in children(e) {
        if let hit = findContinue(child) {
            return hit
        }
    }
    return nil
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

var radios: [AXUIElement] = []
gatherRadios(ax, into: &radios)
radios.sort { frameY($0) < frameY($1) }

let target = certIndex - 1
guard target >= 0 && target < radios.count else {
    fputs("Requested certificate index is unavailable.\n", stderr)
    exit(1)
}

guard AXUIElementPerformAction(radios[target], "AXPress" as CFString) == .success else {
    fputs("Failed to select certificate radio.\n", stderr)
    exit(1)
}

Thread.sleep(forTimeInterval: 0.3)
guard let button = findContinue(ax) else {
    fputs("Unable to find certificate continue button.\n", stderr)
    exit(1)
}

guard AXUIElementPerformAction(button, "AXPress" as CFString) == .success else {
    fputs("Failed to continue from certificate step.\n", stderr)
    exit(1)
}
SWIFT

sleep 2

PROFILE_NAME="${profile_name}" swift - <<'SWIFT'
import AppKit
import ApplicationServices
import Foundation

let profileName = ProcessInfo.processInfo.environment["PROFILE_NAME"] ?? ""

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func title(_ e: AXUIElement) -> String { (attr(e, kAXTitleAttribute) as? String) ?? "" }

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func findField(_ e: AXUIElement) -> AXUIElement? {
    if role(e) == "AXTextField" && title(e) == "Provisioning Profile Name" {
        return e
    }
    for child in children(e) {
        if let hit = findField(child) {
            return hit
        }
    }
    return nil
}

func findGenerate(_ e: AXUIElement) -> AXUIElement? {
    if role(e) == "AXButton" && title(e) == "Generate" {
        return e
    }
    for child in children(e) {
        if let hit = findGenerate(child) {
            return hit
        }
    }
    return nil
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

guard let field = findField(ax) else {
    fputs("Unable to find profile name field.\n", stderr)
    exit(1)
}

guard AXUIElementSetAttributeValue(field, kAXValueAttribute as CFString, profileName as CFTypeRef) == .success else {
    fputs("Failed to set profile name.\n", stderr)
    exit(1)
}

Thread.sleep(forTimeInterval: 0.3)
guard let button = findGenerate(ax) else {
    fputs("Unable to find Generate button.\n", stderr)
    exit(1)
}

guard AXUIElementPerformAction(button, "AXPress" as CFString) == .success else {
    fputs("Failed to generate profile.\n", stderr)
    exit(1)
}
SWIFT

sleep 2

swift - <<'SWIFT'
import AppKit
import ApplicationServices

func attr(_ e: AXUIElement, _ n: String) -> AnyObject? {
    var v: CFTypeRef?
    return AXUIElementCopyAttributeValue(e, n as CFString, &v) == .success ? v as AnyObject? : nil
}

func role(_ e: AXUIElement) -> String { (attr(e, kAXRoleAttribute) as? String) ?? "" }
func value(_ e: AXUIElement) -> String { (attr(e, kAXValueAttribute) as? String) ?? "" }

func children(_ e: AXUIElement) -> [AXUIElement] {
    var out: [AXUIElement] = []
    for key in [kAXChildrenAttribute, kAXContentsAttribute, kAXRowsAttribute, kAXTabsAttribute] {
        if let arr = attr(e, key) as? [AXUIElement] {
            out.append(contentsOf: arr)
        }
    }
    return out
}

func texts(_ e: AXUIElement) -> [String] {
    var out: [String] = []
    if role(e) == "AXStaticText" {
        let v = value(e)
        if !v.isEmpty { out.append(v) }
    }
    for child in children(e) {
        out.append(contentsOf: texts(child))
    }
    return out
}

func pressDownload(_ e: AXUIElement) -> Bool {
    if role(e) == "AXLink" && texts(e).joined(separator: " ") == "Download" {
        return AXUIElementPerformAction(e, "AXPress" as CFString) == .success
    }
    for child in children(e) {
        if pressDownload(child) { return true }
    }
    return false
}

let app = NSRunningApplication.runningApplications(withBundleIdentifier: "com.microsoft.edgemac").first!
let ax = AXUIElementCreateApplication(app.processIdentifier)

guard pressDownload(ax) else {
    fputs("Unable to press Download link.\n", stderr)
    exit(1)
}
SWIFT

sleep 3

latest_after="$(find "${download_dir}" -maxdepth 1 -type f -name '*.mobileprovision' -print0 | xargs -0 ls -t 2>/dev/null | head -1 || true)"
if [[ -z "${latest_after}" ]]; then
  echo "No .mobileprovision file found after download." >&2
  exit 1
fi

latest_epoch="$(stat -f '%m' "${latest_after}")"
if [[ "${latest_after}" == "${before_latest}" && "${latest_epoch}" -lt "${before_epoch}" ]]; then
  echo "No newly downloaded provisioning profile detected." >&2
  exit 1
fi

printf '%s\n' "${latest_after}"
