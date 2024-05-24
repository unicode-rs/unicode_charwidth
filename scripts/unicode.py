#!/usr/bin/env python3
#
# Copyright 2011-2022 The Rust Project Developers. See the COPYRIGHT
# file at the top-level directory of this distribution and at
# http://rust-lang.org/COPYRIGHT.
#
# Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
# http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
# <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
# option. This file may not be copied, modified, or distributed
# except according to those terms.

# This script uses the following Unicode tables:
#
# - DerivedCoreProperties.txt
# - EastAsianWidth.txt
# - HangulSyllableType.txt
# - NormalizationTest.txt (for tests only)
# - PropList.txt
# - ReadMe.txt
# - Scripts.txt
# - UnicodeData.txt
# - emoji/emoji-data.txt
# - emoji/emoji-variation-sequences.txt
# - extracted/DerivedGeneralCategory.txt
#
# Since this should not require frequent updates, we just store this
# out-of-line and check the generated module into git.

import enum
import math
import operator
import os
import re
import sys
import urllib.request
from collections import defaultdict
from itertools import batched
from typing import Callable, Iterable

UNICODE_VERSION = "15.1.0"
"""The version of the Unicode data files to download."""

NUM_CODEPOINTS = 0x110000
"""An upper bound for which `range(0, NUM_CODEPOINTS)` contains Unicode's codespace."""

MAX_CODEPOINT_BITS = math.ceil(math.log2(NUM_CODEPOINTS - 1))
"""The maximum number of bits required to represent a Unicode codepoint."""


class OffsetType(enum.IntEnum):
    """Represents the data type of a lookup table's offsets. Each variant's value represents the
    number of bits required to represent that variant's type."""

    U2 = 2
    """Offsets are 2-bit unsigned integers, packed four-per-byte."""
    U4 = 4
    """Offsets are 4-bit unsigned integers, packed two-per-byte."""
    U8 = 8
    """Each offset is a single byte (u8)."""


MODULE_PATH = "../src/tables.rs"
"""The path of the emitted Rust module (relative to the working directory)"""

TABLE_SPLITS = [7, 13]
"""The splits between the bits of the codepoint used to index each subtable.
Adjust these values to change the sizes of the subtables"""

Codepoint = int
BitPos = int


def fetch_open(filename: str, local_prefix: str = ""):
    """Opens `filename` and return its corresponding file object. If `filename` isn't on disk,
    fetches it from `https://www.unicode.org/Public/`. Exits with code 1 on failure.
    """
    basename = os.path.basename(filename)
    localname = os.path.join(local_prefix, basename)
    if not os.path.exists(localname):
        urllib.request.urlretrieve(
            f"https://www.unicode.org/Public/{UNICODE_VERSION}/ucd/{filename}",
            localname,
        )
    try:
        return open(localname, encoding="utf-8")
    except OSError:
        sys.stderr.write(f"cannot load {localname}")
        sys.exit(1)


def load_unicode_version() -> tuple[int, int, int]:
    """Returns the current Unicode version by fetching and processing `ReadMe.txt`."""
    with fetch_open("ReadMe.txt") as readme:
        pattern = r"for Version (\d+)\.(\d+)\.(\d+) of the Unicode"
        return tuple(map(int, re.search(pattern, readme.read()).groups()))  # type: ignore


def load_property(filename: str, pattern: str, action: Callable[[int], None]):
    with fetch_open(filename) as properties:
        single = re.compile(rf"^([0-9A-F]+)\s*;\s*{pattern}\s+")
        multiple = re.compile(rf"^([0-9A-F]+)\.\.([0-9A-F]+)\s*;\s*{pattern}\s+")

        for line in properties.readlines():
            raw_data = None  # (low, high)
            if match := single.match(line):
                raw_data = (match.group(1), match.group(1))
            elif match := multiple.match(line):
                raw_data = (match.group(1), match.group(2))
            else:
                continue
            low = int(raw_data[0], 16)
            high = int(raw_data[1], 16)
            for cp in range(low, high + 1):
                action(cp)


def to_sorted_ranges(iter: Iterable[Codepoint]) -> list[tuple[Codepoint, Codepoint]]:
    "Creates a sorted list of ranges from an iterable of codepoints"
    lst = [c for c in iter]
    lst.sort()
    ret = []
    for cp in lst:
        if len(ret) > 0 and ret[-1][1] == cp - 1:
            ret[-1] = (ret[-1][0], cp)
        else:
            ret.append((cp, cp))
    return ret


class EastAsianWidth(enum.IntEnum):
    """Represents the width of a Unicode character according to UAX 16.
    All East Asian Width classes resolve into either
    `EffectiveWidth.NARROW`, `EffectiveWidth.WIDE`, or `EffectiveWidth.AMBIGUOUS`.
    """

    NARROW = 1
    """ One column wide. """
    WIDE = 2
    """ Two columns wide. """
    AMBIGUOUS = 3
    """ Two columns wide in a CJK context. One column wide in all other contexts. """


class CharWidthInTable(enum.IntEnum):
    """Represents the width of a Unicode character
    as stored in the tables."""

    ZERO = 0
    ONE = 1
    TWO = 2
    SPECIAL = 3


