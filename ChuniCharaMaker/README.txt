CHUNI CHARA MAKER
=================

Make your own CHUNITHM characters and your own option folder (like community packs),
with no Paint.NET or hand-editing XML.

START
  New here? Open Guide.html (double-click it) for a picture-by-picture guide.
  1. Install Python 3.8 or newer from https://www.python.org/downloads/
     (tick "Add python.exe to PATH"). Only needed once.
  2. Unzip this folder (right-click the zip -> Extract All). Keep it OUTSIDE bin\option.
  3. Double-click "Start Chuni Chara Maker.bat". The first run installs Pillow + NumPy
     (needs the internet once). Leave the black window open while you use the app.

TWO WAYS TO MAKE A CHARACTER
  + New character   Adds a brand-new character with its own ID (default 70000, 70010, ...).
                    Nothing in the game is replaced.
  Replace           Switch the list to "All (to replace)", pick a character, click
                    "Replace this one". Yours takes over that slot. Delete yours and the
                    original comes back.

FIRST START
  A welcome window asks for your game folder (the one with "data" and "bin", e.g.
  D:\CHUNITHM) and offers to create your own option folder. It's pre-filled as AXXX -
  rename it to whatever you like (A + 3 letters, e.g. AMYC). It shows which names are
  already used, and "Make it load last" picks a name no other folder can overwrite.
  You can rename it any time later with "Rename..." next to "Option folder".

NEW OPTION FOLDER (for a new set of characters)
  "+ New option folder" at the top makes another option folder and switches to it. Name
  it A + 3 letters (A + numbers is how official folders are named). In the same window
  you pick the folder's VERSION LABEL and GROUP: make new ones (ID + name), or use ones
  that already exist, e.g. the same label/group as your other folder. Every character
  you add there gets them. Your other folders stay as they are: type a folder's name next
  to "Option folder" and press Enter (or Load) to go back to it.
  (The first-start welcome window asks the same after it makes your first folder.)
  LOAD ORDER: while you type the name, the window shows which option folders load AFTER
  yours. The game loads option folders A->Z and the later one wins when two change the
  same thing. It lists what each of those folders changes (characters, groups, songs...).
  The name starts as one that loads LAST (after all your folders), so nothing can overwrite
  it. "Make it load last" picks such a name again if you changed it: AZZZ (the very last
  name possible), or 'AZ' + your own letters, like AZJA.
  "Check a folder" also warns when a later folder has a character with the same ID.

STEPS
  1. Game folder = the folder with "data" and "bin", click Load.
     "Option folder" = where your stuff goes (A + 3 letters).
  2. Click "+ New character" (or pick one to replace).
  3. Open image... -> your art. PNG with transparency is best. For plain backgrounds use
     "Remove background" (tolerance slider; "Undo cut" goes back).
  4. Three boxes on the image = the three game images:
        blue   Large 1080    login, transform select, skill, results
        orange Select 512    character select, in play
        green  Nameplate 128 face icon
     Drag to move, mouse wheel / corner to resize, arrow keys to nudge (hold Shift while
     dragging for small moves).
  5. Transformations: click "+ Transformation", open its image, set its name and the
     character rank that unlocks it. Up to 9.
     A new transformation's Large, Select and Nameplate boxes start exactly where the
     Base's are. After that:
       - moving or resizing a box on a TRANSFORMATION changes only that transformation;
       - moving or resizing a box on the BASE moves the same box on every transformation
         by the same amount (their own fine-tuning is kept).
     Untick "Move with the Base's boxes" on a transformation to keep it in place when the
     Base's boxes move. "Match Base" puts its boxes back exactly where the Base's are.
     If a transformation's picture is a different size, the boxes are scaled to fit it.
  6. Name + Group. "New..." next to Group makes your own group (e.g. "My Characters").
     Version label = the text shown ABOVE the group name when you get the character
     (e.g. "CHUNITHM X-VERSE-X"). Pick one of the game's, or "New..." to make your own,
     like "<your sort name>". It's applied to the character and to your own group.
     Each label has an ID, shown in the list ("90 · <your label> [AXXX]") along with the
     folder that defines it. The app recommends a free ID (90 and up - lower IDs are kept
     for future official versions) and warns if two folders use the same ID; "Move mine to N"
     renumbers yours everywhere. A new option folder asks for its own label and group.
     "Rename..." changes the text of one of your own labels (the ID stays the same).
     ONE GROUP + ONE LABEL PER FOLDER: the FIRST character in your option folder (lowest
     ID, top of the "My folder" list) decides the group and version label for every
     character in that folder.
       - Only that first character can change them. Change them there and save, and all
         your other characters in the folder get the same group + label.
       - On every other character (and on new ones) Group and Version label are locked to
         the first character's.
       - Characters that don't match yet (from before) show in red in "My folder";
         "Match them to ... now" fixes them all at once without re-saving each one.
     The very first character in an empty folder can pick any group and label.
     OFFICIAL CHARACTERS: a character from an official option folder (A + three digits,
     like A000 or A001) keeps the game's own group and version label when you replace it;
     those two fields are locked. Characters from custom option folders (A + letters,
     like AMYC) follow the rules above.
  7. Click "Add to AXXX" / "Replace character" / "Save changes". A "please wait" window
     shows while the pictures are cropped and converted to DDS; it closes by itself.
  8. Start the game. Characters are unlocked by default.

