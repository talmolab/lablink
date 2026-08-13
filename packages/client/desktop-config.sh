#!/bin/bash
# Generates the XFCE configuration the participant desktop starts with.
#
# Everything here is written into the xfconf XML store directly rather than
# applied with `xfconf-query`. xfconf-query needs the session dbus already
# up, so calling it from the startup path would race xfce4-session. xfconf
# reads this store once, at session start -- anything written afterwards is
# ignored, and there is no second session start inside one participant
# session.
#
# This lives outside start.sh so it can be run on its own: the image-build
# workflow executes it in the built image and reads every value back with
# xfconf-query. start.sh cannot be used for that -- it registers with an
# allocator and launches long-running services.
set -euo pipefail

CONFIG_HOME="${HOME:-/home/client}"
XFCONF="${CONFIG_HOME}/.config/xfce4/xfconf/xfce-perchannel-xml"
mkdir -p "${XFCONF}"

# XFCE's compositor recomposites the whole screen on every window move, so
# Xvnc sees one full-screen damage rect instead of a few small ones and
# re-encodes the entire framebuffer for each frame of a drag -- the single
# largest source of choppy motion in the participant desktop.
cat > "${XFCONF}/xfwm4.xml" <<'XFWM'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="theme" type="string" value="Yaru"/>
    <property name="title_font" type="string" value="Ubuntu Bold 10"/>
    <property name="button_layout" type="string" value="O|HMC"/>
  </property>
</channel>
XFWM

# GTK theme, icons, and font rendering.
#
# RGBA=none is a VNC decision, not a cosmetic one. Subpixel antialiasing
# puts coloured fringes on every glyph, and at -DynamicQualityMin 4 those
# fringes are the first thing the encoder discards -- text ends up ringed
# with colour noise. Greyscale antialiasing compresses better and stays
# legible at the quality floor.
cat > "${XFCONF}/xsettings.xml" <<'XSETTINGS'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Net" type="empty">
    <property name="ThemeName" type="string" value="Yaru"/>
    <property name="IconThemeName" type="string" value="Yaru"/>
    <property name="EnableEventSounds" type="bool" value="false"/>
    <property name="EnableInputFeedbackSounds" type="bool" value="false"/>
  </property>
  <property name="Gtk" type="empty">
    <property name="FontName" type="string" value="Ubuntu 10"/>
    <property name="MonospaceFontName" type="string" value="Ubuntu Mono 11"/>
    <property name="CursorThemeName" type="string" value="Yaru"/>
    <property name="CursorThemeSize" type="int" value="24"/>
  </property>
  <property name="Xft" type="empty">
    <property name="Antialias" type="int" value="1"/>
    <property name="Hinting" type="int" value="1"/>
    <property name="HintStyle" type="string" value="hintslight"/>
    <property name="RGBA" type="string" value="none"/>
  </property>
</channel>
XSETTINGS

# Solid backdrop. image-style=0 means "no image"; color-style=0 means a
# single solid colour taken from rgba1. The colour is Ubuntu aubergine
# (#2C001E), so the desktop still reads as Ubuntu without a 57 MB wallpaper
# package -- and a flat fill is far cheaper to encode than a photograph
# during a window drag.
#
# xfdesktop keys the backdrop by RandR output name. Xvnc exposes VNC-0, but
# the name has moved across KasmVNC versions and a non-RandR session uses
# the generic monitor0 path. Writing both costs nothing and xfdesktop reads
# whichever one matches.
cat > "${XFCONF}/xfce4-desktop.xml" <<'XFDESKTOP'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitor0" type="empty">
        <property name="workspace0" type="empty">
          <property name="image-style" type="int" value="0"/>
          <property name="color-style" type="int" value="0"/>
          <property name="rgba1" type="array">
            <value type="double" value="0.172549"/>
            <value type="double" value="0.000000"/>
            <value type="double" value="0.117647"/>
            <value type="double" value="1.000000"/>
          </property>
        </property>
      </property>
      <property name="monitorVNC-0" type="empty">
        <property name="workspace0" type="empty">
          <property name="image-style" type="int" value="0"/>
          <property name="color-style" type="int" value="0"/>
          <property name="rgba1" type="array">
            <value type="double" value="0.172549"/>
            <value type="double" value="0.000000"/>
            <value type="double" value="0.117647"/>
            <value type="double" value="1.000000"/>
          </property>
        </property>
      </property>
    </property>
  </property>
</channel>
XFDESKTOP

# Panel layout. Writing the panel channel ourselves skips xfce4-panel's
# first-run copy of /etc/xdg/xfce4/panel/default.xml, which is where the
# nested Applications menu comes from -- the single most dated thing about
# the stock desktop.
#
# Five plugins, no clipboard: xfce4-clipman-plugin left with xfce4-goodies,
# and naming it here would leave an empty slot in the panel at session start.
mkdir -p "${CONFIG_HOME}/.config/xfce4/panel"
cat > "${XFCONF}/xfce4-panel.xml" <<'XFPANEL'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=6;x=0;y=0"/>
      <property name="length" type="uint" value="100"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="36"/>
      <property name="plugin-ids" type="array">
        <value type="int" value="1"/>
        <value type="int" value="2"/>
        <value type="int" value="3"/>
        <value type="int" value="4"/>
        <value type="int" value="5"/>
      </property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-1" type="string" value="whiskermenu"/>
    <property name="plugin-2" type="string" value="tasklist"/>
    <property name="plugin-3" type="string" value="separator">
      <property name="expand" type="bool" value="true"/>
      <property name="style" type="uint" value="0"/>
    </property>
    <property name="plugin-4" type="string" value="systray"/>
    <property name="plugin-5" type="string" value="clock">
      <property name="mode" type="uint" value="2"/>
      <property name="digital-time-format" type="string" value="%a %d %b  %H:%M"/>
    </property>
  </property>