class CharWidth(enum.IntEnum):
    """The integer values of these variants have special meaning:
    - Top bit: whether this is Vs16
    - 2nd from top: whether this is Vs15
    - 3rd from top: whether this is unaffected by ligature-transparent
    - 4th bit: if 3rd is set but this one is not, then this is a ZWJ ligature state
      where no ZWJ has been encountered yet; encountering one flips this on"""

    # BASIC WIDTHS

    ZERO = 0x100
    "Zero columns wide."

    NARROW = 0x101
    "One column wide."

    WIDE = 0x102
    "Two columns wide."

    # TIGHTLY DEFINED SEQUENCES

    # \r\n
    LINE_FEED = 0b0000_0011
    "\\n (CRLF has width 1)"

    # Emoji skintone modifiers
    EMOJI_MODIFIER = 0b0000_0100
    "`Emoji_Modifier`"

    # Emoji ZWJ sequences

    REGIONAL_INDICATOR = 0b0000_0101
    "`Regional_Indicator` (for ZWJ sequences)"

    EMOJI_PRESENTATION = 0b0000_0110
    "`Emoji_Presentation`"

    # VARIATION SELECTORS

    # Text presentation sequences (not CJK)
    VARIATION_SELECTOR_15 = 0b0100_0000
    "\\uFE0E (text presentation sequences)"

    # Emoji presentation sequences
    VARIATION_SELECTOR_16 = 0b1000_0000
    "\\uFE0F (emoji presentation sequences)"

    # --- Width modes below this line can have 1 of their top 2 bits set to indicate presence of a VS ---

    # ARABIC LAM ALEF

    JOINING_GROUP_ALEF = 0b0000_1111
    "Joining_Group=Alef (Arabic Lam-Alef ligature)"

    # COMBINING SOLIDUS (CJK only)

    COMBINING_LONG_SOLIDUS_OVERLAY = 0b0011_1111
    "\\u0338 (CJK only, makes <, =, > width 2)"

    # SOLIDUS + ALEF (solidus is Joining_Type=Transparent)
    SOLIDUS_OVERLAY_ALEF = 0b0010_1111
    "\\u0338 followed by Joining_Group=Alef"

    # SCRIPT ZWJ LIGATURES

    # Hebrew alef lamed

    HEBREW_LETTER_LAMED = 0b0010_0000
    "\\u05DC (Alef-ZWJ-Lamed ligature)"

    ZWJ_HEBREW_LETTER_LAMED = 0b0011_0000
    "\\u200D\\u05DC (Alef-ZWJ-Lamed ligature)"

    # Buginese <a -i> ya

    BUGINESE_LETTER_YA = 0b0010_0001
    "\\u1A10 (<a, -i> + ya ligature)"

    ZWJ_BUGINESE_LETTER_YA = 0b0011_0001
    "\\u200D\\u1A10 (<a, -i> + ya ligature)"

    BUGINESE_VOWEL_SIGN_I_ZWJ_LETTER_YA = 0b0011_0010
    "\\u1A17\\u200D\\u1A10 (<a, -i> + ya ligature)"

    # Tifinagh bi-consonants

    TIFINAGH_CONSONANT = 0b0010_0011
    "\\u2D31..=\\u2D65 or \\u2D6F (joined by ZWJ or \\u2D7F TIFINAGH CONSONANT JOINER)"

    ZWJ_TIFINAGH_CONSONANT = 0b0011_0011
    "ZWJ then \\u2D31..=\\u2D65 or \\u2D6F"

    TIFINAGH_JOINER_CONSONANT = 0b0011_0100
    "\\u2D7F then \\u2D31..=\\u2D65 or \\u2D6F"

    # Lisu tone letters
    LISU_TONE_LETTER_MYA_NA_JEU = 0b0011_0101
    "\\uA4FC or \\uA4FD (https://www.unicode.org/versions/Unicode15.0.0/ch18.pdf#G42078)"

    # Old Turkik orkhon ec - orkhon i

    OLD_TURKIC_LETTER_ORKHON_I = 0b0010_0110
    "\\u10C03 (ORKHON EC-ZWJ-ORKHON I ligature)"

    ZWJ_OLD_TURKIC_LETTER_ORKHON_I = 0b0011_0110
    "\\u10C03 (ORKHON EC-ZWJ-ORKHON I ligature)"

    def table_width(self) -> CharWidthInTable:
        "The width of a character as stored in the lookup tables."
        match self:
            case CharWidth.ZERO:
                return CharWidthInTable.ZERO
            case CharWidth.NARROW:
                return CharWidthInTable.ONE
            case CharWidth.WIDE:
                return CharWidthInTable.TWO
            case _:
                return CharWidthInTable.SPECIAL

    def width_alone(self) -> int:
        "The width of a character with this type when it appears alone."
        match self:
            case (
                CharWidth.ZERO
                | CharWidth.COMBINING_LONG_SOLIDUS_OVERLAY
                | CharWidth.VARIATION_SELECTOR_15
                | CharWidth.VARIATION_SELECTOR_16
            ):
                return 0
            case (
                CharWidth.WIDE | CharWidth.EMOJI_MODIFIER | CharWidth.EMOJI_PRESENTATION
            ):
                return 2
            case _:
                return 1


assert len(set([v.value for v in CharWidth])) == len([v.value for v in CharWidth])


def load_east_asian_widths() -> list[EastAsianWidth]:
    """Return a list of effective widths, indexed by codepoint.
    Widths are determined by fetching and parsing `EastAsianWidth.txt`.

    `Neutral`, `Narrow`, and `Halfwidth` characters are assigned `EffectiveWidth.NARROW`.

    `Wide` and `Fullwidth` characters are assigned `EffectiveWidth.WIDE`.

    `Ambiguous` characters are assigned `EffectiveWidth.AMBIGUOUS`."""

    with fetch_open("EastAsianWidth.txt") as eaw:
        # matches a width assignment for a single codepoint, i.e. "1F336;N  # ..."
        single = re.compile(r"^([0-9A-F]+)\s*;\s*(\w+) +# (\w+)")
        # matches a width assignment for a range of codepoints, i.e. "3001..3003;W  # ..."
        multiple = re.compile(r"^([0-9A-F]+)\.\.([0-9A-F]+)\s*;\s*(\w+) +# (\w+)")
        # map between width category code and condensed width
        width_codes = {
            **{c: EastAsianWidth.NARROW for c in ["N", "Na", "H"]},
            **{c: EastAsianWidth.WIDE for c in ["W", "F"]},
            "A": EastAsianWidth.AMBIGUOUS,
        }

        width_map = []
        current = 0
        for line in eaw.readlines():
            raw_data = None  # (low, high, width)
            if match := single.match(line):
                raw_data = (match.group(1), match.group(1), match.group(2))
            elif match := multiple.match(line):
                raw_data = (match.group(1), match.group(2), match.group(3))
            else:
                continue
            low = int(raw_data[0], 16)
            high = int(raw_data[1], 16)
            width = width_codes[raw_data[2]]

            assert current <= high
            while current <= high:
                # Some codepoints don't fall into any of the ranges in EastAsianWidth.txt.
                # All such codepoints are implicitly given Neural width (resolves to narrow)
                width_map.append(EastAsianWidth.NARROW if current < low else width)
                current += 1

        while len(width_map) < NUM_CODEPOINTS:
            # Catch any leftover codepoints and assign them implicit Neutral/narrow width.
            width_map.append(EastAsianWidth.NARROW)

    # Characters from alphabetic scripts are narrow
    load_property(
        "Scripts.txt",
        r"(?:Latin|Greek|Cyrillic)",
        lambda cp: (
            operator.setitem(width_map, cp, EastAsianWidth.NARROW)
            if width_map[cp] == EastAsianWidth.AMBIGUOUS
            and not (0x2160 <= cp <= 0x217F)  # Roman numerals remain ambiguous
            else None
        ),
    )

    # Ambiguous `Modifier_Symbol`s are narrow
    load_property(
        "extracted/DerivedGeneralCategory.txt",
        "Sk",
        lambda cp: (
            operator.setitem(width_map, cp, EastAsianWidth.NARROW)
            if width_map[cp] == EastAsianWidth.AMBIGUOUS
            else None
        ),
    )

    # GREEK ANO TELEIA: NFC decomposes to U+00B7 MIDDLE DOT
    width_map[0x0387] = EastAsianWidth.AMBIGUOUS

    # Canonical equivalence for symbols with stroke
    with fetch_open("UnicodeData.txt") as udata:
        single = re.compile(r"([0-9A-Z]+);.*?;.*?;.*?;.*?;([0-9A-Z]+) 0338;")
        for line in udata.readlines():
            if match := single.match(line):
                composed = int(match.group(1), 16)
                decomposed = int(match.group(2), 16)
                if width_map[decomposed] == EastAsianWidth.AMBIGUOUS:
                    width_map[composed] = EastAsianWidth.AMBIGUOUS

    return width_map


