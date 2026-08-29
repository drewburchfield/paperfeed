#!/bin/bash
# Install the paperfeed command from this repo.
#
# Usage:
#   ./install.sh              # Install
#   ./install.sh uninstall    # Remove

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
LIB_DIR="${LIB_DIR:-$HOME/.local/lib/paperfeed}"

info() { printf '==> %s\n' "$1"; }
fail() { printf 'Error: %s\n' "$1" >&2; exit 1; }

remove_old_scan_symlink() {
    local scan_link="$BIN_DIR/scan"
    [ -L "$scan_link" ] || return 0
    local target
    target="$(readlink "$scan_link")"
    case "$target" in
        *paperfeed*|*lan-scan*)
            rm -f "$scan_link"
            ;;
    esac
}

install_paperfeed() {
    command -v python3 >/dev/null || fail "python3 is required."
    mkdir -p "$BIN_DIR"
    rm -rf "$LIB_DIR"
    mkdir -p "$LIB_DIR"
    cp -R "$ROOT/bin" "$ROOT/paperfeed" "$LIB_DIR/"
    chmod +x "$LIB_DIR/bin/paperfeed"
    ln -sfn "$LIB_DIR/bin/paperfeed" "$BIN_DIR/paperfeed"
    remove_old_scan_symlink
    info "Installed $BIN_DIR/paperfeed"
    info "Set the scanner with: paperfeed --host PRINTER.local --status"
    info "Or: echo PRINTER.local > ~/.config/paperfeed/host"
    info "UI: paperfeed ui"
}

uninstall_paperfeed() {
    rm -f "$BIN_DIR/paperfeed"
    remove_old_scan_symlink
    rm -rf "$LIB_DIR"
    info "Uninstalled paperfeed"
}

case "${1:-install}" in
    install)
        install_paperfeed
        ;;
    uninstall)
        uninstall_paperfeed
        ;;
    *)
        echo "Usage: $0 [install|uninstall]"
        exit 1
        ;;
esac
