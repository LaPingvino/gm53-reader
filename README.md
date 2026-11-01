# gm53-reader

Reads games made with **Game Maker 5.3 / 5.3a** (project format 530) back out of their `.exe`, and turns them into
files you can read: every object's events and code, the rooms, sprites, backgrounds, sounds, timelines, scripts
and settings.

Game Maker 5.3a executables were long thought unrecoverable: their game data is encrypted, and the decompilers
for later versions don't read them. This reader was written to get back the lost sources of two 2006 Esperanto
games, [Stelo](https://lapingvino.itch.io/) and Pacmanio, and reads both completely.

## Use

Python 3 and [Pillow](https://python-pillow.org) (for images):

```sh
python3 -I gm53_reader.py GAME.exe out/     # reads the game into out/project.json, sprites/, sounds/, ...
python3 -I gm53_export.py out/              # writes readable files next to them
```

You get:

| | |
|---|---|
| `project.json` | the whole project: settings, resources, objects with their actions, rooms with their instances |
| `objects/*.gml` | each object's events, drag-and-drop actions shown as function calls, code as written |
| `timelines/*.gml`, `scripts/*.gml` | timelines and scripts |
| `rooms/*.json`, `*.png`, `*.txt` | each room's instances, the room drawn with the game's own sprites, and a 32 px grid as text |
| `sprites/`, `backgrounds/`, `sounds/`, `datafiles/` | the game's own images (PNG), sounds and data files |
| `game.ico`, `game_information.rtf`, `sprites_contact.png` | the icon, the help text, and every sprite frame on one sheet |

`--trace` on the reader prints where in the file each part is read, to help with games it doesn't read to the end.

## How it works

At offset 1,500,000 of the executable is the marker `1230500` and a 32-bit seed. Every byte after them is
substituted through a table made from that seed:

```
t = identity(256)
for i in 1..10000: j = 1 + (i * seed) % 254; swap t[j], t[j+1]
```

and the data is read through the inverse of that table. The result holds the usual Game Maker project
(`1234321`, version `530`), laid out as a 5.3a `.gmd` file; images and sounds are zlib blocks inside it.

The layout of the project was learned by reading LateralGM's `GmFileReader` and notes on the GM4-era cipher;
no code from them is used.

## Limits

- Only version 530 (Game Maker 5.3 and 5.3a). Other versions stop with an error.
- A few kilobytes at the end of each game tried so far aren't read yet; they are probably the resource tree's
  folders. Everything the game needs to run comes before them.
- The `.gml` files are for reading; they aren't a project Game Maker can open again.

## License

MIT, see [LICENSE](LICENSE).