def load_zero_widths() -> list[bool]:
    """Returns a list `l` where `l[c]` is true if codepoint `c` is considered a zero-width
    character. `c` is considered a zero-width character if

    - it has the `Default_Ignorable_Code_Point` property (determined from `DerivedCoreProperties.txt`),
    - or if it has the `Grapheme_Extend` property (determined from `DerivedCoreProperties.txt`),
    - or if it one of eight characters that should be `Grapheme_Extend` but aren't due to a Unicode spec bug,
    - or if it has a `Hangul_Syllable_Type` of `Vowel_Jamo` or `Trailing_Jamo` (determined from `HangulSyllableType.txt`).
    """

    zw_map = [False] * NUM_CODEPOINTS

    # `Default_Ignorable_Code_Point`s also have 0 width:
    # https://www.unicode.org/faq/unsup_char.html#3
    # https://www.unicode.org/versions/Unicode15.1.0/ch05.pdf#G40095
    #
    # `Grapheme_Extend` includes characters with general category `Mn` or `Me`,
    # as well as a few `Mc` characters that need to be included so that
    # canonically equivalent sequences have the same width.
    load_property(
        "DerivedCoreProperties.txt",
        r"(?:Default_Ignorable_Code_Point|Grapheme_Extend)",
        lambda cp: operator.setitem(zw_map, cp, True),
    )

    # Unicode spec bug: these should be `Grapheme_Cluster_Break=Extend`,
    # as they canonically decompose to two characters with this property,
    # but they aren't.
    for c in [0x0CC0, 0x0CC7, 0x0CC8, 0x0CCA, 0x0CCB, 0x1B3B, 0x1B3D, 0x1B43]:
        zw_map[c] = True

    # Treat `Hangul_Syllable_Type`s of `Vowel_Jamo` and `Trailing_Jamo`
    # as zero-width. This matches the behavior of glibc `wcwidth`.
    #
    # Decomposed Hangul characters consist of 3 parts: a `Leading_Jamo`,
    # a `Vowel_Jamo`, and an optional `Trailing_Jamo`. Together these combine
    # into a single wide grapheme. So we treat vowel and trailing jamo as
    # 0-width, such that only the width of the leading jamo is counted
    # and the resulting grapheme has width 2.
    #
    # (See the Unicode Standard sections 3.12 and 18.6 for more on Hangul)
    load_property(
        "HangulSyllableType.txt",
        r"(?:V|T)",
        lambda cp: operator.setitem(zw_map, cp, True),
    )

    # Syriac abbreviation mark:
    # Zero-width `Prepended_Concatenation_Mark`
    zw_map[0x070F] = True

    # Some Arabic Prepended_Concatenation_Mark`s
    # https://www.unicode.org/versions/Unicode15.0.0/ch09.pdf#G27820
    zw_map[0x0605] = True
    zw_map[0x0890] = True
    zw_map[0x0891] = True
    zw_map[0x08E2] = True

    # HANGUL CHOSEONG FILLER
    # U+115F is a `Default_Ignorable_Code_Point`, and therefore would normally have
    # zero width. However, the expected usage is to combine it with vowel or trailing jamo
    # (which are considered 0-width on their own) to form a composed Hangul syllable with
    # width 2. Therefore, we treat it as having width 2.
    zw_map[0x115F] = False

    # TIFINAGH CONSONANT JOINER
    # (invisible only when used to join two Tifinagh consonants
    zw_map[0x2D7F] = False

    # DEVANAGARI CARET
    # https://www.unicode.org/versions/Unicode15.0.0/ch12.pdf#G667447
    zw_map[0xA8FA] = True

    return zw_map


def load_width_maps() -> tuple[list[CharWidth], list[CharWidth]]:
    """Load complete width table, including characters needing special handling.
    (Returns 2 tables, one for East Asian and one for not.)"""

    eaws = load_east_asian_widths()
    zws = load_zero_widths()

    not_ea = []
    ea = []

    for eaw, zw in zip(eaws, zws):
        if zw:
            not_ea.append(CharWidth.ZERO)
            ea.append(CharWidth.ZERO)
        else:
            if eaw == EastAsianWidth.WIDE:
                not_ea.append(CharWidth.WIDE)
            else:
                not_ea.append(CharWidth.NARROW)

            if eaw == EastAsianWidth.NARROW:
                ea.append(CharWidth.NARROW)
            else:
                ea.append(CharWidth.WIDE)

    # Joining_Group=Alef (Arabic Lam-Alef ligature)
    alef_joining = []
    load_property(
        "extracted/DerivedJoiningGroup.txt",
        "Alef",
        lambda cp: alef_joining.append(cp),
    )

    # Regional indicators
    regional_indicators = []
    load_property(
        "PropList.txt",
        r"Regional_Indicator",
        lambda cp: regional_indicators.append(cp),
    )

    # Emoji modifiers
    emoji_modifiers = []
    load_property(
        "emoji/emoji-data.txt",
        r"Emoji_Modifier",
        lambda cp: emoji_modifiers.append(cp),
    )

    # Default emoji presentation (for ZWJ sequences)
    emoji_presentation = []
    load_property(
        "emoji/emoji-data.txt",
        r"Emoji_Presentation",
        lambda cp: emoji_presentation.append(cp),
    )

    for cps, width in [
        ([0x0A], CharWidth.LINE_FEED),
        ([0x05DC], CharWidth.HEBREW_LETTER_LAMED),
        (alef_joining, CharWidth.JOINING_GROUP_ALEF),
        ([0x1A10], CharWidth.BUGINESE_LETTER_YA),
        (range(0x2D31, 0x2D66), CharWidth.TIFINAGH_CONSONANT),
        ([0x2D6F], CharWidth.TIFINAGH_CONSONANT),
        ([0xA4FC], CharWidth.LISU_TONE_LETTER_MYA_NA_JEU),
        ([0xA4FD], CharWidth.LISU_TONE_LETTER_MYA_NA_JEU),
        ([0xFE0F], CharWidth.VARIATION_SELECTOR_16),
        ([0x10C03], CharWidth.OLD_TURKIC_LETTER_ORKHON_I),
        (regional_indicators, CharWidth.REGIONAL_INDICATOR),
        (emoji_modifiers, CharWidth.EMOJI_MODIFIER),
        (emoji_presentation, CharWidth.EMOJI_PRESENTATION),
    ]:
        for cp in cps:
            not_ea[cp] = width
            ea[cp] = width

    # East-Asian only
    ea[0x0338] = CharWidth.COMBINING_LONG_SOLIDUS_OVERLAY

    # Not East Asian only
    not_ea[0xFE0E] = CharWidth.VARIATION_SELECTOR_15

    return (not_ea, ea)


def load_joining_group_lam() -> list[tuple[Codepoint, Codepoint]]:
    "Returns a list of character ranges with Joining_Group=Lam"
    lam_joining = []
    load_property(
        "extracted/DerivedJoiningGroup.txt",
        "Lam",
        lambda cp: lam_joining.append(cp),
    )

    return to_sorted_ranges(lam_joining)


def load_non_transparent_zero_widths(
    width_map: list[CharWidth],
) -> list[tuple[Codepoint, Codepoint]]:
    "Returns a list of characters with zero width but not 'Joining_Type=Transparent'"

    zero_widths = set()
    for cp, width in enumerate(width_map):
        if width.width_alone() == 0:
            zero_widths.add(cp)
    transparent = set()
    load_property(
        "extracted/DerivedJoiningType.txt",
        "T",
        lambda cp: transparent.add(cp),
    )

    return to_sorted_ranges(zero_widths - transparent)


def load_ligature_transparent() -> list[tuple[Codepoint, Codepoint]]:
    """Returns a list of character ranges corresponding to all combining marks that are also
    `Default_Ignorable_Code_Point`s, plus ZWJ. This is the set of characters that won't interrupt
    a ligature."""
    default_ignorables = set()
    load_property(
        "DerivedCoreProperties.txt",
        "Default_Ignorable_Code_Point",
        lambda cp: default_ignorables.add(cp),
    )

    combining_marks = set()
    load_property(
        "extracted/DerivedGeneralCategory.txt",
        "(?:Mc|Mn|Me)",
        lambda cp: combining_marks.add(cp),
    )

    default_ignorable_combinings = default_ignorables.intersection(combining_marks)
    default_ignorable_combinings.add(0x200D)  # ZWJ

    return to_sorted_ranges(default_ignorable_combinings)


