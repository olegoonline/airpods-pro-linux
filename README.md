# AirPods Pro 3 for Linux — noise cancellation, transparency & battery in the tray

**Control Apple AirPods Pro 3 on Linux** (Bazzite, Fedora, KDE Plasma): switch **Active Noise Cancellation (ANC)** and **Transparency mode**, see **left / right / case battery**, and get **automatic pause when you take an AirPod out**. A lightweight tray app and window, written in Python with PySide6 (Qt 6), no root and no system packages to install.

[Русская версия ниже ↓](#русский)

![AirPods Pro 3 Linux app window: noise cancellation on, low battery, disconnected](docs/window.png)

## Features

- **Noise Cancellation and Transparency** — the two main listening modes, one click each. Click the active mode again to turn noise control **off**.
- **Battery** for the left bud, right bud and case: bars on the earbud stems in the window, rings in the tray widget, an arc on the tray icon. Low battery turns red.
- **Ear detection auto-pause**: media pauses when you take an AirPod out and resumes when both are back in (see [behavior](#taking-an-airpod-out)).
- **Tray icon + tray widget** for KDE Plasma: left click opens a compact widget with modes and battery, middle click toggles ANC ↔ Transparency, right click opens a menu.
- **Autostart** at login, straight into the tray.
- **CLI** `airpods-mode` for scripts and keyboard shortcuts.

![AirPods tray widget for KDE Plasma: open app, case and earbud battery rings, noise cancellation and transparency buttons](docs/tray-widget.png)

### Deliberately left out

- **No “fashionable” extra modes.** Adaptive Audio and Conversational Awareness are not exposed — only the two modes people actually switch between. Spatial audio is never enabled: the app never starts AirPods head-tracking and adds no audio processing to PipeWire.
- **The interface is designed for AirPods Pro only.** The window artwork, icons and layout are made for AirPods Pro (tested on AirPods Pro 3). Other AirPods models speak the same protocol and may work, but the graphics will still show AirPods Pro.

## Taking an AirPod out

| You do | What happens |
|---|---|
| Take one AirPod out while both were in | Playing media is **paused** (any MPRIS player: browsers / YouTube, Spotify, VLC, mpv…) |
| Take the second one out, or put just one back | Nothing changes |
| Put both back in | Media **resumes** — only the players this app paused; a pause you made yourself stays |
| One AirPod in your ear | **Noise cancellation stays on.** The app enables “Noise Cancellation with One AirPod”, so AirPods no longer fall back to Transparency by themselves |

## Requirements

- Linux with BlueZ and AirPods paired over Bluetooth.
- Python 3 with **PySide6** and **dbus-python** (both ship with Bazzite / Fedora KDE images).
- KDE Plasma for the tray icon and widget (the window and CLI work anywhere). On Wayland the app runs through XWayland so the widget can open right under the tray icon.

## Install

```bash
git clone https://github.com/olegoonline/airpods-pro-linux.git
cd airpods-pro-linux
./install.sh                 # or ./install.sh --no-autostart
```

Everything goes into `~/.local` — nothing is layered onto the immutable Bazzite / Fedora Atomic image, no `rpm-ostree`, no root. Remove with `./install.sh --uninstall`.

## Usage

- Menu → **AirPods**, or it starts by itself at login (tray icon).
- Tray icon: **left click** — widget, **middle click** — ANC ↔ Transparency, **right click** — menu.
- Command line:

```bash
airpods-mode                 # mode, battery, ear status
airpods-mode anc             # noise cancellation
airpods-mode transparency
airpods-mode off
airpods-mode cycle           # ANC ↔ Transparency
```

## How it works

AirPods expose Apple's private **AAP (Apple Accessory Protocol)** over Bluetooth **L2CAP, PSM 0x1001**. The app sends the handshake, subscribes to notifications (battery, ear detection, listening mode) and writes control commands — for example `04 00 04 00 09 00 0D <mode> 00 00 00` sets the listening mode. Protocol knowledge comes from the excellent reverse-engineering work of [LibrePods](https://github.com/kavishdevar/librepods); the code here is an independent, minimal implementation.

| File | Purpose |
|---|---|
| `airpods_aap.py` | AAP protocol client (stdlib only) |
| `airpods-tray` | Window, tray widget, tray icon (PySide6) |
| `sni.py` | KDE StatusNotifierItem tray icon with click coordinates |
| `media.py` | MPRIS pause / resume for ear detection |
| `airpods-mode` | Command-line tool |

## FAQ

**Can I use AirPods noise cancellation on Linux?** Yes. Linux plays audio to AirPods over standard Bluetooth, but switching ANC / Transparency needs Apple's AAP protocol, which this app implements.

**Does it work on Bazzite / Fedora Atomic / Steam Deck-like immutable systems?** Yes, it installs into your home directory and needs no system changes.

**Does it support AirPods Pro 2, AirPods 4 or AirPods Max?** Protocol-wise probably (LibrePods documents the same commands), but the interface is built for AirPods Pro and only AirPods Pro 3 has been tested.

**Is spatial audio enabled?** No. Spatial audio is computed by the playing device from head-tracking data; this app never requests head tracking and adds no spatial filters.

**Why is the case battery an older value?** AirPods only know the case level while they sit in the case with the lid open — even Apple's own Bluetooth LE adverts report the case as “unknown” once the buds are in your ears. The app remembers the last reported case level (stored in `~/.config/airpods-tray/state.json`) and shows it until a fresh one arrives; to refresh it, put the buds in the case and open the lid.

**How is this different from LibrePods?** LibrePods is a full-featured multi-platform project. This is a small, focused tray app for AirPods Pro on KDE Plasma with two modes, battery and ear-detection pause.

---

## Русский

### AirPods Pro 3 на Linux: шумоподавление, прозрачность и заряд в трее

Утилита для **управления AirPods Pro 3 в Linux** (Bazzite, Fedora, KDE Plasma): переключение **шумоподавления** и **режима прозрачности**, **заряд левого и правого наушника и кейса**, **автопауза музыки, когда вынимаешь наушник**. Значок в трее, всплывающий виджет и окно на Python + PySide6 (Qt 6), без root и без установки системных пакетов.

### Возможности

- **Шумоподавление и прозрачность** — два основных режима в один клик. Повторное нажатие активного режима **выключает** управление шумом.
- **Заряд** левого и правого наушника и кейса: полоски на ножках в окне, кольца в виджете трея, дуга на значке. При низком заряде — красный цвет.
- **Автопауза** при вынимании наушника и продолжение, когда оба снова в ушах.
- **Значок и виджет в трее KDE Plasma**: левый клик — виджет, средний — переключение режимов, правый — меню.
- **Автозапуск** при входе в систему, сразу в трей.
- **Командная строка** `airpods-mode` для скриптов и горячих клавиш.

### Что сознательно убрано

- **Ненужные «модные» режимы выключены.** Адаптивный звук и адаптация к разговору в интерфейс не выведены — только два режима, которыми реально пользуются. Пространственный звук никогда не включается: программа не запускает отслеживание головы и не добавляет обработку звука в PipeWire.
- **Графика сделана только для AirPods Pro.** Окно, иконки и раскладка нарисованы под AirPods Pro (проверено на AirPods Pro 3). Другие модели AirPods говорят на том же протоколе и могут работать, но на картинке всё равно будут AirPods Pro.

### Что происходит, когда вынимаешь наушник

| Действие | Результат |
|---|---|
| Вынули один наушник, когда оба были в ушах | Музыка и видео **на паузе** (любой плеер с MPRIS: браузеры и YouTube, Spotify, VLC, mpv…) |
| Вынули второй или вернули только один | Ничего не меняется |
| Вернули оба в уши | Воспроизведение **продолжается** — только у плееров, которые остановила программа; ваша собственная пауза остаётся |
| В ухе один наушник | **Шумоподавление остаётся включённым.** Программа включает «Шумоподавление с одним наушником», и AirPods больше не переключаются сами в прозрачность |

### Заряд кейса

AirPods знают заряд кейса, только пока лежат в нём с открытой крышкой; когда наушники в ушах, даже сами AirPods в Bluetooth LE-рекламе сообщают кейс как «неизвестно». Поэтому программа запоминает последнее значение (`~/.config/airpods-tray/state.json`) и показывает его, пока не придёт новое. Чтобы обновить — положите наушники в кейс и откройте крышку.

### Установка

```bash
git clone https://github.com/olegoonline/airpods-pro-linux.git
cd airpods-pro-linux
./install.sh                 # или ./install.sh --no-autostart
```

Всё ставится в `~/.local`: образ Bazzite / Fedora Atomic не трогается, `rpm-ostree` и root не нужны. Удаление — `./install.sh --uninstall`.

### Как это работает

AirPods принимают закрытый протокол Apple **AAP** поверх Bluetooth **L2CAP (PSM 0x1001)**. Программа выполняет рукопожатие, подписывается на уведомления (заряд, датчики уха, режим) и отправляет управляющие команды. Описание протокола взято из исследований проекта [LibrePods](https://github.com/kavishdevar/librepods); код здесь — независимая минимальная реализация.

## License

Code: MIT (see [LICENSE](LICENSE)). Inter font: SIL Open Font License (`assets/Inter-LICENSE.txt`). AirPods is a trademark of Apple Inc.; this project is not affiliated with Apple.
