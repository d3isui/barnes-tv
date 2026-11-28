# Barnes Television Broadcasting Service: User Guide

This guide covers every feature, in the order you'll probably meet them. New here? Read [Getting started](#getting-started),
then [Building a channel](#building-a-channel). For a quick overview of what the app does, see the [README](README.md).

**Contents**

- [Getting started](#getting-started)
  - [What you need](#what-you-need)
  - [Install and start](#install-and-start)
  - [Start automatically with Windows](#start-automatically-with-windows)
  - [Connect to Jellyfin](#connect-to-jellyfin)
  - [Find your way around the admin page](#find-your-way-around-the-admin-page)
- [Building a channel](#building-a-channel)
  - [The channel list](#the-channel-list)
  - [The channel editor](#the-channel-editor)
  - [Appearance tab](#appearance-tab)
  - [Scheduling tab](#scheduling-tab)
  - [Balancing shows](#balancing-shows)
  - [Time slots](#time-slots)
  - [Marathons](#marathons)
  - [The live schedule](#the-live-schedule)
  - [Commercials tab](#commercials-tab)
  - [Bumpers tab](#bumpers-tab)
  - [Channel recipes](#channel-recipes)
- [YouTube](#youtube)
- [The bumper library](#the-bumper-library)
- [The guide channel](#the-guide-channel)
- [The weather channel](#the-weather-channel)
- [Subtitles](#subtitles)
- [Watching](#watching)
  - [In Jellyfin and other apps](#in-jellyfin-and-other-apps)
  - [In a browser](#in-a-browser)
  - [Screen off and sleep channels](#screen-off-and-sleep-channels)
  - [Phone remote](#phone-remote)
  - [Casting to a Chromecast](#casting-to-a-chromecast)
  - [TV app for Google TV and Android TV](#tv-app-for-google-tv-and-android-tv)
- [Kids channels and the channel lock](#kids-channels-and-the-channel-lock)
- [Making it yours](#making-it-yours)
  - [Themes](#themes)
  - [Theme builder](#theme-builder)
  - [Fonts](#fonts)
  - [Branding](#branding)
- [Settings reference](#settings-reference)
- [Performance](#performance)
- [How it works](#how-it-works)
- [Troubleshooting](#troubleshooting)
- [Known limitations](#known-limitations)

---

## Getting started

### What you need

| | |
|---|---|
| **Python 3.10+** | Windows: `winget install Python.Python.3.12`, or get it from python.org (tick "Add to PATH"). Linux: usually already installed. Install `python3-venv` if needed. |
| **ffmpeg** | Found automatically. It looks for **Jellyfin's own ffmpeg** first (`C:\Program Files\Jellyfin\Server\ffmpeg.exe` or `/usr/lib/jellyfin-ffmpeg/ffmpeg`), then for any ffmpeg on your PATH. |
| **Pillow, PyChromecast, yt-dlp, Deno** | Installed automatically by the start script (yt-dlp and Deno are only used for [YouTube](#youtube)). |
| **A Jellyfin API key** | Create one in Jellyfin: **Dashboard → API Keys → +**. |

It's easiest to run it on the same machine as Jellyfin, but it doesn't have to be. By default it streams media
from Jellyfin over HTTP, so it works from any machine that can reach Jellyfin.

### Install and start

**Windows**

1. Copy the project folder to the Jellyfin box, for example `C:\JellyfinBroadcast`.
2. Double-click **`start.bat`**. The first run creates a private Python environment and installs what it needs. Later
   runs only reinstall packages when `requirements.txt` has changed.
3. Open **http://localhost:8420** and go to **Settings**. Enter your Jellyfin URL (`http://localhost:8096`) and the
   API key, then click **Test connection** and **Save settings**.

**Linux**

```bash
./start.sh                       # or: python3 broadcast.py --port 8420 --data ./data
```

To run it as a service, see `scripts/jellyfin-broadcast.service`.

**Command-line options** (both systems): `--port 8420`, `--data <folder>` (where settings and schedules are kept) and
`--host 0.0.0.0`.

### Start automatically with Windows

Run this from an **administrator** PowerShell in the project folder:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-windows-startup.ps1
```

It registers a hidden startup task and opens Windows Firewall for devices on your local network, whatever network type
Windows thinks it is. It also removes any firewall "block" rules for Python left over from an earlier "allow this app?"
prompt, because those override every allow rule. At the end it prints the addresses to use from your other devices.
If you skip this, Windows Firewall will ask the first time instead.

- The task starts at boot, before anyone signs in, and restarts the server if it ever quits.
- To stop it by hand, use **End** on the "Barnes TV Broadcast" task in Task Scheduler: that stops the server and all
  its ffmpeg processes. **Run** starts it again.
- After installing it, close any `start.bat` window: only one copy can use port 8420.
- To ride out power cuts, set the PC's BIOS/UEFI option **Restore on AC power loss** (also called *After power
  failure* or *AC back*) to **Power On**, and set Windows **Sleep** to **Never**.
- `-Check` shows whether the server is running and how the firewall is set up (it changes nothing).
- `-AnyAddress` also allows connections from outside your network, for example over a VPN.
- `-Uninstall` removes the task and its firewall rules.
- The task runs as the SYSTEM account. If you use direct media access with network shares, use UNC paths
  (`\\server\share`), not mapped drive letters.

### Connect to Jellyfin

The **Connect to Jellyfin** page in the app shows these addresses with copy buttons.

1. In Jellyfin, go to **Dashboard → Live TV → Tuner Devices → +** and choose **M3U Tuner**. Enter
   `http://<broadcast-server>:8420/iptv/channels.m3u`.
2. Go to **TV Guide Data Providers → +** and choose **XMLTV**. Enter
   `http://<broadcast-server>:8420/iptv/xmltv.xml`. *Optional:* set "Movie categories" to `Movie`.
3. Click **Refresh Guide Data**. Your channels, logos and listings now appear under **Live TV** in every Jellyfin app.

If Jellyfin runs on the same machine, `<broadcast-server>` can be `localhost`. If it doesn't, use the machine's LAN
IP. You can pin that address under **Settings → Address Jellyfin uses to reach this app**.

### Find your way around the admin page

The admin page is at `http://<broadcast-server>:8420`. The top menu has:

- **Channels**: every channel, with what's on now. This is where you add and edit channels.
- **Guide**: a grid of what's on across all channels.
- **Bumpers**: the [bumper library](#the-bumper-library) and the default bumper music.
- **Connect to Jellyfin**: the tuner and guide addresses, the TV app, the phone remote (with a QR code) and
  [other ways to watch](#in-jellyfin-and-other-apps).
- **Appearance**: [themes, fonts and branding](#making-it-yours).
- **Settings**: see the [Settings reference](#settings-reference).
- **📱 Remote** opens the [phone remote](#phone-remote), and **▶ Watch TV** opens the [TV page](#in-a-browser).

The version number next to the station name is the server's version. After you update the server, an open admin
page reloads itself the next time you change pages, or shows a note asking you to reload if you have unsaved changes.

---

## Building a channel

### The channel list

**Channels** lists every channel with its logo and what's on now. **+ New channel** creates one and opens it in the
editor. For each channel:

- **Edit** opens the [channel editor](#the-channel-editor).
- **Watch** opens the channel on the [TV page](#in-a-browser).
- **Cast…** sends it to a [Chromecast](#casting-to-a-chromecast).
- **Copy stream URL** copies the channel's direct stream address, for VLC or any other player.

The **TV Guide** channel (channel 1) exists from the start. You can add a [weather channel](#the-weather-channel) by
setting a new channel's **Type** to **Weather channel**.

### The channel editor

A channel's page is split into four tabs:

- **🎨 Appearance:** name, number, group, theme, sleep timer, subtitles, the channel logo, the clock and the "Up next"
  banner, with a live preview. Restart stream, Log and Delete channel are here too.
- **📅 Scheduling:** what plays, the order, start times, time slots, marathons, the pool breakdown and the live schedule.
- **📢 Commercials:** commercial breaks and compilation splitting.
- **✨ Bumpers:** which bumpers play, where and how often.

Guide and weather channels have **Appearance** and **Guide** / **Weather** tabs instead.

- **One Save button** saves every tab at once. A dot on a tab marks unsaved changes there.
- **Saving is instant.** If the change affects the schedule, the server re-plans it in the background. A note in the
  bottom-left corner says it's working; you can keep editing or leave the page, and a message tells you when it's done.
  The library is only re-read from Jellyfin when the change needs it: what plays, what's excluded, item types, length
  limits, filler, commercial or bumper sources, or a time slot's show. Changes such as order, start times, break
  lengths or slot times re-plan from the items already in hand, usually in well under a second.
- **Re-planning starts after whatever is on now**, so viewers aren't interrupted. Graphics changes (logo, clock,
  banner) reach the stream within seconds, and people who are watching stay connected.
- The page remembers the last tab you used.

### Appearance tab

**Channel card**

- **Name**, **Number** (decimals like 4.1 work) and **Group**. The group is shown in Jellyfin, for example "Kids".
- **Type**: a regular channel, the [guide channel](#the-guide-channel) or a [weather channel](#the-weather-channel).
- **On the air**: untick to take a channel off the lineup without deleting it.
- **🧸 Kids channel**: always watchable, even when the [channel lock](#kids-channels-and-the-channel-lock) is on.
- **🌙 Sleep channel**: turns the screen off by itself after 1–30 minutes. See
  [Screen off and sleep channels](#screen-off-and-sleep-channels).
- **Theme**: on a regular channel, this changes the channel's "Up Next" and standby cards, its "Up next" banner and
  its default clock font. See [Themes](#themes).
- **Restart stream** stops and restarts the channel's encoder. **Log** shows what the channel has been doing, including
  why a file didn't play and which subtitles were picked. **Delete channel** removes it.

**On-screen graphics**

**Preview** renders one frame of what's on now with your logo, clock and banner, so you can check placement. Save
first to preview changes.

- **Channel logo ("bug")**: upload an image (PNG with a transparent background looks best). Pick any of the four
  corners, the size and the opacity. Without an upload, no logo is shown on the video, and a generated number badge is
  used in guides.
- **Clock**: tick **Show the time on screen**, then choose:
  - the corner (top-left by default; if the logo uses the same corner, the clock stacks neatly under it)
  - the format: 12- or 24-hour, with or without AM/PM or seconds
  - the size
  - a **quick style**: Japanese broadcast (rounded gothic with a thick outline), VCR 7-segment, news ticker, teletext,
    neon or subtle
  - or set it yourself: font, colour, clock opacity, the bar behind the time, outline (none, thin or thick) and drop
    shadow. The sample updates as you go.

  The clock uses the Broadcast server's time zone. The 7-segment faces only have digits, so pair them with 24-hour
  time or "no AM/PM".
- **"Up next" banner**: slides in near the end of each program with the next show's title. Set how many seconds before
  the end it appears and how long it stays.

**Subtitles**: see [Subtitles](#subtitles).

### Scheduling tab

**Programming**

- **What plays on this channel**: mix and match libraries, genres, collections, single series, playlists, tags or
  studios/networks. Pick a type, optionally type to filter, choose an item and click **Add**.
- **Never play**: anything matching these is removed, for example the Horror genre on a kids channel.
- **Item types**: movies, episodes, music videos and home videos. **Include specials (season 0)** is off by default.
- **Shortest item** and **Longest item** in minutes (0 = any), for example a movie channel with "shortest 60".
- **Order**:
  - *Shuffle*: everything plays once before anything repeats, with each show's episodes spread out through the mix.
  - *Rotate shows*: a random show in each slot, with each show's episodes in order, like classic reruns.
  - *In order*: by series, season and episode (or release date), then loops. Playlists keep their own order.
  - *Pure random*: anything can play next.
- **Never play the same show twice in a row** (on by default): another show always airs in between when the channel
  has anything else to play. "In order" then takes turns between shows, each show's episodes still in order. With one
  big show and one tiny one, the tiny one reruns more often to keep them apart.
- **Start times**: back-to-back, or on the quarter hour, half hour or hour. The gaps are filled with your **filler**,
  and whatever's left shows an "Up Next" card.
- **Audio language**: for example, Japanese audio on the anime channel. "Default track" plays each file's default.
- **Even out loudness**: levels each program's volume so loud and quiet shows sit closer together.
- **Filler for the gaps**: short clips (15 minutes or less) used to fill gaps before the next start time:
  commercials, music videos, shorts. **Tip:** a "Commercials" or "Bumpers" library in Jellyfin (Home Videos type works
  well) makes the half-hour padding feel just like real TV.
- **Music under "Up Next" cards**: a file or a folder on the Broadcast server. A folder plays a random track. See
  [Music volume](#music-and-music-volume).

### Balancing shows

A channel plays every episode and movie in its pool once before repeating, so its airtime follows the size of each
show: if one show has 300 episodes and another has 10, the big one gets most of the time. The **📊 What's on this
channel** card shows this as a pie chart. Use **Items**, **Hours**, **Airtime goal** or **Scheduled** to switch what
the chart shows. With balancing on, the card opens on **Airtime goal**, and the other views show a **Goal** column.

- **Even out the shows** is off by default (0%). At 100%, every show gets the same airtime. In between, big shows
  still get more time, just less of a lead.
- Each show also has a **weight** slider, from ×0.25 to ×4, to fine-tune a single show. All movies count as one
  "show", and so do all other clips.
- When balancing gives a small show a lot of airtime, it repeats more often. The table warns you when a show will
  run through all of its episodes in under two days.
- With **Never play the same show twice in a row** on, no show can air more than every other slot, so a goal above
  about 50% can't be met. The card tells you when that happens.

Turn the slider back to Off, or click **Reset balancing**, to return to the original behaviour.

### Time slots

**📅 Time slots → + Add a time slot** puts something on at set times, for example *The Simpsons, Mon–Fri 8–9 PM* or
*a movie every Friday at 8*. Regular programming fills the rest of the day. For each slot you choose:

- **Name** (optional), shown in the list.
- **What plays:** a series, collection, playlist, genre, or anything else you can add to a channel. It doesn't have to
  be part of the channel's regular programming.
- **Repeats:** every week on the days you pick (with **Mon–Fri**, **Weekends** and **Every day** shortcuts), or just
  once on a date. A weekly slot can be limited to a range of dates, such as a holiday season.
- **Plays:** from the start time to the end time, or **one episode or movie** at the start time and then back to
  regular programming. An end time earlier than the start runs past midnight.
- **Order:** **In order** plays the next episode each time, like a real weekly show, and picks up where it left off,
  even after you edit the channel or restart the server. **Shuffle** and **Random** are also available.
- **When it's time to start:**
  - **Start on time** (default): whatever is on before ends early. A shorter show, or the channel's filler and an "Up
    Next" card, fills the gap.
  - **Cut off** whatever is playing.
  - **Wait** for it to finish, so the slot starts late (and keeps its length).
- **If the next one would run past the end:**
  - **End on time** (default): don't start it; filler and an "Up Next" card fill the rest.
  - **Let it finish**, even past the end time.
  - **Cut it off** at the end time.

  The first program of a slot always airs, even if it's longer than the slot.
- **Commercial breaks** during the slot (on by default, using the channel's break settings).
- **Only show this in its time slot**, to take it out of the channel's regular programming.

Click **Done**, then **Save** the channel. Each slot in the list shows what it found in Jellyfin and when it airs next,
with the episodes. For **In order** slots, **Next episode** lets you pick where it continues from (save other changes
first). A slot can be turned off with its checkbox without deleting it. If two slots overlap, the card warns you: the
one that starts first plays and the other is skipped that day. Time slots appear in the schedule, the guide and the EPG
like any other program, marked 📅 on the channel's page.

### Marathons

**🏃 Marathons → + Schedule a marathon** puts one show on back to back. You choose:

- **Which show:** usually a single series. A collection or playlist also works.
- **Day and start time:** up to 7 days ahead.
- **How long:** 1 to 24 hours. The slider shows when it will end.
- **Start with:** the first episode or any episode you pick (each listed with its running time). The marathon plays
  **in order** from there, or **shuffled**. If the show runs out before the marathon ends, it starts over from the
  beginning. The editor tells you when a show is shorter than the marathon.
- **When it's time to start** and **if the last episode would run past the end:** the same choices as time slots.
- **Commercial breaks** during the marathon.

While a marathon is on it takes over the channel, including its time slots. A time slot that's running when the
marathon starts ends there, and slots that would start during it are skipped that day. The Time slots and Marathons
cards both say when this happens. Each marathon in the list shows a countdown (or **● On now**), the episodes it has
planned, and any warnings. The channel's schedule marks marathon programs with 🏃. A channel plans far enough ahead to
include an upcoming marathon, so it's in the guide and the EPG as soon as you save, even if it's further out than
**Days of schedule to plan ahead**. Finished marathons stay in the list until you delete them.

### The live schedule

The **Schedule** card on the Scheduling tab shows the next 24 hours, with the program that's on now highlighted, and
how many items, hours, fillers and commercials the channel has in rotation.

- **⏭ Skip what's on** moves on right away. If a show is on, the whole show is skipped, including its remaining parts
  and breaks, and a new one starts. If an ad or bumper is on, only that clip is skipped and the rest of the break moves
  up. Useful when a file doesn't play right.
- **Rebuild schedule** re-reads the library and reshuffles everything after the program that's on now.
- **Rebuild including now** re-reads the library and starts a fresh schedule this second, replacing what's on too.

Both rebuilds run in the background, like saving.

### Commercials tab

Shows pause every few minutes for spots from your own commercials library, then resume at the exact frame where they
stopped.

1. In Jellyfin, create a library for your commercials. *Home Videos* type works well. Fill it with short clips:
   old ads, station IDs, trailers.
2. On the channel's **Commercials** tab, tick **Interrupt shows with commercial breaks** and pick that library. Then
   set:
   - **Minutes of show between breaks.** About 7–8 feels like a half-hour sitcom. 12–15 feels like a movie channel.
   - **Break length.** Breaks are filled with whole commercials up to this length.
   - **No breaks in the last … minutes**, so the ending isn't interrupted.
   - **Max breaks per show** (0 = no limit), and whether breaks happen **during episodes**, **during movies** or both.
   - **Snap to chapter marks.** If a file has chapters near a break point, for example the act breaks in a TV rip,
     the break moves to that chapter.
   - **Keep logo & clock on commercials.** Off by default: the logo and clock are hidden during breaks, the way
     broadcasters do it.
3. Save. The break plan applies from the next show onward.

The program guide, Jellyfin's guide and the "now playing" info keep listing the show as one block. Every hand-over
between clips costs the stream a moment, so a channel can run a few seconds behind its schedule. Ads, bumpers and a
show's return from a break still always start from their first frame. The channel catches up by dropping a whole
commercial once it's more than about 6 seconds behind, so nothing gets clipped.

**Commercial compilations**

You don't need to cut compilation videos ("80s Commercials, 12 minutes") into separate clips. Put them in the
commercials library as they are. With **Find the separate ads inside long commercial videos** on (the default), every
commercial video longer than 90 seconds (adjustable) is scanned once in the background. The scan looks for the black,
silent frames between ads. When ads are joined by hard cuts instead, it looks for scene changes that land on standard
ad lengths (15, 30, 60 seconds...). Each ad found then plays on its own, straight from the original file. Nothing is
cut or re-encoded.

- Scanning reads the whole file once, one file at a time, at low priority. Expect roughly a tenth to a third of the
  video's length per file, depending on resolution and your CPU. Ads become available as files finish.
- Files with chapter marks at each ad use those instead.
- The Commercials tab lists every compilation and how many ads were found. **Review** shows one picture from the start
  of each ad. Odd lengths are outlined, because those are usually two ads glued together or one ad split in two.
  **Rescan** scans a file again, and **Don't split** plays a file as one piece (only if it's 10 minutes or less).
- Known limit: two ads joined by a hard cut with no pause, in a stretch that is itself a normal ad length (for
  example 30 + 15 = 45 seconds), stay together.

### Bumpers tab

Bumpers are the short text cards between shows and around breaks. Write and edit them in the
[bumper library](#the-bumper-library); turn them on per channel here:

- **Play bumpers**, and where: **Going into a break**, **Coming back from a break**, **Between shows** ("next: …").
  "Going into a break" only applies when commercial breaks are on.
- **Keep logo & clock on bumpers** (off by default).
- **Bumpers around commercial breaks**: every break, or every 2nd, 3rd or 4th break.
- **Text bumpers to use**: tick the ones for this channel. None ticked means all of them.
- **Video bumpers from Jellyfin**: short clips (under 5 minutes) you made yourself, mixed in at any spot.

If you edit a bumper's text, the change shows up the next time it airs. New bumpers are added to the schedule straight
away.

### Channel recipes

| Channel | Sources | Order | Start times | Extras |
|---|---|---|---|---|
| **Saturday Morning Cartoons** | Genre *Animation*, with Genre *Horror* excluded | Rotate shows | Half hour | Filler: a "Commercials" library of old ads |
| **Japanese TV** | Library *Anime* or Tag *japanese* | Rotate shows | Half hour | Audio language: Japanese |
| **Movie Channel** | Library *Movies* (shortest item 60 min) | Shuffle | On the hour | "Up Next" banner, clock off |
| **Network channel** | Studio *Cartoon Network* or *Fuji TV* | Rotate shows | Half hour | Logo bottom-right at 60% opacity |
| **Prime time** | A mix of shows | Shuffle | Half hour | A [time slot](#time-slots) for one show Mon–Fri 8–9 PM, in order |
| **Sleep channel** | Ambient videos or a calm show | Shuffle | Back-to-back | 🌙 Sleep channel: screen off after 15 minutes |

---

## YouTube

Any channel can play YouTube videos alongside (or instead of) your Jellyfin library. They stream straight from
YouTube: nothing is downloaded to disk. Under **Scheduling → What plays on this channel**, pick **▶ YouTube link**
in the type menu, paste a link and click **Add**:

- **A video**: `https://www.youtube.com/watch?v=…` or `https://youtu.be/…`.
- **A playlist**: any link with `list=…` in it.
- **A whole channel**: `https://www.youtube.com/@name` (or a `/channel/…` link). Its newest 500 videos are used,
  played oldest first; playlists play in their own order.

The app reads the link right away and says how many videos and hours it found. Live streams, upcoming premieres,
private and deleted videos are left out. YouTube links work in time slots and marathons too, and as filler.

**How YouTube videos behave on a channel**

- They're in the guide like any other program: the video's title, with the YouTube channel's name underneath, and its
  thumbnail as the poster.
- Each YouTube channel counts as one "show": **Never play the same show twice in a row** keeps two videos from the
  same creator apart, and [balancing](#balancing-shows) treats each creator as one show.
- **In order** plays them in YouTube's order. Commercial breaks follow the **During episodes** setting.
- YouTube's own ads never play. (Sponsor segments that creators put inside their videos are part of the video, so
  those do.)
- The list of videos is re-read with the rest of the library (**Settings → Re-scan libraries every**), so new uploads
  join the rotation.
- Each video is looked up just before it airs (the upcoming one ahead of time), so it starts like any other program.
  YouTube's links expire after a few hours, so nothing is stored.

**What it needs**: [yt-dlp](https://github.com/yt-dlp/yt-dlp), which talks to YouTube, plus the Deno JavaScript
runtime and yt-dlp's challenge solver. YouTube now requires these to play most videos. All three are installed by
the start scripts. **Settings → YouTube** shows what's installed, and **Update YouTube support** upgrades them in
the background without a restart. YouTube changes things often, and a newer yt-dlp is usually the fix when videos
stop playing.

**Signing in (optional)**

You don't need to sign in to stream YouTube, and YouTube's ads don't play either way. Signing in is useful for:

- age-restricted, members-only and private videos and playlists (including your own private playlists);
- YouTube Premium's higher-bitrate streams;
- when YouTube starts asking to "confirm you're not a bot".

The sign-in works with a **cookies.txt** file:

1. Open a private/incognito window and sign in to youtube.com.
2. Export the cookies with a "cookies.txt" browser extension (for example *Get cookies.txt LOCALLY*).
3. Close that window without signing out. (YouTube changes the cookies of a window that stays open, which can make
   the exported ones stop working.)
4. In **Settings → YouTube**, click **Upload cookies.txt…**, then **Test playback**.

The file is kept in the data folder (`data/youtube/cookies.txt`) and only sent to YouTube. **Remove sign-in** deletes
it. Treat it like a password: anyone with it can use your YouTube account.

**Good to know**

- Streaming through yt-dlp isn't an official YouTube app, so it's outside YouTube's terms of service, and YouTube can
  change things at any time and break it until yt-dlp catches up. yt-dlp's developers warn that accounts used with it
  can, rarely, be flagged; if that worries you, sign in with a secondary account.
- Picture quality follows **Settings → Video → Resolution** (720p by default).
- If a video can't be played (removed, region-blocked, needs a sign-in), the channel shows "Please Stand By" until
  the next program, and the channel's **Log** says why.

---

## The bumper library

Open **Bumpers** in the top menu. The app comes with about 60 built-in bumpers in a deadpan late-night style, to use
as they are, edit or delete. The filter buttons at the top sort them by where they play, weather and time of day. If you
delete built-in ones and want them back, **Restore built-in bumpers** returns them. **+ New bumper** starts a fresh one.

Each bumper is a short sequence of text cards. For each one you set:

- **Where it plays:**
  - *Going into a break*, for example "{show} / will be right back."
  - *Coming back from a break*, for example "and now, / back to {show}."
  - *Before the next show*, for example "next: / {next}."
  - *Anywhere*: random thoughts, station IDs, "it's {time}. you're still up."
- **When it plays** (optional):
  - a time of day: late night, mornings, daytime, evenings, or weekends
  - a kind of weather from your weather channel: raining, snowing, thunderstorms, clear, cloudy, foggy, hot, cold,
    freezing, windy, or nice out
- **Cards:** the text, and how many seconds each card stays on screen. You can also set the beat of black between
  cards.
- **Font:** pick from a gallery that shows each font in your bumper's colours. Your own fonts are included.
- **Look:**
  - background and text colour
  - regular or bold weight
  - size, centred or left alignment
  - all-lowercase, as typed, or ALL CAPS
  - a small corner tag such as `[{channel}]`
  - optionally your own font file and music
- **Live details** in the text: `{show}`, `{episode}`, `{next}`, `{next_time}`, `{channel}`, `{number}`,
  `{station}`, `{time}` and `{day}`.
- **Weather details** from your weather channel's forecast: `{weather}` ("41° and light rain"), `{temp}`,
  `{feels_like}`, `{conditions}`, `{high}`, `{low}`, `{rain_chance}`, `{wind}`, `{humidity}`, `{tomorrow}`,
  `{tomorrow_high}`, `{sunrise}`, `{sunset}`, `{city}`, `{weather_channel}` and `{weather_number}`.

The preview shows each card as you type, and **▶ Play** runs the whole bumper with its timing.

Time-of-day bumpers are only scheduled into their hours. Weather bumpers are checked just before they air. If the
weather doesn't match (a "raining" bumper on a sunny day), or there's no forecast to quote, a different bumper of the
same kind plays instead. With no weather channel set up, weather bumpers are left out entirely.

### Music and music volume

- **Default music for bumpers** (top of the Bumpers page): a file, or a folder for a random track each time. Used by
  every bumper that doesn't pick its own music. If that's not set either, bumpers use the channel's music, or play
  silent. The page tells you how many audio files it found.
- **Match music to the shows' volume** (on by default): music is mastered much louder than TV, so every music track is
  measured once (in the background, at low priority) and turned down to the same loudness as the shows. On channels
  with **Even out loudness** on, music matches that level instead.
- **Music volume**: your own adjustment on top, from -30 to +10 dB. Untick **Match music to the shows' volume** to
  play music as recorded, with only the slider applied.
- These settings cover all background music: bumpers, "Up Next" cards, the guide and the weather channel. Changes
  apply from the next bumper or card.
- Music starts at a random point in the song each time (never in its last minute), so a bed doesn't always open the
  same way.

---

## The guide channel

The guide channel is channel 1 when you first start the app: a live channel with a big clock, a "Now On" spotlight
with poster art, and a smoothly scrolling grid of every channel that's on the air. Its **Guide** tab has:

- **Background music**: a file or a folder of music on the Broadcast server.
- **Scroll speed** and the **clock format**.
- **Listings font** and **Clock & channel numbers font**. Leave either on "Theme default" to follow the
  [theme](#themes).

Its **Appearance** tab has the **Theme** (which restyles the whole guide) and the **Corner logo**: what sits in the
top-left corner of the screen.

- **Station logo**: your logo from **Appearance → Branding** (the Barnes artwork by default).
- **This channel's logo**: the channel logo uploaded just below it (or the generated number badge if there isn't one).
- **A different image…**: upload any picture just for that corner. PNGs with a transparent background look best;
  empty borders are trimmed automatically.
- **Station name as text**, or **Nothing**.

There's a size slider, and a **Recolour** option that paints a one-colour logo in the theme's colour. Changes show up
on screen within a few seconds; uploading a corner image doesn't interrupt anyone watching. The **Channel logo** below
it is what the guide listings, the TV page and app, and Jellyfin's Live TV show for this channel.

---

## The weather channel

Add a channel and set **Type** to **Weather channel**, then save. It's drawn live like the guide channel and rotates
through these screens (tick the ones you want on its **Weather** tab):

- **Current conditions**: temperature, sky, feels-like, humidity, dew point, wind and gusts, pressure, visibility, UV
  and cloud cover, plus today's high and low and sunrise and sunset.
- **Next 12 hours**: an icon, temperature curve and chance of rain or snow for each hour.
- **7-day forecast**: a box for each day.
- **Local and regional radar**: the last hour of radar looping over a street map, with your location marked. If the
  newest radar picture is more than 40 minutes old, a "Radar delayed" notice says so. Pictures over 3 hours old are
  never shown.
- **Future radar** (US): forecast radar for the next 3 hours, every 30 minutes, from NOAA's HRRR model, clearly
  marked FORECAST. Outside the US this screen is skipped: RainViewer ended its free forecast radar in January 2026.
- **Sun & moon**: sunrise, sunset and daylight for today and tomorrow, peak UV, and the moon's phase.
- **Weather alerts** (US): watches, warnings and advisories from the National Weather Service, shown only when
  something is active. Alerts also lead the crawl.

**Other settings on the Weather tab**

- **Location:** **Automatic** works out where you are from your internet connection. You can also use a **ZIP /
  postal code** (with its 2-letter country code), a **city name**, or **exact coordinates**, and give it the name you
  want shown. Click **📍 Check location & weather** to see what it found.
- **Units:** automatic (°F, mph and inches in the US; °C, km/h and hPa elsewhere) or your choice.
- **Radar maps: how far in or out**: a zoom slider each for the local, regional and future radar, with a live
  "about 90 miles across" reading as you slide. Local radar goes from about 2,800 miles across down to about 45 (at
  720p; higher output resolutions show a little more). Zoomed in closer than the standard local view (about 350 miles),
  the street map keeps getting sharper while the radar picture is enlarged, because the radar services don't offer
  finer detail. After you save, the new maps are fetched straight away and show within a minute.
- **Seconds per screen** and **Radar loop length** (30 minutes to 2 hours).
- **Radar: hide weak echoes** (US). Most nights, and on calm days, the radars run in a sensitive "clear-air" mode and
  pick up bugs, birds, dust and temperature layers. Unfiltered, that shows up as grey-blue static across the map and
  beige rings around each radar site. By default anything below 10 dBZ is left out, which removes the static and keeps
  drizzle and light snow. Lone specks are cleaned up too, and what's left is drawn in the standard NWS colours that
  match the legend. Choose from **Show everything** (the raw radar) up to **Below 20 dBZ** (rain only).
- **Severe weather alerts** (US) on or off.
- **Scrolling crawl** along the bottom (the current conditions and the next few days) and its speed.
- **Background music**: a file or a folder on the Broadcast server.
- **Text font** and **Big numbers & headings font**.

On the **Appearance** tab, the **Theme** restyles the whole channel (colours, fonts, box style, decorations; light
themes get a light map), and the **Corner logo** works like the [guide channel's](#the-guide-channel). **Preview**
can render any of the screens.

**Weather maps need a free CARTO key.** The street maps under the radar come from CARTO. Get a key at
carto.com/basemaps/apikey (leave the website field blank, so it works from your server) and enter it under
**Settings → Weather maps**.

**Where the data comes from:** forecasts from [Open-Meteo](https://open-meteo.com), alerts from the US National
Weather Service, radar and forecast radar from NOAA via the
[Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu) in the US, radar from
[RainViewer](https://www.rainviewer.com) elsewhere, and maps from OpenStreetMap / CARTO. All are free for personal use,
and each is credited on screen. Forecasts refresh every 10 minutes, and alerts and radar every 5. Each radar refresh
only downloads the newest picture, and a failed refresh tries again within 2 minutes. If the internet drops, the
channel keeps showing the last good forecast.

---

## Subtitles

On a channel's **Appearance** tab, the **Subtitles** card has:

- **Show subtitles**:
  - **Off**.
  - **Always, when the show has them**: picks the full subtitle track in your language.
  - **Only when the audio isn't in my language**: for example, an anime channel with Japanese audio gets English
    subtitles, but English-dubbed episodes don't.
  - **Only "forced" subtitles**: just the signs, songs and foreign-language lines that some releases mark as forced.
- **Subtitle language**, **size**, **font** (for plain-text subtitles), and **look**: white with a black outline, or
  on a dark box.

By default only shows and movies get subtitles, not commercials or filler. Styled anime (ASS) subtitles keep their
own fonts and colours; Japanese, Chinese and Korean subtitles automatically use a font that has those characters.

Subtitles are drawn into the picture, so they show everywhere: Jellyfin, browsers, Chromecasts and the TV app. Text
subtitles (SRT, ASS, VTT, including separate files next to the video) are fetched from Jellyfin; Blu-ray (PGS) and DVD
picture subtitles are read straight from the video. Text subtitles need an ffmpeg with libass; Jellyfin's own ffmpeg
has it. If a show's subtitles ever stop a show from playing, it carries on without them and the channel's Log says so.

**Not seeing subtitles?** Click **Check subtitles on what's on now**. It lists the subtitle tracks Jellyfin reports
for the current show and says exactly which one is used, or why none is (wrong language, no forced track, audio
already in your language, no libass in ffmpeg…). Tracks without a language label are used when no track matches your
language. The channel's Log also notes the subtitle decision for every show.

---

## Watching

### In Jellyfin and other apps

- **Jellyfin Live TV**: once [connected](#connect-to-jellyfin), the channels show up under **Live TV** in every
  Jellyfin app (TV, phone, browser) with a full program guide.
- **Plex, Emby or Channels DVR**: add `http://<broadcast-server>:8420` as an HDHomeRun tuner.
- **Any IPTV player** (VLC, TiviMate, Kodi): open the M3U playlist `http://<broadcast-server>:8420/iptv/channels.m3u`
  and, if it supports one, the XMLTV guide `http://<broadcast-server>:8420/iptv/xmltv.xml`.
- **A single channel**: **Copy stream URL** on the channel list gives its direct address.

A channel only runs ffmpeg while someone watches it, and several viewers of the same channel share one stream.

### In a browser

Open `http://<broadcast-server>:8420/tv` (or **▶ Watch TV** in the admin page) and click to turn the TV on. Then use
these controls:

- **↑/↓** or **PgUp/PgDn**: change channel
- **+/−**, **[/]** or the mouse wheel: volume (remembered between visits)
- **digits**: jump to a channel number
- **G**: guide
- **I**: info banner
- **M**: mute
- **F**: fullscreen
- **C**: cast

On a phone, tap the picture to show the controls (Ch −/+, Guide, Info, Sound, Cast) and swipe up or down to change
channel. Playing video in the browser needs Chrome, Edge, Firefox or desktop Safari. iPhones can't play these streams
in a browser, but they can still cast and act as the remote.

If the server restarts, the TV page reconnects by itself and carries on with the same channel.

### Screen off and sleep channels

**🌙 Screen off** turns the picture pitch black while the sound keeps playing. It's on the control bar, and also the
last rows of the guide: **Turn the screen off**. That guide row is how you do it in the TV app with the TV remote.
Any button, a click or a tap brings the picture back without changing the channel. Volume keys keep working in the
dark. On a TV, "black" means the panel shows black: an OLED goes fully dark, while an LCD's backlight stays on.

To make a **sleep channel**, set the channel's **🌙 Sleep channel** option to turn the screen off by itself 1–30
minutes after you tune in or last press a button. Screen off isn't available while casting to a Chromecast.

### Phone remote

Open `http://<broadcast-server>:8420/remote` on your phone. The **Connect to Jellyfin** page in the admin has a QR
code for it, so you can just scan it with the camera. Then pick a TV.

- **Controls:** big channel and volume rockers, a volume slider, mute, a number pad, the guide (tap a show to tune),
  and what's on now and next.
- **Controlling a TV that's already playing:** if someone else started casting, choose that TV and the remote takes
  over without restarting the channel.
- **Coming back later:** reopening the page reconnects to the TV you used last.
- **Home screen:** use the browser's **Add to Home screen**, and the remote opens full-screen like an app.

The remote only sends commands, so it uses almost no data and works on any phone, including iPhone.

### Casting to a Chromecast

1. Open `http://<broadcast-server>:8420/tv` on your phone or computer. Then press **C** or tap **Cast**, and pick your
   TV.
2. The page turns into a remote: ▲/▼ change channel, and there are buttons for the guide, volume and **Stop casting**.
   If you reopen the page later, it picks the remote back up.
3. You can also use the **Cast…** button on any channel in the admin page.

Your logo and clock show on the TV because they're part of the video itself.

**How it works:** Chrome's built-in Cast button only works on HTTPS sites. So instead, the Broadcast server finds the
Chromecasts on your network and tells them to play the channel as an HLS stream through Google's standard media
player. No app registration or certificates are needed, and the remote works from any phone, including iPhone.
Turning the channel into an HLS stream doesn't re-encode the video, so it adds almost no load. It stops by itself
about 25 seconds after the TV stops watching.

**If the TV shows a grey screen with a Cast icon:** the TV page's cast panel says why, in plain words.

- *"The TV never requested the stream…"*: the TV can't reach this computer. On Windows, run
  `powershell -ExecutionPolicy Bypass -File scripts\open-firewall.ps1` from an administrator PowerShell. It works
  whether Windows has your network set to Private or Public, and it clears out old firewall rules that block Python.
- *A Cast error code* (for example 315): the TV reached the stream but rejected it. `broadcast.log` has the details.
  You can also try **Settings → Chromecast → Stream format**.

**Good to know:**

- The TV must be able to reach the Broadcast server. If the address shown under **Settings → Chromecast** is wrong,
  set **Address Jellyfin uses to reach this app** to the server's LAN IP.
- If no TVs show up, check that the TV is on the same network. On Windows, also check that the firewall allows
  discovery: the startup script adds that rule for you. As a fallback, you can type the Chromecast's IP address
  under **Settings → Chromecast**.
- The TV plays a few seconds behind live, so its buffer never runs dry. Channels that are already being watched
  start almost instantly, because the server keeps the last ~20 seconds of each running channel in memory.
- If `broadcast.log` says a channel *"is only encoding at 0.8x real time"*, the computer can't encode fast enough.
  Viewers will buffer no matter what. Pick a faster preset, 720p, or your GPU under **Settings → Video**.
- Changing channels takes a few seconds on a Chromecast. That's how long it takes the Chromecast to start a new
  stream. When you flip through channels quickly, the TV only loads the one you stop on.
- **Stuck picture:** the server checks each TV every few seconds. If a picture that was playing freezes or buffers
  for 25 seconds, the player stops with an error, or it never starts within about a minute, it reloads the channel on
  the TV by itself (up to 5 times in a row; after that the remote shows what to check). It only watches while the Cast
  player is open on the TV: press Home or Back on the TV and it leaves the TV alone. You can also tap **Picture stuck?
  Restart the stream on the TV** on the remote. To turn the automatic restart off, untick it under
  **Settings → Chromecast**.
- Jellyfin's own apps may also be able to cast these channels with their Cast button, because to Jellyfin they're
  regular Live TV channels.

### TV app for Google TV and Android TV

The TV app (called **Barnes TV** unless you build it with your own branding) runs on a Google TV Streamer, Chromecast
with Google TV, Nvidia Shield or any Android TV. It's the full TV page, driven by the TV remote:

| Button | Does |
|---|---|
| ▲ / ▼ (or CH + / CH −) | Change channel |
| OK (or Guide / Menu) | Open the guide; in the guide, ▲▼ pick and OK watches |
| ◀ | Back to the last channel |
| ▶ (or Info) | What's on now and next |
| Back | Close the guide / lock screen; press again to leave the app |
| Numbers (TV remotes) | Type a channel number |

Locked channels show a code pad you can work with the D-pad. The app finds the server on your network by itself the
first time; to switch servers, open the guide and scroll to **Switch server**. If the server restarts, the app
reconnects by itself.

**Installing it:** open `http://<broadcast-server>:8420/app` for step-by-step instructions (the short version:
install **Downloader** from the TV's Play Store, allow it to install apps, and type
`http://<broadcast-server>:8420/app.apk`). Android may ask you to confirm installing an app from outside the Play Store
("unknown sources"); that's normal for any sideloaded app.

**Building the app file:** the app's source is in `android-tv/`. Either open that folder in **Android Studio** and
choose **Build → Build APK(s)**, or on Linux/macOS with a Java JDK installed run
`bash android-tv/get-tools-and-build.sh` (it downloads the build tools once and writes `web/app/BarnesTV.apk`). Copy
the result to `web/app/BarnesTV.apk` and the `/app` page offers it for download. The app has no third-party code:
one Java file that finds the server and shows its TV page. It targets current Android (API 35), so Android doesn't
warn that it was "built for an older version of Android", and it has an adaptive launcher icon (with a themed version
for Android 13+) plus a TV banner.

**Your branding in the app:** the app's name, icon, icon background and TV banner come from a *branding kit*.
Either build straight from your server:

```bash
bash android-tv/get-tools-and-build.sh --brand http://<broadcast-server>:8420
```

or download the kit (**Appearance → Branding → ⬇ TV app branding kit**) and use `--brand tv-app-branding.zip`. A kit
unzipped into `android-tv/branding/` is picked up automatically. For Android Studio builds, run
`python android-tv/build.py --brand <kit> --apply` once to write the branding into `android-tv/res/`.

**Signing:** installing a newly built app over the old one keeps its settings, because every build is signed with your
own key. `build.py` creates it on the first build (`android-tv/release.keystore`, password in
`android-tv/keystore.properties`). Both stay on your computer and are never committed, so back them up: an update
signed with a different key won't install over the old app. Android Studio users: run
`python android-tv/build.py --keystore-only` once to create the key.

**Why not a Chromecast app?** A real Cast receiver app needs a paid Google developer registration and an HTTPS
website, and even then Google's Cast player doesn't pass the remote's channel buttons along. Google TV devices are
Android TV devices, so a regular TV app is the way to get the remote working.

---

## Kids channels and the channel lock

1. Edit each channel that's fine for kids and tick **🧸 Kids channel**. The TV Guide channel is always available.
2. In **Settings → Channel lock**, choose a 4–8 digit code and tick **Lock every channel that isn't marked as a Kids
   channel**. Set how long one code entry unlocks a device for (60 minutes by default).

With the lock on:

- **Locked channels ask for the code.** Tuning to any non-kids channel on the TV page or the phone remote shows a lock
  screen with a number pad. You can also type the code on a keyboard.
- **The code unlocks that one device** for the time you chose. The guide has a **🔒 Lock** button to lock it again
  early.
- **🧸 Go to a kids channel** jumps to the next channel that's allowed.
- **Casting is covered too.** Casting a locked channel to a TV asks for the code on the phone first.
- **The settings are locked.** Changing anything in the admin page, including turning the lock off or changing the
  code, asks for the code, unless you've set an admin password.
- **The server enforces all of this**, so typing a stream address into a browser doesn't get around it. Five wrong
  codes in a row trigger a one-minute cool-down.

**Jellyfin:** Jellyfin can't ask for a code, so the playlist this app gives Jellyfin carries a private key that plays
every channel. After you first turn on the lock, click **Refresh Guide Data** in Jellyfin so it picks up the new
links. If kids use the Jellyfin app too, tick **Also hide locked channels from Jellyfin**, and Jellyfin will only
list the kids channels (refresh its guide after changing this). It's meant to keep kids out, not to stand up to a
determined adult on your network: anyone who finds the Jellyfin playlist address can use those links.

---

## Making it yours

### Themes

There are 13 built-in station themes: Barnes Classic, Retro Cable, Groovy '70s, Sleek Futuristic, Art Deco, Corporate
Memphis, Synthwave, Teletext, Tokyo Broadcast, Frutiger Aero, Green Phosphor, Atomic Age and 8-Bit Arcade. Each one
restyles the guide channel, the weather channel, the "Up Next" and standby cards, the "Up next" banner, the admin page,
the TV page and the phone remote.

Open **Appearance** in the admin page. Click a theme to preview it: the admin page restyles itself immediately, and
you see a guide channel frame and an "Up Next" card in that theme. Click **Save** to apply it. A running guide
channel switches to the new look within a few seconds, with no restart.

**One channel, different theme:** open the channel and pick a **Theme** on its Appearance tab. On a regular channel, it
changes that channel's Up Next and standby cards, its Up Next banner and its default clock font. On the guide or
weather channel, it changes the whole channel.

### Theme builder

On **Appearance**, click **Create a theme** (or **Copy & customise** on any theme). You can change:

- **Colours** for every part of the guide channel (background, header, channel column, up to four alternating
  programme-box colours, time bar, spotlight, "now" line), the text and highlight colours, and the admin/TV page
  colours.
- **Fonts** for the pages, headings, guide listings, guide clock and the on-screen clock.
- **Style**: the shape of the programme boxes (flat, bevelled, rounded, cut corners, art deco double frame, chunky,
  glossy, pixel…), a header decoration from any built-in theme, corner rounding, spacing, neon glow, scanlines, ALL
  CAPS, genre-coloured boxes, light or dark, the logo's colour, and how the admin/TV pages look.

The guide and "Up Next" previews redraw a moment after each change, and the admin page restyles itself live. Click
**Save & use for the station** to put it on air, or **Save** to keep it for later. Your themes appear alongside the
built-in ones everywhere, including each channel's **Theme** menu. A running guide channel picks up edits to the
theme it's showing within a few seconds. Deleting a theme sends anything that used it back to the station theme.

### Fonts

22 fonts are bundled, and you can add your own.

- **Your own fonts:** drop `.ttf` or `.otf` files into the `fonts` folder inside the data folder (the Appearance page
  shows the exact path), then reload the page. They're listed under "Your fonts" in every font menu.
- **Admin page, TV page and remote font:** under **Appearance → Fonts**.
- **Clock:** on a channel's Appearance tab, under **On-screen graphics → Clock**.
- **Guide and weather channels:** their own font menus on the Guide / Weather tab.
- **Bumpers:** each bumper's **Look** card has a **Font** gallery.
- **Subtitles:** a font menu on the Subtitles card.
- **Video text fonts:** **Settings → Media access & tools** sets the regular, bold and Japanese/CJK fonts used for text
  drawn into the video.

Japanese titles are always readable. If a font has no Japanese characters, those titles switch to a Japanese-capable
font (the bundled Maru Gothic if Windows doesn't have one).

### Branding

Out of the box everything says **Barnes Television Broadcasting System** / **Barnes TV**. To make it your own
station, open **Appearance → Branding**:

- **Station name** and **short name.** The full name appears on the guide, in bumpers' `{station}`, on the admin page,
  and as the tuner name in Jellyfin. The short name is used for the app name, page titles and phone home-screen icons.
- **Wide logo**: the guide header, the TV page start screen and the welcome screen.
- **Small logo**: the admin header, the corner of Up Next / Stand By cards, the weather header and the remote. If you
  upload only one logo, it's used for both.
- **App icon**: the browser tab, phone home-screen icons and the TV app. It's optional. Without one, the icon is
  made from the small logo on your **brand colour**.
- **Recolour the logos to match each theme**: right for one-colour logos on a transparent background (like the
  Barnes artwork). Untick it for full-colour logos so they keep their own colours.
- **⬇ TV app branding kit**: everything the [TV app](#tv-app-for-google-tv-and-android-tv) build needs to carry your
  name and icons.

Changes show up right away, including on the guide and weather channels while they're on the air. **Back to the
Barnes default** removes your logos and name. Uploaded files live in `data/brand/`; the Barnes originals in
`web/brand/` are never changed.

---

## Settings reference

**Jellyfin server**

- **Jellyfin URL** and **API key**, with **Test connection**.
- **Browse library as user**: which Jellyfin user's view of the library to use (for example, to respect that user's
  library access).

**Station**

- **Address Jellyfin uses to reach this app**: the LAN address put into the M3U playlist, the guide and Chromecast
  streams. Set it if the automatic one is wrong.
- **Admin password** (optional): protects the admin page.
- **Days of schedule to plan ahead** (3 by default). Upcoming [marathons](#marathons) are always planned, even beyond
  this.
- **Guide data hours (XMLTV)**: how far ahead Jellyfin's guide gets listings.
- **Re-scan libraries every (hours)**: how often each channel's list of items is refreshed from Jellyfin. The refresh
  runs in the background; channels keep playing from the last list meanwhile.
- **Stop a channel after nobody watches for (s)**: how long an unwatched channel keeps encoding before it stops.

**Video**

- **Resolution**, **Frame rate**, **Video bitrate** and **Audio bitrate**.
- **Encoder**: CPU (libx264) works everywhere. Hardware: NVIDIA NVENC, Intel QSV, AMD AMF, VAAPI (Linux, with its
  **VAAPI device**) or VideoToolbox. If one fails, switch back to CPU.
- **Speed preset**: faster presets use less CPU.
- **Deinterlace old TV recordings** and **Convert HDR to SDR** (tone mapping).

**Media access & tools**

- **How to read media**: **Stream from Jellyfin** (works anywhere) or **Read files directly** (same machine or a
  shared drive; faster).
- **Path mappings for direct mode**, one per line, `Jellyfin path => local path`, for when the paths Jellyfin reports
  differ from how this machine sees the files.
- **ffmpeg path**: leave empty to find it automatically.
- **Font**, **Bold font** and **Japanese/CJK font** for text drawn into the video.

**🔒 Channel lock (kids mode)**: see [Kids channels and the channel lock](#kids-channels-and-the-channel-lock).

**Chromecast**

- **Chromecast IP addresses** (optional): for TVs that aren't found automatically.
- **Stream format for Chromecast**: try another one if a TV rejects the stream.
- **Restart the stream automatically if a TV's picture freezes or gets stuck loading** (on by default).

**🌤 Weather maps**: the **CARTO map key** for the street maps under the radar.

**▶ YouTube**: what's installed for [YouTube](#youtube), **Upload cookies.txt…** / **Remove sign-in**, **Test
playback** and **Update YouTube support**.

**🧹 Maintenance: ↻ Restart server** stops every channel, stream and Chromecast connection and starts the server
fresh, like closing and reopening it. It takes about 10 seconds; the page reconnects by itself, browser viewers
reconnect, and Chromecasts that were casting are put back on the same channel. It works however you start the server
(start.bat, the Windows startup task, start.sh or systemd), because `broadcast.py` restarts itself.

---

## Performance

- **Encoding only happens when someone watches.** Each watched channel runs one ffmpeg encode, shared by all of its
  viewers. Idle channels cost nothing. A modern quad-core CPU handles a few 720p channels with libx264 at the
  `veryfast` preset.
- **Use your GPU** if you have one: **Settings → Video → Encoder**: NVENC (NVIDIA), QSV (Intel) or AMF (AMD) on
  Windows, and NVENC, QSV or VAAPI on Linux.
- **Direct file access** (**Settings → Media access**) is faster than streaming from Jellyfin when both apps run on
  the same box. Add path mappings if the paths Jellyfin reports differ from how this machine sees the files.
- **Saving is instant**: see [The channel editor](#the-channel-editor).
- **Startup doesn't wait for Jellyfin.** Each channel's last library list is kept on disk and used straight away, and
  a fresh copy is fetched in the background (at most two channels at a time) when it's older than **Re-scan libraries
  every (hours)**. Admin and TV pages never wait for a library query; they show what's planned so far. The music
  loudness check starts two minutes after startup. `start.bat` and `start.sh` only run `pip install` when
  `requirements.txt` has changed.

---

## How it works

```
Jellyfin library ──► scheduler ──► persistent timeline per channel (3 days ahead, saved in data/state)
                                      │
viewer tunes in ──► session: one ffmpeg per program (seeks to the right spot, scales, logo + clock overlays)
                                      │   pieces are stitched into one continuous MPEG-TS stream
                                      ▼
                       /stream/<channel>.ts ──► Jellyfin Live TV, VLC, browser TV page
                       /iptv/xmltv.xml      ──► Jellyfin's program guide
```

- Schedules are planned ahead and saved, so the guide is always accurate and tuning in drops you into the middle of
  whatever is "on". When the library changes, only the future schedule is affected.
- If a file can't be played, the channel shows a "Please Stand By" colour-bars card until the next program. Details go
  to that channel's **Log**. **⏭ Skip what's on** gets past it without waiting.
- Everything the app stores is in the `data` folder: settings, channels, schedules (`data/state`), cached library
  lists, logos, fonts and branding. Delete `data/state` to throw away all schedules.

---

## Troubleshooting

- **"ffmpeg not found"**: set the path in Settings, for example `C:\Program Files\Jellyfin\Server\ffmpeg.exe`.
- **Other devices can't reach the server** (but it works on the server itself): Windows Firewall. Run
  `powershell -ExecutionPolicy Bypass -File scripts\open-firewall.ps1` from an administrator PowerShell, or re-run the
  startup installer. Add `-Check` to the installer to see the current state.
- **"certificate verify failed" / "certificate has expired"** (weather, maps): Python's list of trusted certificates
  is out of step with Windows'. This happens most when the server runs from the startup task. The app checks
  certificates the way Windows does (the `truststore` package) and falls back to Mozilla's list (`certifi`). Both are
  installed by `start.bat`, and by `install-windows-startup.ps1` each time you run it.
- **Weather not updating**: the Weather tab's **📍 Check location & weather** shows the last error for the forecast,
  alerts and radar.
- **A weather screen is missing**: **Weather alerts** only shows while an alert is active, and **Future radar** is
  skipped outside the US or while the forecast radar service sends no images. **📍 Check location & weather** says
  which.
- **Jellyfin can't load the M3U or the guide**: from the Jellyfin machine, check that
  `http://<broadcast-server>:8420/iptv/channels.m3u` opens in a browser. If it doesn't, check the firewall and the
  "Address Jellyfin uses" setting.
- **Channel stuck on "Please Stand By"**: open the channel's **Log**. The usual causes are a wrong API key, a path
  mapping problem in direct mode, or an unsupported encoder choice.
- **A program doesn't play right**: **⏭ Skip what's on**, or **Rebuild including now**, on the channel's Scheduling tab.
- **Japanese titles show boxes**: this shouldn't happen any more, because the bundled Maru Gothic font covers Japanese.
  For Chinese or Korean titles, set a CJK font in Settings. On Windows, Yu Gothic, Meiryo or Malgun Gothic are found
  automatically. On Linux, install `fonts-noto-cjk`.
- **"No matching distribution found for PyChromecast"**: your Python is older than the newest PyChromecast
  supports. The app works with PyChromecast 13.1 on Python 3.8–3.10, and `start.bat` installs that automatically.
  If pip still fails, the app starts without casting. Installing Python 3.12 (`winget install Python.Python.3.12`)
  and deleting the `.venv` folder gets you the newest version.
- **YouTube videos stop playing**, or "Please Stand By" on YouTube programs: **Settings → YouTube → Update YouTube
  support**, then **Test playback**. If it asks you to confirm you're not a bot, or the video is private,
  age-restricted or members-only, [sign in](#youtube). The channel's Log has the exact message.
- **Clock shows the wrong time**: the clock uses the Broadcast machine's time zone.
- **The admin page looks out of date after an update**: reload it once (Ctrl+F5). From 1.19.2 on, it reloads itself.

## Known limitations

- The browser TV page can't play on iPhone. Use Jellyfin's Live TV there, or cast from the iPhone.
- Hardware encoders depend on your drivers and ffmpeg build. If one fails, switch back to CPU.
- Screen off isn't available while casting to a Chromecast.
- Future radar and severe weather alerts are US-only.