def load_solidus_transparent(
    ligature_transparents: list[tuple[Codepoint, Codepoint]],
    cjk_width_map: list[CharWidth],
) -> list[tuple[Codepoint, Codepoint]]:
    """Characters expanding to a canonical combining class above 1, plus `ligature_transparent`s from above.
    Ranges matching ones in `ligature_transparent` exactly are excluded (for compression), so it needs to bechecked also.
    """

    ccc_above_1 = set()
    load_property(
        "extracted/DerivedCombiningClass.txt",
        "(?:[2-9]|(?:[1-9][0-9]+))",
        lambda cp: ccc_above_1.add(cp),
    )

    for lo, hi in ligature_transparents:
        for cp in range(lo, hi + 1):
            ccc_above_1.add(cp)

    num_chars = len(ccc_above_1)

    # Recursive decompositions
    while True:
        with fetch_open("UnicodeData.txt") as udata:
            single = re.compile(r"([0-9A-Z]+);.*?;.*?;.*?;.*?;([0-9A-F ]+);")
            for line in udata.readlines():
                if match := single.match(line):
                    composed = int(match.group(1), 16)
                    decomposed = [int(c, 16) for c in match.group(2).split(" ")]
                    if all([c in ccc_above_1 for c in decomposed]):
                        ccc_above_1.add(composed)
        if len(ccc_above_1) == num_chars:
            break
        else:
            num_chars = len(ccc_above_1)

    for cp in ccc_above_1:
        if cp != 0xFE0F:
            assert (
                cjk_width_map[cp].table_width() != CharWidthInTable.SPECIAL
            ), f"U+{cp:X}"

    sorted = to_sorted_ranges(ccc_above_1)
    return list(filter(lambda range: range not in ligature_transparents, sorted))


def make_special_ranges(
    width_map: list[CharWidth],
) -> list[tuple[tuple[Codepoint, Codepoint], CharWidth]]:
    "Assign ranges of characters to their special behavior (used in match)"
    ret = []
    can_merge_with_prev = False
    for cp, width in enumerate(width_map):
        if width == CharWidth.EMOJI_PRESENTATION:
            can_merge_with_prev = False
        elif width.table_width() == CharWidthInTable.SPECIAL:
            if can_merge_with_prev and ret[-1][1] == width:
                ret[-1] = ((ret[-1][0][0], cp), width)
            else:
                ret.append(((cp, cp), width))
                can_merge_with_prev = True
    return ret


class Bucket:
    """A bucket contains a group of codepoints and an ordered width list. If one bucket's width
    list overlaps with another's width list, those buckets can be merged via `try_extend`.
    """

    def __init__(self):
        """Creates an empty bucket."""
        self.entry_set = set()
        self.widths = []

    def append(self, codepoint: Codepoint, width: CharWidthInTable):
        """Adds a codepoint/width pair to the bucket, and appends `width` to the width list."""
        self.entry_set.add((codepoint, width))
        self.widths.append(width)

    def try_extend(self, attempt: "Bucket") -> bool:
        """If either `self` or `attempt`'s width list starts with the other bucket's width list,
        set `self`'s width list to the longer of the two, add all of `attempt`'s codepoints
        into `self`, and return `True`. Otherwise, return `False`."""
        (less, more) = (self.widths, attempt.widths)
        if len(self.widths) > len(attempt.widths):
            (less, more) = (attempt.widths, self.widths)
        if less != more[: len(less)]:
            return False
        self.entry_set |= attempt.entry_set
        self.widths = more
        return True

    def entries(self) -> list[tuple[Codepoint, CharWidthInTable]]:
        """Return a list of the codepoint/width pairs in this bucket, sorted by codepoint."""
        result = list(self.entry_set)
        result.sort()
        return result

    def width(self) -> CharWidthInTable | None:
        """If all codepoints in this bucket have the same width, return that width; otherwise,
        return `None`."""
        if len(self.widths) == 0:
            return None
        potential_width = self.widths[0]
        for width in self.widths[1:]:
            if potential_width != width:
                return None
        return potential_width


def make_buckets(
    entries: Iterable[tuple[int, CharWidthInTable]], low_bit: BitPos, cap_bit: BitPos
) -> list[Bucket]:
    """Partitions the `(Codepoint, EffectiveWidth)` tuples in `entries` into `Bucket`s. All
    codepoints with identical bits from `low_bit` to `cap_bit` (exclusive) are placed in the
    same bucket. Returns a list of the buckets in increasing order of those bits."""
    num_bits = cap_bit - low_bit
    assert num_bits > 0
    buckets = [Bucket() for _ in range(0, 2**num_bits)]
    mask = (1 << num_bits) - 1
    for codepoint, width in entries:
        buckets[(codepoint >> low_bit) & mask].append(codepoint, width)
    return buckets


class Table:
    """Represents a lookup table. Each table contains a certain number of subtables; each
    subtable is indexed by a contiguous bit range of the codepoint and contains a list
    of `2**(number of bits in bit range)` entries. (The bit range is the same for all subtables.)

    Typically, tables contain a list of buckets of codepoints. Bucket `i`'s codepoints should
    be indexed by sub-table `i` in the next-level lookup table. The entries of this table are
    indexes into the bucket list (~= indexes into the sub-tables of the next-level table.) The
    key to compression is that two different buckets in two different sub-tables may have the
    same width list, which means that they can be merged into the same bucket.

    If no bucket contains two codepoints with different widths, calling `indices_to_widths` will
    discard the buckets and convert the entries into `EffectiveWidth` values."""

    def __init__(
        self,
        name: str,
        entry_groups: Iterable[Iterable[tuple[int, CharWidthInTable]]],
        secondary_entry_groups: Iterable[Iterable[tuple[int, CharWidthInTable]]],
        low_bit: BitPos,
        cap_bit: BitPos,
        offset_type: OffsetType,
        align: int,
        bytes_per_row: int | None = None,
        starting_indexed: list[Bucket] = [],
        cfged: bool = False,
    ):
        """Create a lookup table with a sub-table for each `(Codepoint, EffectiveWidth)` iterator
        in `entry_groups`. Each sub-table is indexed by codepoint bits in `low_bit..cap_bit`,
        and each table entry is represented in the format specified by  `offset_type`. Asserts
        that this table is actually representable with `offset_type`."""
        starting_indexed_len = len(starting_indexed)
        self.name = name
        self.low_bit = low_bit
        self.cap_bit = cap_bit
        self.offset_type = offset_type
        self.entries: list[int] = []
        self.indexed: list[Bucket] = list(starting_indexed)
        self.align = align
        self.bytes_per_row = bytes_per_row
        self.cfged = cfged

        buckets: list[Bucket] = []
        for entries in entry_groups:
            buckets.extend(make_buckets(entries, self.low_bit, self.cap_bit))

        for bucket in buckets:
            for i, existing in enumerate(self.indexed):
                if existing.try_extend(bucket):
                    self.entries.append(i)
                    break
            else:
                self.entries.append(len(self.indexed))
                self.indexed.append(bucket)

        self.primary_len = len(self.entries)
        self.primary_bucket_len = len(self.indexed)

        buckets = []
        for entries in secondary_entry_groups:
            buckets.extend(make_buckets(entries, self.low_bit, self.cap_bit))

        for bucket in buckets:
            for i, existing in enumerate(self.indexed):
                if existing.try_extend(bucket):
                    self.entries.append(i)
                    break
            else:
                self.entries.append(len(self.indexed))
                self.indexed.append(bucket)

        # Validate offset type
        max_index = 1 << int(self.offset_type)
        for index in self.entries:
            assert index < max_index, f"{index} <= {max_index}"

        self.indexed = self.indexed[starting_indexed_len:]

    def indices_to_widths(self):
        """Destructively converts the indices in this table to the `EffectiveWidth` values of
        their buckets. Assumes that no bucket contains codepoints with different widths.
        """
        self.entries = list(map(lambda i: int(self.indexed[i].width()), self.entries))  # type: ignore
        del self.indexed

    def buckets(self):
        """Returns an iterator over this table's buckets."""
        return self.indexed

    def to_bytes(self) -> list[int]:
        """Returns this table's entries as a list of bytes. The bytes are formatted according to
        the `OffsetType` which the table was created with, converting any `EffectiveWidth` entries
        to their enum variant's integer value. For example, with `OffsetType.U2`, each byte will
        contain four packed 2-bit entries."""
        entries_per_byte = 8 // int(self.offset_type)
        byte_array = []
        for i in range(0, len(self.entries), entries_per_byte):
            byte = 0
            for j in range(0, entries_per_byte):
                byte |= self.entries[i + j] << (j * int(self.offset_type))
            byte_array.append(byte)
        return byte_array


