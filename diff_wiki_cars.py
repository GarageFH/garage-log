"""
Diff two saved copies of the Forza Horizon 6 wiki car-list page.

Usage:
    python3 diff_wiki_cars.py old_cars.html new_cars.html

What it does:
- Parses BOTH files with the exact same logic (so differences reflect real
  data changes, not parser inconsistencies between two different scrapes).
- Identifies each car by (manufacturer, model, year) -- the same identity
  key the garage-log app itself uses -- not by raw HTML position, since
  row order can shift between scrapes even when nothing actually changed.
- Reports three categories:
    ADDED    -- present in new file, not in old (genuinely new cars)
    REMOVED  -- present in old file, not in new (rare, but worth knowing)
    CHANGED  -- same identity, but price/rarity/class/PI/availability differs
- Cars identical in every tracked field between the two files are not
  reported at all, since there's nothing to act on.

Requires: beautifulsoup4, lxml (pip install beautifulsoup4 lxml --break-system-packages)
"""

import re
import json
import sys
from bs4 import BeautifulSoup

# Multi-word manufacturer names that must be matched before falling back to
# "first word is the manufacturer". Keep this in sync with parse.py / finalize.py
# if the original parser's list ever gets extended.
MULTI_WORD_MAKES = [
    "Alfa Romeo", "Aston Martin", "Mercedes-Benz", "Mercedes-AMG", "Land Rover",
    "Rolls-Royce", "De Tomaso", "Alpine Renault", "GMC", "RUF", "Mazdaspeed",
    "Mini", "SCG", "Hot Wheels", "Mercedes", "VUHL", "W Motors", "Holden",
    "Local Motors", "American Motors", "Mitsubishi", "TVR", "Donkervoort",
    "AMG Transport Dynamics", "Alumicraft", "Ariel", "Hennessey", "Praga",
    "Vauxhall", "Wagner", "Zenvo", "Austin-Healey",
]
MULTI_WORD_MAKES.sort(key=len, reverse=True)


def split_manufacturer(name):
    for make in MULTI_WORD_MAKES:
        if name.startswith(make + " "):
            return make, name[len(make):].strip()
    parts = name.split(" ", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], ""