EDIT / REMOVE
  "My folder" lists everything you made. Select one -> "Edit this" (reloads your images,
  box positions and transformations exactly as you saved them; a small "One second…"
  window shows while the boxes are put back in place) or "Remove from my folder".

CHECK A FOLDER  (top right)
  Checks any option folder (yours, another one in bin\option, or a pack you downloaded):
   * DDS files that DDSImage.xml points to but that are missing or misnamed
   * images that aren't 1080 / 512 / 128
   * characters pointing at groups or images that don't exist
   * group sort lists (WorksSort.xml / WorksNameSort.xml) copied from an older game
     version - a folder's list REPLACES the game's, so old lists hide newer groups
   * folder names the game won't load
   * groups hidden by another option folder: the game only uses the group list of the
     LAST folder (A->Z) that has one, so a folder that loads later with an older list
     hides your groups. The app adds your groups to those lists whenever you save,
     and "Fix" does it too.
  "Fix" does the safe repairs (rename misnamed DDS, rebuild sort lists with every group your
  game has, add data.conf). "Copy into game..." installs a downloaded pack into bin\option.

WHAT GETS WRITTEN (bin\option\AXXX\ - your folder name)
  data.conf
  chara\charaXXXXXX\Chara.xml
  ddsImage\ddsImageXXXXXX\DDSImage.xml + _00/_01/_02 .dds   (one folder per look)
  charaWorks\charaWorksXXXXXX\CharaWorks.xml + WorksSort.xml + WorksNameSort.xml  (if you made a group)
  releaseTag\releaseTagXXXXXX\ReleaseTag.xml   (if you made your own version label)
  IDs: character 70000 -> images 70000 (base), 70001 (transformation 1), 70002 ...

  Base game files are never modified. To undo everything, delete your folder in bin\option.
  Your projects (source pictures, box positions, names) and settings are kept in
  %APPDATA%\ChuniCharaMaker (paste that into the Explorer address bar to open it), so they
  stay put when you update or move this program. If a project is missing, "Edit this"
  rebuilds the box positions from the game files instead.

NOTES
  * DDS format (top bar): BC3/DXT5 like the game's own files (default), or Uncompressed (lossless,
    4x bigger - some community packs use this). Transparent edges are colour-filled before
    compression so there are no dark/white halos.
  * Better cut-outs for busy backgrounds:  pip install rembg onnxruntime  then restart;
    an "AI cut-out" button appears.

MADE WITH AI
  This tool was made with the help of AI (Claude, by Anthropic). The code, the DDS
  encoder and this README were written by AI working from my instructions and from
  the structure of my own game files, then tested on copies of those files.
  It has not been reviewed line by line by a professional programmer and may
  contain bugs. If something looks wrong, check your files with "Check a folder..."
  and keep a backup.

DISCLAIMER
  Chuni Chara Maker is an unofficial, fan-made tool. It is not made, endorsed,
  or supported by SEGA. CHUNITHM and all related names, characters, and artwork
  are trademarks and/or copyrights of SEGA and their respective owners.

  This tool contains no game data, game files, SEGA artwork or SEGA music. It only
  reads and writes files in a game folder that you already have on your own computer.
  Don't use this tool to share or redistribute SEGA's game files.

  You are responsible for the images you use. Only use artwork you made yourself
  or have permission to use, and credit the artist (the "Illustrator" field is a
  good place for that). Don't share character packs made with art you don't have
  rights to.

  Provided "as is", without warranty of any kind. Use at your own risk. Back up
  your game folder before making changes. The author is not responsible for lost
  data, damaged files, or any other problems caused by using this tool.

  For personal, offline use only. Do not use modified data on official arcade
  machines or official online services.

LICENSE
  Chuni Chara Maker is free and open-source software under the GNU General Public
  License v3.0 or later (see LICENSE). You may use, share and change it; if you share a
  changed version, it must stay under the same license with its source code available.
  Copyright (C) 2026 Chuni Chara Maker contributors.