def make_tables(
    width_map: list[CharWidth],
    cjk_width_map: list[CharWidth],
) -> list[Table]:
    """Creates a table for each configuration in `table_cfgs`, with the first config corresponding
    to the top-level lookup table, the second config corresponding to the second-level lookup
    table, and so forth. `entries` is an iterator over the `(Codepoint, EffectiveWidth)` pairs
    to include in the top-level table."""

    entries = enumerate([w.table_width() for w in width_map])
    cjk_entries = enumerate([w.table_width() for w in cjk_width_map])

    root_table = Table(
        "WIDTH_ROOT",
        [entries],
        [],
        TABLE_SPLITS[1],
        MAX_CODEPOINT_BITS,
        OffsetType.U8,
        128,
    )

    cjk_root_table = Table(
        "WIDTH_ROOT_CJK",
        [cjk_entries],
        [],
        TABLE_SPLITS[1],
        MAX_CODEPOINT_BITS,
        OffsetType.U8,
        128,
        starting_indexed=root_table.indexed,
        cfged=True,
    )

    middle_table = Table(
        "WIDTH_MIDDLE",
        map(lambda bucket: bucket.entries(), root_table.buckets()),
        map(lambda bucket: bucket.entries(), cjk_root_table.buckets()),
        TABLE_SPLITS[0],
        TABLE_SPLITS[1],
        OffsetType.U8,
        2 ** (TABLE_SPLITS[1] - TABLE_SPLITS[0]),
        bytes_per_row=2 ** (TABLE_SPLITS[1] - TABLE_SPLITS[0]),
    )

    leaves_table = Table(
        "WIDTH_LEAVES",
        map(
            lambda bucket: bucket.entries(),
            middle_table.buckets()[: middle_table.primary_bucket_len],
        ),
        map(
            lambda bucket: bucket.entries(),
            middle_table.buckets()[middle_table.primary_bucket_len :],
        ),
        0,
        TABLE_SPLITS[0],
        OffsetType.U2,
        2 ** (TABLE_SPLITS[0] - 2),
        bytes_per_row=2 ** (TABLE_SPLITS[0] - 2),
    )

    return [root_table, cjk_root_table, middle_table, leaves_table]


def load_emoji_presentation_sequences() -> list[int]:
    """Outputs a list of character ranages, corresponding to all the valid characters for starting
    an emoji presentation sequence."""

    with fetch_open("emoji/emoji-variation-sequences.txt") as sequences:
        # Match all emoji presentation sequences
        # (one codepoint followed by U+FE0F, and labeled "emoji style")
        sequence = re.compile(r"^([0-9A-F]+)\s+FE0F\s*;\s*emoji style")
        codepoints = []
        for line in sequences.readlines():
            if match := sequence.match(line):
                cp = int(match.group(1), 16)
                codepoints.append(cp)
    return codepoints


def load_text_presentation_sequences() -> list[int]:
    """Outputs a list of character ranages, corresponding to all the valid characters
    whose widths change with a text presentation sequence."""

    text_presentation_seq_codepoints = set()
    with fetch_open("emoji/emoji-variation-sequences.txt") as sequences:
        # Match all text presentation sequences
        # (one codepoint followed by U+FE0E, and labeled "text style")
        sequence = re.compile(r"^([0-9A-F]+)\s+FE0E\s*;\s*text style")
        for line in sequences.readlines():
            if match := sequence.match(line):
                cp = int(match.group(1), 16)
                text_presentation_seq_codepoints.add(cp)

    default_emoji_codepoints = set()

    load_property(
        "emoji/emoji-data.txt",
        "Emoji_Presentation",
        lambda cp: default_emoji_codepoints.add(cp),
    )

    codepoints = []
    for cp in text_presentation_seq_codepoints.intersection(default_emoji_codepoints):
        # "Enclosed Ideographic Supplement" block;
        # wide even in text presentation
        if not cp in range(0x1F200, 0x1F300):
            codepoints.append(cp)

    codepoints.sort()
    return codepoints


def make_presentation_sequence_table(
    seqs: list[Codepoint],
    width_map: list[CharWidth],
    spurious_true: set[CharWidth] = set(),
    lsb: int = 10,
) -> tuple[list[tuple[int, int]], list[list[int]]]:
    """Generates 2-level lookup table for whether a codepoint might start an emoji variation sequence.
    The first level is a match on all but the 10 LSB, the second level is a 1024-bit bitmap for those 10 LSB.
    """

    prefixes_dict = defaultdict(set)
    for cp in seqs:
        prefixes_dict[cp >> lsb].add(cp & (2**lsb - 1))

    msbs: list[int] = list(prefixes_dict.keys())

    for cp, width in enumerate(width_map):
        if width in spurious_true and (cp >> lsb) in msbs:
            prefixes_dict[cp >> lsb].add(cp & (2**lsb - 1))

    leaves: list[list[int]] = []
    for cps in prefixes_dict.values():
        leaf = [0] * (2 ** (lsb - 3))
        for cp in cps:
            idx_in_leaf, bit_shift = divmod(cp, 8)
            leaf[idx_in_leaf] |= 1 << bit_shift
        leaves.append(leaf)

    indexes = [(msb, index) for (index, msb) in enumerate(msbs)]

    # Cull duplicate leaves
    i = 0
    while i < len(leaves):
        first_idx = leaves.index(leaves[i])
        if first_idx == i:
            i += 1
        else:
            for j in range(0, len(indexes)):
                if indexes[j][1] == i:
                    indexes[j] = (indexes[j][0], first_idx)
                elif indexes[j][1] > i:
                    indexes[j] = (indexes[j][0], indexes[j][1] - 1)

            leaves.pop(i)

    return (indexes, leaves)