def parse_app_html(path):
    """Parse the CARS array directly out of the app's own garage-log.html file.
    This is the actual ground truth for 'what does the app currently have' --
    deliberately NOT a re-parse of an old wiki page, since the live app file
    may contain manual corrections (e.g. Forza Edition rarity, which the wiki
    parser can't detect automatically and has to be fixed by hand) that a
    fresh wiki-to-wiki diff would never see and would silently overwrite."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    start = content.find("const CARS = [")
    if start == -1:
        raise ValueError(f"No 'const CARS = [' found in {path} -- is this the app's HTML file?")
    i = start + len("const CARS = ")
    depth = 0
    in_string = False
    escape = False
    end = None
    for idx in range(i, len(content)):
        c = content[idx]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = idx
                break

    cars_json = content[i:end + 1]
    try:
        app_cars = json.loads(cars_json)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Could not parse the CARS array in {path} as valid JSON ({e}).\n"
            f"This usually means a manual edit introduced a syntax problem -- "
            f"common causes: a trailing comma before the closing ']', a missing "
            f"comma between two car entries, or an unescaped quote inside a "
            f"'find' value. Check the area around the reported line/column and "
            f"fix it directly in {path} before re-running this tool."
        ) from None

    normalized = []
    for c in app_cars:
        normalized.append({
            "mfr": c["mfr"],
            "model": c["model"],
            "year": c["y"],
            "price": c["p"],
            "rarity": c["r"],
            "class": c["cl"],
            "pi": c["pi"],
            "availability": c["find"],  # already the app's final find text, not raw wiki text
            "_already_app_format": True,
        })
    return normalized


def parse_wiki_html(path):
    """Parse a saved wiki car-list HTML page into a list of car dicts.
    Mirrors the original parse.py logic exactly so two scrapes are comparable."""
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table", class_="sortable")
    if not tables:
        raise ValueError(f"No sortable table found in {path} -- is this the right saved page?")
    main_table = tables[0]

    rows = main_table.find_all("tr")
    cars = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 13:
            continue  # header row

        name_cell = cells[0]
        link = name_cell.find("a")
        if not link:
            continue
        car_name = link.get("title", link.text).strip()

        name_divs = name_cell.find_all("div")
        full_title_text = name_divs[1].get_text(strip=True) if len(name_divs) > 1 else ""
        year_match = re.search(r"(19|20)\d{2}$", full_title_text)
        year = int(year_match.group()) if year_match else 0

        avail_text = ""
        if len(name_divs) > 2:
            avail_text = name_divs[2].get_text(strip=True)

        value_cell = cells[5]
        value_text = value_cell.get_text(" ", strip=True)
        cr_match = re.search(r"([\d,]+)\s*CR", value_text)
        price = int(cr_match.group(1).replace(",", "")) if cr_match else 0

        rarity_match = re.search(r"(COMMON|RARE|EPIC|LEGENDARY|UNKNOWN)", value_text)
        rarity = rarity_match.group(1) if rarity_match else "UNKNOWN"

        class_cell = cells[12]
        class_spans = class_cell.find_all("span")
        car_class = class_spans[0].get_text(strip=True) if len(class_spans) > 0 else "?"
        pi = class_spans[1].get_text(strip=True) if len(class_spans) > 1 else "?"

        mfr, model = split_manufacturer(car_name)

        cars.append({
            "mfr": mfr,
            "model": model,
            "year": year,
            "availability": avail_text,
            "price": price,
            "rarity": rarity,
            "class": car_class,
            "pi": pi,
        })

    return cars


def identity_key(car):
    """The same identity logic the garage-log app uses: manufacturer + model + year."""
    return (car["mfr"].strip().lower(), car["model"].strip().lower(), car["year"])


def resolve_find(car):
    """Returns the find text to compare/display for this car. If the car
    came from parse_app_html() (already-normalized app data), use it as-is.
    If it came from parse_wiki_html() (raw availability text), normalize it
    first. Never apply how_to_find() twice -- doing so to already-normalized
    text (e.g. 'Hard to Find') would run it back through rules meant for raw
    wiki phrasing and could silently mangle it."""
    if car.get("_already_app_format"):
        return car.get("availability", "")
    return how_to_find(car.get("availability", ""))


def fields_equal(a, b):
    """Compare the fields that matter for the app: price, rarity, class, PI,
    and the find text (resolved correctly regardless of which side is raw
    wiki data and which side is already-normalized app data).

    Two deliberate exceptions, both covering "placeholder becomes real data"
    rather than an actual change to something the game already had:

    1. Price: 0 means "unknown/unbuyable" in this dataset (DLC-locked cars
       the wiki hasn't priced yet, etc). 0 -> a real number is the wiki
       filling in previously-missing info, not a price change to warn about.
       A real number -> a DIFFERENT real number is still a genuine change.

    2. Rarity: the wiki parser can't detect Forza Edition rarity from the
       raw page text (it only recognizes COMMON/RARE/EPIC/LEGENDARY/UNKNOWN),
       so every FE car parses as UNKNOWN from the wiki side even though the
       app correctly has FORZAEDITION (set by a one-time manual correction).
       A wiki-side UNKNOWN should never override a more specific app-side
       rarity -- that's a parser limitation, not a real change."""
    a_price, b_price = a.get("price"), b.get("price")
    if a_price != b_price:
        if not (a_price == 0 or b_price == 0):
            return False

    if a.get("class") != b.get("class"):
        return False
    if a.get("pi") != b.get("pi"):
        return False

    a_rarity, b_rarity = a.get("rarity"), b.get("rarity")
    if a_rarity != b_rarity:
        if not (a_rarity == "UNKNOWN" or b_rarity == "UNKNOWN"):
            return False

    if resolve_find(a) != resolve_find(b):
        return False
    return True


def diff_describe(a, b):
    """Human-readable list of which specific fields differ. Mirrors the same
    placeholder-to-real-data exceptions as fields_equal, so the displayed
    diff list never contradicts what fields_equal decided was worth flagging."""
    diffs = []

    a_price, b_price = a.get("price"), b.get("price")
    if a_price != b_price and not (a_price == 0 or b_price == 0):
        diffs.append(f"Price: {a_price!r} -> {b_price!r}")

    for key, label in [("class", "Class"), ("pi", "PI")]:
        if a.get(key) != b.get(key):
            diffs.append(f"{label}: {a.get(key)!r} -> {b.get(key)!r}")

    a_rarity, b_rarity = a.get("rarity"), b.get("rarity")
    if a_rarity != b_rarity and not (a_rarity == "UNKNOWN" or b_rarity == "UNKNOWN"):
        diffs.append(f"Rarity: {a_rarity!r} -> {b_rarity!r}")

    old_find = resolve_find(a)
    new_find = resolve_find(b)
    if old_find != new_find:
        diffs.append(f"How to find: {old_find!r} -> {new_find!r}")
    return diffs


def how_to_find(avail):
    """
    Mirrors finalize.py's how_to_find() exactly. Returns '' if the car is
    plainly buyable from the Autoshow with no real gate (Autoshow alone, or
    Autoshow + Wheelspin/Aftermarket as bonus routes). Otherwise returns a
    short tag describing the actual unlock requirement -- this is what the
    app's 'find' field actually stores, NOT the raw wiki availability text.
    """
    a = avail.strip()

    has_autoshow = a.startswith('Autoshow')

    if has_autoshow:
        rest = a[len('Autoshow'):].lstrip(', ').strip()
        if rest == '':
            return ''  # plain autoshow
        if 'DLC' in rest:
            dlc_match = re.search(r'DLC:\s*([^)]+)\)', rest)
            dlc_name = dlc_match.group(1).strip() if dlc_match else 'DLC'
            return f'Requires {dlc_name}'
        if 'Promotional' in rest:
            promo_match = re.search(r'Promotional:\s*([^)]+)\)', rest)
            promo_name = promo_match.group(1).strip() if promo_match else 'Promotional'
            return f'Promo: {promo_name}'
        if 'Complete the Prologue' in rest:
            return 'Complete the Prologue'
        if 'Collection Journal' in rest:
            cat_match = re.search(r'"([^"]+)"', rest)
            pts_match = re.search(r'Earn ([\d,]+) points', rest)
            cat = cat_match.group(1) if cat_match else 'Collection Journal'
            pts = pts_match.group(1) if pts_match else '?'
            return f'Journal: {pts} pts in "{cat}"'
        if 'Wristband' in rest or 'wristband' in rest:
            wb_match = re.search(r'Earn the (\w+) [Ww]ristband', rest)
            color = wb_match.group(1) if wb_match else ''
            return f'{color} Wristband'.strip()
        if rest.startswith('Wheelspin') or rest.startswith('Aftermarket Car'):
            tokens = [t.strip() for t in rest.split(',')]
            bonus_only = all(
                t == 'Wheelspin' or t.startswith('Aftermarket Car')
                for t in tokens
            )
            if bonus_only:
                return ''  # still buyable normally, these are just extra routes
        return rest[:60]

    if a == 'Wheelspin':
        return 'Wheelspin only'
    if a.startswith('Barn Find'):
        loc_match = re.search(r'Barn Find:\s*(.+)', a)
        loc = loc_match.group(1).strip() if loc_match else ''
        return f'Barn Find ({loc})' if loc else 'Barn Find'
    if a.startswith('Treasure Car'):
        loc_match = re.search(r'Treasure Car:\s*(.+)', a)
        loc = loc_match.group(1).strip() if loc_match else ''
        return f'Treasure Car ({loc})' if loc else 'Treasure Car'
    if a.startswith('Car Mastery'):
        target_match = re.search(r'Car Mastery:\s*(.+)', a)
        target = target_match.group(1).strip() if target_match else ''
        return f'Car Mastery ({target})' if target else 'Car Mastery reward'
    if a.startswith('Gifted'):
        dlc_match = re.search(r'DLC:\s*([^)]+)\)', a)
        if dlc_match:
            return f'Gifted ({dlc_match.group(1).strip()})'
        return 'Gifted'
    if 'Hard to Find' in a:
        return 'Hard to Find'
    if a.startswith('Earn') and 'Collection Journal' in a:
        cat_match = re.search(r'"([^"]+)"', a)
        pts_match = re.search(r'Earn ([\d,]+) points', a)
        cat = cat_match.group(1) if cat_match else 'Collection Journal'
        pts = pts_match.group(1) if pts_match else '?'
        return f'Journal: {pts} pts in "{cat}"'
    if 'Wristband' in a or 'wristband' in a:
        wb_match = re.search(r'Earn the (\w+) [Ww]ristband', a)
        color = wb_match.group(1) if wb_match else ''
        return f'{color} Wristband'.strip()
    if a == '' or a == 'Unobtainable':
        return 'Unobtainable'
    return a[:60]


def to_app_format(car):
    """Convert a car dict (from either parse_app_html or parse_wiki_html)
    into the exact JSON line the app's CARS array uses. Uses resolve_find()
    so already-normalized app data isn't run through how_to_find() a second
    time."""
    app_car = {
        "mfr": car["mfr"],
        "model": car["model"],
        "y": car["year"] if car["year"] is not None else 0,
        "p": car["price"],
        "r": car["rarity"],
        "cl": car["class"],
        "pi": car["pi"],
        "find": resolve_find(car),
    }
    return "  " + json.dumps(app_car, ensure_ascii=False) + ","


def app_identity_line(wiki_car):
    """A short identity string matching how the app names a car, for locating
    a CHANGED car's existing line inside CARS via text search."""
    mfr = wiki_car["mfr"]
    model = wiki_car["model"]
    return f'"mfr": "{mfr}", "model": "{model}"'


def find_cars_array_bounds(content):
    """Locate the exact start/end character offsets of the CARS array literal
    inside the app's HTML, using bracket-depth counting (not regex) so it's
    robust to any nested brackets inside string values."""
    start = content.find("const CARS = [")
    if start == -1:
        raise ValueError("No 'const CARS = [' found -- is this the app's HTML file?")
    i = start + len("const CARS = ")
    depth = 0
    in_string = False
    escape = False
    end = None
    for idx in range(i, len(content)):
        c = content[idx]
        if escape:
            escape = False
            continue
        if c == "\\" and in_string:
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                end = idx
                break
    if end is None:
        raise ValueError("Could not find the matching closing bracket for CARS array")
    return i, end  # content[i] == '[', content[end] == ']'


def apply_patch(app_path, added_cars, changed_pairs, out_path):
    """Writes out_path as a copy of app_path with ADDED cars inserted and
    CHANGED cars' lines replaced in-place. REMOVED cars are deliberately
    left untouched -- deleting a car's line is destructive (it would also
    orphan any owned count/rating/notes for it) and is left for the user
    to decide and do by hand, exactly as the printed report already says.

    Returns (success: bool, messages: list[str]) -- if any expected old line
    for a CHANGED car can't be found verbatim in the file (meaning the file
    has drifted from what was parsed, e.g. it was hand-edited again since
    parsing), that one replacement is skipped and reported, rather than
    silently applying a different line than intended."""
    with open(app_path, "r", encoding="utf-8") as f:
        content = f.read()

    messages = []

    # apply CHANGED replacements first, on the raw content, before touching
    # the array boundaries for insertion (insertion happens once at the end)
    for k, old_c, new_c in changed_pairs:
        old_line = to_app_format(old_c).strip()
        new_line = to_app_format(new_c).strip()
        count = content.count(old_line)
        if count == 0:
            messages.append(
                f"SKIPPED (not found verbatim, needs manual review): "
                f"{old_c['mfr']} {old_c['model']} ({old_c['year']})"
            )
            continue
        if count > 1:
            messages.append(
                f"SKIPPED (matched {count} times, ambiguous -- needs manual review): "
                f"{old_c['mfr']} {old_c['model']} ({old_c['year']})"
            )
            continue
        content = content.replace(old_line, new_line)
        messages.append(f"Applied: {old_c['mfr']} {old_c['model']} ({old_c['year']}) -- updated")

    # insert ADDED cars right after the array's opening bracket
    if added_cars:
        start, end = find_cars_array_bounds(content)
        insertion_point = start + 1  # right after the '['
        new_lines = "\n" + "\n".join(to_app_format(c) for c in added_cars)
        content = content[:insertion_point] + new_lines + content[insertion_point:]
        for c in added_cars:
            messages.append(f"Added: {c['mfr']} {c['model']} ({c['year']})")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    # sanity-check the result actually parses before calling it a success
    try:
        verify_cars = parse_app_html(out_path)
        ok = True
    except Exception as e:
        messages.append(f"WARNING: patched file failed to re-parse cleanly: {e}")
        ok = False

    return ok, messages


def main():
    if len(sys.argv) != 4:
        print("Usage: python3 diff_wiki_cars.py garage-log-v10.html new_wiki_page.html garage-log-v11.html")
        print()
        print("  garage-log-v10.html -- your CURRENT app file (the one currently on GitHub)")
        print("  new_wiki_page.html  -- a freshly-saved copy of the wiki car list page")
        print("  garage-log-v11.html -- where to write the PATCHED app file")
        print()
        print("This compares the wiki's CURRENT data against what your app file ACTUALLY")
        print("has right now -- not against an old wiki snapshot -- so any manual fixes")
        print("you've made directly in the app file (e.g. Forza Edition rarity, which the")
        print("wiki page itself doesn't label) are correctly treated as the current truth")
        print("and won't be silently overwritten or mismatched.")
        print()
        print("New cars are inserted automatically. Changed cars are updated automatically")
        print("(price/rarity/class/PI/find). Cars no longer on the wiki are NEVER deleted")
        print("automatically -- deleting is destructive (loses owned counts/notes for that")
        print("car) and is left for you to review and do by hand if you actually want it.")
        sys.exit(1)

    app_path, new_wiki_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

    print(f"Parsing your CURRENT app file: {app_path}")
    old_cars = parse_app_html(app_path)
    print(f"  -> {len(old_cars)} cars currently in the app")

    print(f"Parsing the NEW wiki page: {new_wiki_path}")
    new_cars = parse_wiki_html(new_wiki_path)
    print(f"  -> {len(new_cars)} cars on the wiki now")
    print()

    old_by_key = {identity_key(c): c for c in old_cars}
    new_by_key = {identity_key(c): c for c in new_cars}

    old_keys = set(old_by_key.keys())
    new_keys = set(new_by_key.keys())

    added_keys = new_keys - old_keys
    removed_keys = old_keys - new_keys
    common_keys = old_keys & new_keys

    changed = []
    for k in common_keys:
        if not fields_equal(old_by_key[k], new_by_key[k]):
            changed.append((k, old_by_key[k], new_by_key[k]))

    known_manufacturers = set(c["mfr"] for c in old_cars)

    print("=" * 60)
    print(f"ADDED ({len(added_keys)}) -- new cars not previously in your list:")
    print("=" * 60)
    if not added_keys:
        print("  (none)")
    for k in sorted(added_keys):
        c = new_by_key[k]
        line = f"  + {c['mfr']} {c['model']} ({c['year']}) -- {c['rarity']}, {c['class']}{c['pi']}, {c['price']:,} CR"
        if c['mfr'] not in known_manufacturers:
            line += "   [NEW MANUFACTURER -- double-check this mfr/model split is right]"
        print(line)

    print()
    print("=" * 60)
    print(f"REMOVED ({len(removed_keys)}) -- in your app, but the wiki no longer lists them:")
    print("=" * 60)
    if not removed_keys:
        print("  (none)")
    for k in sorted(removed_keys):
        c = old_by_key[k]
        print(f"  - {c['mfr']} {c['model']} ({c['year']})")

    print()
    print("=" * 60)
    print(f"CHANGED ({len(changed)}) -- same car, different data:")
    print("=" * 60)
    if not changed:
        print("  (none)")
    for k, old_c, new_c in sorted(changed):
        print(f"  ~ {old_c['mfr']} {old_c['model']} ({old_c['year']})")
        for d in diff_describe(old_c, new_c):
            print(f"      {d}")

    # write a machine-readable summary too, for handing back to Claude or
    # feeding into another script without re-parsing the HTML
    summary = {
        "added": [new_by_key[k] for k in sorted(added_keys)],
        "removed": [old_by_key[k] for k in sorted(removed_keys)],
        "changed": [
            {"old": old_by_key[k], "new": new_by_key[k]}
            for k, _, _ in sorted(changed)
        ],
    }
    summary_json_path = "wiki_car_diff.json"
    with open(summary_json_path, "w") as f:
        json.dump(summary, f, indent=2)
    print()
    print(f"Full machine-readable diff written to {summary_json_path}")

    # --- Patch text: exactly what to paste into the app's HTML, and where ---
    patch_lines = []
    patch_lines.append("=" * 70)
    patch_lines.append("PATCH FOR garage-log.html")
    patch_lines.append("=" * 70)
    patch_lines.append("")
    patch_lines.append("WHERE TO ADD THIS:")
    patch_lines.append('  Open garage-log.html and find the line that says:  const CARS = [')
    patch_lines.append("  Paste the lines below directly under that line (as new lines,")
    patch_lines.append("  before the first existing car entry). Each line is one complete")
    patch_lines.append("  car -- you can paste them in any order, anywhere inside the")
    patch_lines.append("  CARS [ ... ] array, as long as each line ends with a comma")
    patch_lines.append("  (matching every other line in that array).")
    patch_lines.append("")

    if added_keys:
        patch_lines.append(f"--- {len(added_keys)} NEW CAR LINE(S) TO ADD ---")
        patch_lines.append("")
        for k in sorted(added_keys):
            c = new_by_key[k]
            patch_lines.append(f"  // New: {c['mfr']} {c['model']} ({c['year']})")
            patch_lines.append(to_app_format(c))
        patch_lines.append("")
    else:
        patch_lines.append("--- No new cars to add ---")
        patch_lines.append("")

    if changed:
        patch_lines.append(f"--- {len(changed)} EXISTING LINE(S) TO FIND AND REPLACE ---")
        patch_lines.append("")
        patch_lines.append("For each one below: search the HTML file for the OLD line shown")
        patch_lines.append("(use your editor's Find feature with the mfr/model text), then")
        patch_lines.append("replace that entire line with the NEW line shown directly under it.")
        patch_lines.append("")
        for k, old_c, new_c in sorted(changed):
            patch_lines.append(f"  // {old_c['mfr']} {old_c['model']} ({old_c['year']}) -- search for this text to find it:")
            patch_lines.append(f'  //   "mfr": "{old_c["mfr"]}", "model": "{old_c["model"]}"')
            patch_lines.append("  // FIND (old line):")
            patch_lines.append("  " + to_app_format(old_c).strip())
            patch_lines.append("  // REPLACE WITH (new line):")
            patch_lines.append(to_app_format(new_c))
            patch_lines.append("")
    else:
        patch_lines.append("--- No existing cars changed ---")
        patch_lines.append("")

    if removed_keys:
        patch_lines.append(f"--- {len(removed_keys)} CAR(S) NO LONGER ON THE WIKI ---")
        patch_lines.append("")
        patch_lines.append("These are rare -- the wiki no longer lists them. Decide for yourself")
        patch_lines.append("whether to delete their line from CARS (this would also discard any")
        patch_lines.append("owned count / rating / notes you have for them, unless you've already")
        patch_lines.append("set up the tombstone-aware export/import flow). No line is auto-deleted")
        patch_lines.append("by this tool -- this is just a list to review:")
        patch_lines.append("")
        for k in sorted(removed_keys):
            c = old_by_key[k]
            patch_lines.append(f"  - {c['mfr']} {c['model']} ({c['year']})")
        patch_lines.append("")

    patch_text = "\n".join(patch_lines)
    patch_out_path = "patch_for_app.txt"
    with open(patch_out_path, "w", encoding="utf-8") as f:
        f.write(patch_text)

    print(f"Ready-to-paste patch instructions written to {patch_out_path}")
    print()
    print(patch_text)

    # --- Auto-apply: actually write the patched file ---
    print()
    print("=" * 70)
    print(f"AUTO-APPLYING PATCH -> {out_path}")
    print("=" * 70)

    added_cars_list = [new_by_key[k] for k in sorted(added_keys)]
    changed_pairs_list = [(k, old_by_key[k], new_by_key[k]) for k, _, _ in sorted(changed)]

    if not added_cars_list and not changed_pairs_list:
        print("Nothing to auto-apply (no additions or changes detected).")
        print(f"Copying {app_path} to {out_path} unchanged.")
        with open(app_path, "r", encoding="utf-8") as f:
            content = f.read()
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        ok, messages = apply_patch(app_path, added_cars_list, changed_pairs_list, out_path)
        for m in messages:
            print(f"  {m}")
        print()
        if ok:
            verify_count = len(parse_app_html(out_path))
            print(f"SUCCESS: {out_path} written and re-parses cleanly ({verify_count} cars).")
        else:
            print(f"WARNING: {out_path} was written but failed to re-parse cleanly.")
            print("Do not upload this file as-is -- check it by hand before using it.")

    if removed_keys:
        print()
        print(f"NOTE: {len(removed_keys)} car(s) are no longer on the wiki but were NOT")
        print("removed from the file (deleting is destructive and left to your judgment --")
        print("see the REMOVED section above and in patch_for_app.txt).")


if __name__ == "__main__":
    main()