</channel>
XFPANEL

# Whisker reads its own rc file, not xfconf. Without it the panel button
# renders as an unlabelled blank. `start-here` is used for the icon because
# every icon theme provides it -- a Yaru-only name would render blank if the
# theme ever changes.
cat > "${CONFIG_HOME}/.config/xfce4/panel/whiskermenu-1.rc" <<'WHISKERRC'
button-title=Applications
button-icon=start-here
show-button-title=false
show-button-icon=true
launcher-show-name=true
launcher-show-description=false
category-show-name=true
position-search-alternate=true
position-commands-alternate=true
recent-items-max=10
favorites=xfce4-terminal.desktop,google-chrome.desktop,Thunar.desktop,org.xfce.mousepad.desktop
WHISKERRC

# Window-management keybindings, set explicitly rather than inherited.
# 4.18's defaults differ between the xfwm4 package and the Xubuntu session,
# and this image runs neither -- it runs xfce4-session bare.
#
# Super-based bindings only fire when the participant's OS lets the key
# through to the browser, which macOS and Windows often do not. Edge-drag
# tiling needs no keyboard at all and is the reliable path; these are the
# accelerator, not the only route. Whisker is on Ctrl+Alt+Space for the
# same reason.
cat > "${XFCONF}/xfce4-keyboard-shortcuts.xml" <<'XFKEYS'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-keyboard-shortcuts" version="1.0">
  <property name="xfwm4" type="empty">
    <property name="custom" type="empty">
      <property name="&lt;Super&gt;Left" type="string" value="tile_left_key"/>
      <property name="&lt;Super&gt;Right" type="string" value="tile_right_key"/>
      <property name="&lt;Super&gt;Up" type="string" value="maximize_window_key"/>
      <property name="&lt;Super&gt;Down" type="string" value="hide_window_key"/>
      <property name="&lt;Alt&gt;Tab" type="string" value="cycle_windows_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Left" type="string" value="left_workspace_key"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Right" type="string" value="right_workspace_key"/>
    </property>
  </property>
  <property name="commands" type="empty">
    <property name="custom" type="empty">
      <property name="&lt;Primary&gt;&lt;Alt&gt;space" type="string" value="xfce4-popup-whiskermenu"/>
    </property>
  </property>
</channel>
XFKEYS

# xfce4-terminal reads an ini file, not xfconf -- it is the one component
# here that does not use the settings daemon.
#
# The palette is Ubuntu's own (Tango on aubergine), so the terminal matches
# the #2C001E desktop backdrop rather than clashing with it. Transparency is
# set off explicitly: compositing is disabled for latency, so a translucent
# background renders as a flat opaque block, which looks like a bug rather
# than a choice.
#
# ScrollingOnOutput is off because a chatty training job would otherwise
# yank the view to the bottom on every line, and each jump is a full-screen
# damage rect for the encoder.
mkdir -p "${CONFIG_HOME}/.config/xfce4/terminal"
cat > "${CONFIG_HOME}/.config/xfce4/terminal/terminalrc" <<'TERMINALRC'
[Configuration]
FontName=Ubuntu Mono 12
ColorForeground=#ffffff
ColorBackground=#300a24
ColorCursor=#ffffff
ColorCursorUseDefault=FALSE
ColorPalette=#2e3436;#cc0000;#4e9a06;#c4a000;#3465a4;#75507b;#06989a;#d3d7cf;#555753;#ef2929;#8ae234;#fce94f;#729fcf;#ad7fa8;#34e2e2;#eeeeec
BackgroundMode=TERMINAL_BACKGROUND_SOLID
MiscMenubarDefault=FALSE
MiscToolbarDefault=FALSE
MiscAlwaysShowTabs=FALSE
MiscBell=FALSE
MiscBellUrgent=FALSE
MiscCursorShape=TERMINAL_CURSOR_SHAPE_BLOCK
MiscDefaultGeometry=100x30
ScrollingLines=10000
ScrollingOnOutput=FALSE
ScrollingBar=TERMINAL_SCROLLBAR_RIGHT
TERMINALRC

# Images only. Chrome's .deb claims png/jpeg/gif and outranks ristretto, so a
# double-clicked frame opens a whole browser window instead of a viewer --
# painful when flipping through labelled frames. Every other type sorts itself
# out: GIO resolves an unclaimed type through its parent, so once the Dockerfile
# drops micro's MimeType line, mousepad wins all of text/* via text/plain and
# ristretto already wins bmp/tiff/svg unaided. Nothing to pin for those.
#
# webp is deliberately absent -- ristretto's .desktop does not claim it, so it
# stays with Chrome rather than being pointed at an app that never declared it.
cat > "${CONFIG_HOME}/.config/mimeapps.list" <<'MIMEAPPS'
[Default Applications]
image/png=org.xfce.ristretto.desktop
image/jpeg=org.xfce.ristretto.desktop
image/gif=org.xfce.ristretto.desktop
MIMEAPPS

echo "desktop-config: wrote configuration under ${XFCONF}"