def lookup_fns(
    is_cjk: bool,
    special_ranges: list[tuple[tuple[Codepoint, Codepoint], CharWidth]],
    joining_group_lam: list[tuple[Codepoint, Codepoint]],
) -> str:
    if is_cjk:
        cfg = '#[cfg(feature = "cjk")]\n'
        cjk_lo = "_cjk"
        cjk_cap = "_CJK"
        ambig = "wide"
    else:
        cfg = ""
        cjk_lo = ""
        cjk_cap = ""
        ambig = "narrow"
    s = f"""
/// Returns the [UAX #11](https://www.unicode.org/reports/tr11/) based width of `c` by
/// consulting a multi-level lookup table.
///
/// # Maintenance
/// The tables themselves are autogenerated but this function is hardcoded. You should have
/// nothing to worry about if you re-run `unicode.py` (for example, when updating Unicode.)
/// However, if you change the *actual structure* of the lookup tables (perhaps by editing the
/// `make_tables` function in `unicode.py`) you must ensure that this code reflects those changes.
{cfg}#[inline]
fn lookup_width{cjk_lo}(c: char) -> (u8, WidthInfo) {{
    let cp = c as usize;

    let t1_offset = WIDTH_ROOT{cjk_cap}.0[cp >> {TABLE_SPLITS[1]}];

    // Each sub-table in WIDTH_MIDDLE is 7 bits, and each stored entry is a byte,
    // so each sub-table is 128 bytes in size.
    // (Sub-tables are selected using the computed offset from the previous table.)
    let t2_offset = WIDTH_MIDDLE.0[usize::from(t1_offset)][cp >> {TABLE_SPLITS[0]} & 0x{(2 ** (TABLE_SPLITS[1] - TABLE_SPLITS[0]) - 1):X}];

    // Each sub-table in WIDTH_LEAVES is 6 bits, but each stored entry is 2 bits.
    // This is accomplished by packing four stored entries into one byte.
    // So each sub-table is 2**(7-2) == 32 bytes in size.
    // Since this is the last table, each entry represents an encoded width.
    let packed_widths = WIDTH_LEAVES.0[usize::from(t2_offset)][cp >> 2 & 0x{(2 ** (TABLE_SPLITS[0] - 2) - 1):X}];

    // Extract the packed width
    let width = packed_widths >> (2 * (cp & 0b11)) & 0b11;

    if width < 3 {{
        (width, WidthInfo::DEFAULT)
    }} else {{
        match c {{
"""

    for (lo, hi), width in special_ranges:
        s += f"            '\\u{{{lo:X}}}'"
        if hi != lo:
            s += f"..='\\u{{{hi:X}}}'"
        s += f" => ({width.width_alone()}, WidthInfo::{str(width.name)}),\n"

    s += f"""            _ => (2, WidthInfo::EMOJI_PRESENTATION),
        }}
    }}
}}

/// Returns the [UAX #11](https://www.unicode.org/reports/tr11/) based width of `c`, or
/// `None` if `c` is a control character.
/// Ambiguous width characters are treated as {ambig}.
{cfg}#[inline]
pub fn single_char_width{cjk_lo}(c: char) -> Option<usize> {{
    if c < '\\u{{7F}}' {{
        if c >= '\\u{{20}}' {{
            // U+0020 to U+007F (exclusive) are single-width ASCII codepoints
            Some(1)
        }} else {{
            // U+0000 to U+0020 (exclusive) are control codes
            None
        }}
    }} else if c >= '\\u{{A0}}' {{
        // No characters >= U+00A0 are control codes, so we can consult the lookup tables
        Some(lookup_width{cjk_lo}(c).0.into())
    }} else {{
        // U+007F to U+00A0 (exclusive) are control codes
        None
    }}
}}

/// Returns the [UAX #11](https://www.unicode.org/reports/tr11/) based width of `c`.
/// Ambiguous width characters are treated as {ambig}.
{cfg}#[inline]
fn width_in_str{cjk_lo}(c: char, mut next_info: WidthInfo) -> (u8, WidthInfo) {{
    if next_info.is_emoji_presentation() {{
        if starts_emoji_presentation_seq(c) {{
            return (2, WidthInfo::DEFAULT);
        }} else {{
            next_info = next_info.unset_emoji_presentation();
        }}
    }}"""

    if is_cjk:
        s += """
    if (matches!(
        next_info,
        WidthInfo::COMBINING_LONG_SOLIDUS_OVERLAY | WidthInfo::SOLIDUS_OVERLAY_ALEF
    ) && matches!(c, '<' | '=' | '>'))
    {
        return (2, WidthInfo::DEFAULT);
    }"""

    s += """
    if c <= '\\u{A0}' {
        match c {
            '\\n' => (1, WidthInfo::LINE_FEED),
            '\\r' if next_info == WidthInfo::LINE_FEED => (0, WidthInfo::DEFAULT),
            _ => (1, WidthInfo::DEFAULT),
        }
    } else {
        // Fast path
        if next_info != WidthInfo::DEFAULT {
            if c == '\\u{FE0F}' {
                return (0, next_info.set_emoji_presentation());
            }"""

    if not is_cjk:
        s += """
            if c == '\\u{FE0E}' {
                return (0, next_info.set_text_presentation());
            }
            if next_info.is_text_presentation() {
                if starts_non_ideographic_text_presentation_seq(c) {
                    return (1, WidthInfo::DEFAULT);
                } else {
                    next_info = next_info.unset_text_presentation();
                }
            }"""

    s += """
            if next_info.is_ligature_transparent() {
                if c == '\\u{200D}' {
                    return (0, next_info.set_zwj_bit());
                } else if is_ligature_transparent(c) {
                    return (0, next_info);
                }
            }

            match (next_info, c) {
                // Arabic Lam-Alef ligature
                (
                    WidthInfo::JOINING_GROUP_ALEF,
                    """

    tail = False
    for lo, hi in joining_group_lam:
        if tail:
            s += " | "
        tail = True
        s += f"'\\u{{{lo:X}}}'"
        if hi != lo:
            s += f"..='\\u{{{hi:X}}}'"
    s += """,
                ) => return (0, WidthInfo::DEFAULT),
                (WidthInfo::JOINING_GROUP_ALEF, _) if is_transparent_zero_width(c) => {
                    return (0, WidthInfo::JOINING_GROUP_ALEF);
                }

                // Hebrew Alef-ZWJ-Lamed ligature
                (WidthInfo::ZWJ_HEBREW_LETTER_LAMED, '\\u{05D0}') => {
                    return (0, WidthInfo::DEFAULT);
                }

                // Buginese <a, -i> ZWJ ya ligature
                (WidthInfo::ZWJ_BUGINESE_LETTER_YA, '\\u{1A17}') => {
                    return (0, WidthInfo::BUGINESE_VOWEL_SIGN_I_ZWJ_LETTER_YA)
                }
                (WidthInfo::BUGINESE_VOWEL_SIGN_I_ZWJ_LETTER_YA, '\\u{1A15}') => {
                    return (0, WidthInfo::DEFAULT)
                }

                // Lisu tone letter combinations
                (WidthInfo::LISU_TONE_LETTER_MYA_NA_JEU, '\\u{A4F8}'..='\\u{A4FB}') => {
                    return (0, WidthInfo::DEFAULT);
                }"""
    if is_cjk:
        s += """
                (WidthInfo::COMBINING_LONG_SOLIDUS_OVERLAY, _) if is_solidus_transparent(c) => {
                    return (
                        lookup_width_cjk(c).0,
                        WidthInfo::COMBINING_LONG_SOLIDUS_OVERLAY,
                    );
                }
                (WidthInfo::JOINING_GROUP_ALEF, '\\u{0338}') => {
                    return (0, WidthInfo::SOLIDUS_OVERLAY_ALEF);
                }"""

    s += f"""

                _ => {{}}
            }}
        }}

        lookup_width{cjk_lo}(c)
    }}
}}

{cfg}#[inline]
pub fn str_width{cjk_lo}(s: &str) -> usize {{
    s.chars()
        .rfold((0, WidthInfo::DEFAULT), |(sum, next_info), c| {{
            let (add, info) = width_in_str{cjk_lo}(c, next_info);
            (sum + (usize::from(add)), info)
        }})
        .0
}}
"""

    return s


