#!/usr/bin/env bash
# Installs AirPods tray app + CLI into ~/.local (Bazzite's /usr is read-only; no rpm-ostree needed).
# Usage: ./install.sh [--no-autostart] | ./install.sh --uninstall
set -euo pipefail
cd "$(dirname "$0")"

share="$HOME/.local/share/airpods-mode"
bin="$HOME/.local/bin"
apps="$HOME/.local/share/applications"
autostart="$HOME/.config/autostart/airpods-tray.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
    pkill -f "$share/airpods-tray" || true
    find "$HOME/.local/share/icons/hicolor" -name 'airpods-tray.*' -delete 2>/dev/null || true
    rm -rf "$share" "$bin/airpods-mode" "$bin/airpods-tray" \
           "$apps/airpods-tray.desktop" "$apps/airpods-mode.desktop" "$autostart"
    update-desktop-database "$apps" 2>/dev/null || true
    echo "Removed."
    exit 0
fi

install -Dm644 airpods_aap.py "$share/airpods_aap.py"
install -Dm644 sni.py "$share/sni.py"
install -Dm644 media.py "$share/media.py"
install -Dm755 airpods-mode "$share/airpods-mode"
install -Dm755 airpods-tray "$share/airpods-tray"
rm -rf "$share/assets"
mkdir -p "$share/assets/ui"
install -m644 assets/*.* "$share/assets/"
install -m644 assets/ui/* "$share/assets/ui/"
mkdir -p "$bin"
ln -sf "$share/airpods-mode" "$bin/airpods-mode"
ln -sf "$share/airpods-tray" "$bin/airpods-tray"

"$share/airpods-tray" --write-icons "$HOME/.local/share/icons/hicolor"
install -Dm644 assets/app-icon.svg "$HOME/.local/share/icons/hicolor/scalable/apps/airpods-tray.svg"
gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

rm -f "$apps/airpods-mode.desktop"  # entry from the first CLI-only version
# Absolute paths: ~/.local/bin isn't always on PATH for the Plasma session.
sed "s|^Exec=airpods-|Exec=$bin/airpods-|" airpods-tray.desktop > "$apps/airpods-tray.desktop"
update-desktop-database "$apps" 2>/dev/null || true

if [[ "${1:-}" != "--no-autostart" ]]; then
    mkdir -p "$(dirname "$autostart")"
    sed "s|^Exec=$bin/airpods-tray$|Exec=$bin/airpods-tray --hidden|" "$apps/airpods-tray.desktop" > "$autostart"
fi

echo "Installed: airpods-tray (\"AirPods\" in the app menu), airpods-mode (CLI)"
