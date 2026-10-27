# Chuni Chara Maker

Put your own characters into CHUNITHM using any picture you like. No image editors, and no editing game files by hand.

Open a picture, move three boxes to choose the big picture, the select picture and the face icon, type a name and click Save. The app converts everything to the game's own DDS format and writes it into your own option folder. The game's files are never changed.

> Unofficial fan-made tool. Not made, endorsed or supported by SEGA. Contains no game files, artwork or music.

## Features

- **New characters** with their own IDs, or **replace** one of the game's characters (delete yours and the original comes back)
- **Transformations**: up to 9 extra looks per character, each unlocked at a character rank. Their boxes follow the Base look's boxes
- **Groups and version labels**: your own group with your own label. Every character in an option folder shares them, set by the folder's first character
- **Option folders**: make a new one for each set of characters, with its own label and group
- **Remove background** for plain backgrounds (optional AI cut-out with `rembg`)
- **Check a folder**: finds missing or misnamed DDS files, wrong image sizes, outdated sort lists and more, and fixes the safe ones
- Box positions and source pictures are saved, so "Edit this" brings everything back exactly as you left it

## Download and run

1. Install [Python 3.8 or newer](https://www.python.org/downloads/) and tick "Add python.exe to PATH".
2. Download this repository (Code → Download ZIP) and unzip it. Keep it outside the game's `bin\option` folder.
3. Double-click `Start Chuni Chara Maker.bat`. The first run installs Pillow and NumPy.

Or from a terminal:

```
pip install -r requirements.txt
python chuni_chara_maker.py
```

How to use it: see **What is Chuni Chara Maker.txt** (short), **README.txt** (step by step) and **Guide.html** (picture guide).

## What gets written

Everything goes into `bin\option\<your folder>\`:

```
data.conf
chara\charaXXXXXX\Chara.xml
ddsImage\ddsImageXXXXXX\DDSImage.xml + _00 / _01 / _02 .dds   (one folder per look)
charaWorks\...      (if you made a group)
releaseTag\...      (if you made a version label)
```

Projects (source pictures, box positions) and settings are kept in `%APPDATA%\ChuniCharaMaker`.

## Files

| File | What it is |
|---|---|
| `chuni_chara_maker.py` | The app (window, boxes, saving) |
| `chuni_mod.py` | Reads the game's folders and writes characters, groups and labels |
| `chuni_core.py` | Picture handling, BC3/DXT5 DDS encoder, XML helpers |
| `chuni_theme.py` | The dark theme |
| `icon.ico` / `icon.png` | The app icon |

## Made with AI

This tool was made with the help of AI (Claude, by Anthropic), working from my instructions and tested on copies of my own game files. It hasn't been reviewed line by line by a professional programmer and may contain bugs. Keep a backup of your option folder.

## License

Copyright (C) 2026 Chuni Chara Maker contributors

Chuni Chara Maker is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. See [LICENSE](LICENSE).

Third-party software and credits: [CREDITS.txt](CREDITS.txt).

The example character in `Guide.html` is Hatsune Miku, © Crypton Future Media, INC. 2007, used under [CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/) (illustration by KEI). These pictures aren't covered by the GPL.

CHUNITHM and all related names, characters and artwork belong to SEGA. Only use artwork you made yourself or have permission to use. For personal, offline use only. Don't use modified data on official arcade machines or official online services.