def emit_module(
    out_name: str,
    unicode_version: tuple[int, int, int],
    tables: list[Table],
    special_ranges: list[tuple[tuple[Codepoint, Codepoint], CharWidth]],
    special_ranges_cjk: list[tuple[tuple[Codepoint, Codepoint], CharWidth]],
    emoji_presentation_table: tuple[list[tuple[int, int]], list[list[int]]],
    text_presentation_table: tuple[list[tuple[int, int]], list[list[int]]],
    joining_group_lam: list[tuple[Codepoint, Codepoint]],
    non_transparent_zero_widths: list[tuple[Codepoint, Codepoint]],
    ligature_transparent: list[tuple[Codepoint, Codepoint]],
    solidus_transparent: list[tuple[Codepoint, Codepoint]],
):
    """Outputs a Rust module to `out_name` using table data from `tables`.
    If `TABLE_CFGS` is edited, you may need to edit the included code for `lookup_width`.
    """
    if os.path.exists(out_name):
        os.remove(out_name)
    with open(out_name, "w", newline="\n", encoding="utf-8") as module:
        module.write(
            """// Copyright 2012-2022 The Rust Project Developers. See the COPYRIGHT
// file at the top-level directory of this distribution and at
// http://rust-lang.org/COPYRIGHT.
//
// Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
// http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
// <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
// option. This file may not be copied, modified, or distributed
// except according to those terms.

// NOTE: The following code was generated by "scripts/unicode.py", do not edit directly

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct WidthInfo(u8);

impl WidthInfo {
    /// No special handling necessary
    const DEFAULT: Self = Self(0);
"""
        )

        for variant in CharWidth:
            if variant.table_width() == CharWidthInTable.SPECIAL:
                if variant in [
                    CharWidth.COMBINING_LONG_SOLIDUS_OVERLAY,
                    CharWidth.SOLIDUS_OVERLAY_ALEF,
                ]:
                    module.write('    #[cfg(feature = "cjk")]\n')
                module.write(
                    f"    const {variant.name}: Self = Self(0b{variant.value:08b});\n"
                )

        module.write(
            f"""
    /// Whether this width mode is ligature_transparent
    /// (has 3rd MSB set.)
    fn is_ligature_transparent(self) -> bool {{
        (self.0 & 0b0010_0000) == 0b0010_0000
    }}

    /// Sets 4th MSB.
    fn set_zwj_bit(self) -> Self {{
        Self(self.0 | 0b001_0000)
    }}

    /// Has top bit set
    fn is_emoji_presentation(self) -> bool {{
        (self.0 & 0b1000_0000) == 0b1000_0000
    }}

    /// Set top bit
    fn set_emoji_presentation(self) -> Self {{
        if self.0 >= 0b0000_1111 {{
            Self(self.0 | 0b1000_0000)
        }} else {{
            Self(0b1000_0000)
        }}
    }}

    /// Clear top bit
    fn unset_emoji_presentation(self) -> Self {{
        Self(self.0 & 0b0111_1111)
    }}

    /// Has 2nd bit set
    fn is_text_presentation(self) -> bool {{
        (self.0 & 0b0100_0000) == 0b0100_0000
    }}

    /// Set 2nd bit
    fn set_text_presentation(self) -> Self {{
        if self.0 >= 0b0000_1111 {{
            Self(self.0 | 0b0100_0000)
        }} else {{
            Self(0b0100_0000)
        }}
    }}

    /// Clear 2nd bit
    fn unset_text_presentation(self) -> Self {{
        Self(self.0 & 0b1011_1111)
    }}
}}

/// The version of [Unicode](http://www.unicode.org/)
/// that this version of unicode-width is based on.
pub const UNICODE_VERSION: (u8, u8, u8) = {unicode_version};
"""
        )

        module.write(lookup_fns(False, special_ranges, joining_group_lam))
        module.write(lookup_fns(True, special_ranges_cjk, joining_group_lam))

        emoji_presentation_idx, emoji_presentation_leaves = emoji_presentation_table
        text_presentation_idx, text_presentation_leaves = text_presentation_table

        module.write(
            """
/// Whether this character is a zero-width character with
/// `Joining_Type=Transparent`. Used by the Alef-Lamed ligatures.
/// See also [`is_ligature_transparent`], a near-subset of this (only ZWJ is excepted)
/// which is transparent for non-Arabic ligatures.
fn is_transparent_zero_width(c: char) -> bool {
    use core::cmp::Ordering;
    if lookup_width(c).0 != 0 {
        // Not zero-width
        false
    } else {
        let cp: u32 = c.into();
        NON_TRANSPARENT_ZERO_WIDTHS
            .binary_search_by(|&(lo, hi)| {
                let lo = u32::from_le_bytes([lo[0], lo[1], lo[2], 0]);
                let hi = u32::from_le_bytes([hi[0], hi[1], hi[2], 0]);
                if cp < lo {
                    Ordering::Greater
                } else if cp > hi {
                    Ordering::Less
                } else {
                    Ordering::Equal
                }
            })
            .is_err()
    }
}

/// Whether this character is a default-ignorable combining mark
/// or ZWJ. These characters won't interrupt non-Arabic ligatures.
fn is_ligature_transparent(c: char) -> bool {
    matches!(c, """
        )

        tail = False
        for lo, hi in ligature_transparent:
            if tail:
                module.write(" | ")
            tail = True
            module.write(f"'\\u{{{lo:X}}}'")
            if hi != lo:
                module.write(f"..='\\u{{{hi:X}}}'")

        module.write(
            """)
}

/// Whether this character is transparent wrt the effect of
/// U+0338 COMBINING LONG SOLIDUS OVERLAY
/// on its base character.
#[cfg(feature = "cjk")]
fn is_solidus_transparent(c: char) -> bool {
    use core::cmp::Ordering;
    let cp: u32 = c.into();
    is_ligature_transparent(c)
        || SOLIDUS_TRANSPARENT
            .binary_search_by(|&(lo, hi)| {
                let lo = u32::from_le_bytes([lo[0], lo[1], lo[2], 0]);
                let hi = u32::from_le_bytes([hi[0], hi[1], hi[2], 0]);
                if cp < lo {
                    Ordering::Greater
                } else if cp > hi {
                    Ordering::Less
                } else {
                    Ordering::Equal
                }
            })
            .is_ok()
}

/// Whether this character forms an [emoji presentation sequence]
/// (https://www.unicode.org/reports/tr51/#def_emoji_presentation_sequence)
/// when followed by `'\\u{FEOF}'`.
/// Emoji presentation sequences are considered to have width 2.
/// This may spuriously return `true` or `false` for characters that are always wide.
#[inline]
pub fn starts_emoji_presentation_seq(c: char) -> bool {
    let cp: u32 = c.into();
    // First level of lookup uses all but 10 LSB
    let top_bits = cp >> 10;
    let idx_of_leaf: usize = match top_bits {
"""
        )

        for msbs, i in emoji_presentation_idx:
            module.write(f"        {msbs} => {i},\n")

        module.write(
            """        _ => return false,
    };
    // Extract the 3-9th (0-indexed) least significant bits of `cp`,
    // and use them to index into `leaf_row`.
    let idx_within_leaf = usize::try_from((cp >> 3) & 0x7F).unwrap();
    let leaf_byte = EMOJI_PRESENTATION_LEAVES.0[idx_of_leaf][idx_within_leaf];
    // Use the 3 LSB of `cp` to index into `leaf_byte`.
    ((leaf_byte >> (cp & 7)) & 1) == 1
}
"""
        )

        module.write(
            """
/// Returns `true` iff `c` has default emoji presentation, but forms a [text presentation sequence]
/// (https://www.unicode.org/reports/tr51/#def_text_presentation_sequence)
/// when followed by `'\\u{FEOE}'`, and is not ideographic.
/// Such sequences are considered to have width 1.
///
/// This may spuriously return `true` for characters of narrow or ambiguous width.
#[inline]
pub fn starts_non_ideographic_text_presentation_seq(c: char) -> bool {
    let cp: u32 = c.into();
    // First level of lookup uses all but 10 LSB
    let top_bits = cp >> 10;
    let idx_of_leaf: usize = match top_bits {
"""
        )

        for msbs, i in text_presentation_idx:
            module.write(f"        {msbs} => {i},\n")

        module.write(
            """        _ => return false,
    };
    // Extract the 3-9th (0-indexed) least significant bits of `cp`,
    // and use them to index into `leaf_row`.
    let idx_within_leaf = usize::try_from((cp >> 3) & 0x7F).unwrap();
    let leaf_byte = TEXT_PRESENTATION_LEAVES.0[idx_of_leaf][idx_within_leaf];
    // Use the 3 LSB of `cp` to index into `leaf_byte`.
    ((leaf_byte >> (cp & 7)) & 1) == 1
}

#[repr(align(32))]
struct Align32<T>(T);

#[repr(align(64))]
struct Align64<T>(T);

#[repr(align(128))]
struct Align128<T>(T);
"""
        )

        subtable_count = 1
        for i, table in enumerate(tables):
            new_subtable_count = len(table.buckets())
            if i == len(tables) - 1:
                table.indices_to_widths()  # for the last table, indices == widths
            byte_array = table.to_bytes()

            if table.bytes_per_row is None:
                module.write(
                    f"/// Autogenerated. {subtable_count} sub-table(s). Consult [`lookup_width`] for layout info.)\n"
                )
                if table.cfged:
                    module.write('#[cfg(feature = "cjk")]\n')
                module.write(
                    f"static {table.name}: Align{table.align}<[u8; {len(byte_array)}]> = Align{table.align}(["
                )
                for j, byte in enumerate(byte_array):
                    # Add line breaks for every 15th entry (chosen to match what rustfmt does)
                    if j % 16 == 0:
                        module.write("\n   ")
                    module.write(f" 0x{byte:02X},")
                module.write("\n")
            else:
                num_rows = len(byte_array) // table.bytes_per_row
                num_primary_rows = (
                    table.primary_len
                    // (8 // int(table.offset_type))
                    // table.bytes_per_row
                )
                module.write(
                    f"""
#[cfg(feature = "cjk")]
const {table.name}_LEN: usize = {num_rows};
#[cfg(not(feature = "cjk"))]
const {table.name}_LEN: usize = {num_primary_rows};
/// Autogenerated. {subtable_count} sub-table(s). Consult [`lookup_width`] for layout info.
static {table.name}: Align{table.align}<[[u8; {table.bytes_per_row}]; {table.name}_LEN]> = Align{table.align}([\n"""
                )
                for row_num in range(0, num_rows):
                    if row_num >= num_primary_rows:
                        module.write('    #[cfg(feature = "cjk")]\n')
                    module.write("    [\n")
                    row = byte_array[
                        row_num
                        * table.bytes_per_row : (row_num + 1)
                        * table.bytes_per_row
                    ]
                    for subrow in batched(row, 15):
                        module.write("       ")
                        for entry in subrow:
                            module.write(f" 0x{entry:02X},")
                        module.write("\n")
                    module.write("    ],\n")
            module.write("]);\n")
            subtable_count = new_subtable_count

        # non transparent zero width table

        module.write(
            f"""
/// Sorted list of codepoint ranges (inclusive)
/// that are zero-width but not `Joining_Type=Transparent`
/// FIXME: can we get better compression?
static NON_TRANSPARENT_ZERO_WIDTHS: [([u8; 3], [u8; 3]); {len(non_transparent_zero_widths)}] = [
"""
        )

        for lo, hi in non_transparent_zero_widths:
            module.write(
                f"    ([0x{lo & 0xFF:02X}, 0x{lo >> 8 & 0xFF:02X}, 0x{lo >> 16:02X}], [0x{hi & 0xFF:02X}, 0x{hi >> 8 & 0xFF:02X}, 0x{hi >> 16:02X}]),\n"
            )

        # solidus transparent table

        module.write(
            f"""];

/// Sorted list of codepoint ranges (inclusive)
/// that don't affect how the combining solidus applies
/// (mostly ccc > 1).
/// FIXME: can we get better compression?
#[cfg(feature = "cjk")]
static SOLIDUS_TRANSPARENT: [([u8; 3], [u8; 3]); {len(solidus_transparent)}] = [
"""
        )

        for lo, hi in solidus_transparent:
            module.write(
                f"    ([0x{lo & 0xFF:02X}, 0x{lo >> 8 & 0xFF:02X}, 0x{lo >> 16:02X}], [0x{hi & 0xFF:02X}, 0x{hi >> 8 & 0xFF:02X}, 0x{hi >> 16:02X}]),\n"
            )

        # emoji table

        module.write(
            f"""];

/// Array of 1024-bit bitmaps. Index into the correct bitmap with the 10 LSB of your codepoint
/// to get whether it can start an emoji presentation sequence.
static EMOJI_PRESENTATION_LEAVES: Align128<[[u8; 128]; {len(emoji_presentation_leaves)}]> = Align128([
"""
        )
        for leaf in emoji_presentation_leaves:
            module.write("    [\n")
            for row in batched(leaf, 15):
                module.write("       ")
                for entry in row:
                    module.write(f" 0x{entry:02X},")
                module.write("\n")
            module.write("    ],\n")

        module.write("]);\n")

        # text table

        module.write(
            f"""
/// Array of 1024-bit bitmaps. Index into the correct bitmap with the 10 LSB of your codepoint
/// to get whether it can start a text presentation sequence.
static TEXT_PRESENTATION_LEAVES: Align128<[[u8; 128]; {len(text_presentation_leaves)}]> = Align128([
"""
        )
        for leaf in text_presentation_leaves:
            module.write("    [\n")
            for row in batched(leaf, 15):
                module.write("       ")
                for entry in row:
                    module.write(f" 0x{entry:02X},")
                module.write("\n")
            module.write("    ],\n")

        module.write("]);\n")


def main(module_path: str):
    """Obtain character data from the latest version of Unicode, transform it into a multi-level
    lookup table for character width, and write a Rust module utilizing that table to
    `module_filename`.

    See `lib.rs` for documentation of the exact width rules.
    """
    version = load_unicode_version()
    print(f"Generating module for Unicode {version[0]}.{version[1]}.{version[2]}")

    (width_map, cjk_width_map) = load_width_maps()

    tables = make_tables(width_map, cjk_width_map)

    special_ranges = make_special_ranges(width_map)
    cjk_special_ranges = make_special_ranges(cjk_width_map)

    emoji_presentations = load_emoji_presentation_sequences()
    emoji_presentation_table = make_presentation_sequence_table(
        emoji_presentations, width_map
    )

    text_presentations = load_text_presentation_sequences()
    text_presentation_table = make_presentation_sequence_table(
        text_presentations,
        width_map,
        {CharWidth.NARROW},
    )

    joining_group_lam = load_joining_group_lam()
    non_transparent_zero_widths = load_non_transparent_zero_widths(width_map)
    ligature_transparent = load_ligature_transparent()
    solidus_transparent = load_solidus_transparent(ligature_transparent, cjk_width_map)

    # Download normalization test file for use by tests
    fetch_open("NormalizationTest.txt", "../tests/")

    print("------------------------")
    total_size = 0
    for i, table in enumerate(tables):
        size_bytes = len(table.to_bytes())
        print(f"Table {i} size: {size_bytes} bytes")
        total_size += size_bytes

    for s, table in [
        ("Emoji", emoji_presentation_table),
        ("Text", text_presentation_table),
    ]:
        index_size = len(table[0])
        print(f"{s} presentation index size: {index_size} bytes")
        total_size += index_size
        leaves_size = len(table[1]) * len(table[1][0])
        print(f"{s} presentation leaves size: {leaves_size} bytes")
        total_size += leaves_size
    print("------------------------")
    print(f"  Total size: {total_size} bytes")

    emit_module(
        out_name=module_path,
        unicode_version=version,
        tables=tables,
        special_ranges=special_ranges,
        special_ranges_cjk=cjk_special_ranges,
        emoji_presentation_table=emoji_presentation_table,
        text_presentation_table=text_presentation_table,
        joining_group_lam=joining_group_lam,
        non_transparent_zero_widths=non_transparent_zero_widths,
        ligature_transparent=ligature_transparent,
        solidus_transparent=solidus_transparent,
    )
    print(f'Wrote to "{module_path}"')


if __name__ == "__main__":
    main(MODULE_PATH)
