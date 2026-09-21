"""Named CJK punctuation used in patterns, so regexes read as words rather than escapes.

Each constant is one character. Unicode names are given so the intent is
clear without rendering the glyph.
"""

IDEOGRAPHIC_COMMA = "\u3001"  # U+3001 IDEOGRAPHIC COMMA, the enumeration comma
IDEOGRAPHIC_FULL_STOP = "\u3002"  # U+3002 IDEOGRAPHIC FULL STOP, the CJK period
FULLWIDTH_EXCLAMATION_MARK = "\uff01"  # U+FF01
FULLWIDTH_COMMA = "\uff0c"  # U+FF0C
FULLWIDTH_COLON = "\uff1a"  # U+FF1A
FULLWIDTH_SEMICOLON = "\uff1b"  # U+FF1B
FULLWIDTH_QUESTION_MARK = "\uff1f"  # U+FF1F
EN_DASH = "\u2013"  # U+2013
EM_DASH = "\u2014"  # U+2014

# Characters that end a sentence, ASCII and CJK.
SENTENCE_ENDS = ".!?;" + IDEOGRAPHIC_FULL_STOP + FULLWIDTH_EXCLAMATION_MARK + FULLWIDTH_QUESTION_MARK + FULLWIDTH_SEMICOLON

# Punctuation that terminates an inline #tag, ASCII and CJK.
TAG_TERMINATORS = (
    ",.!?;:"
    + IDEOGRAPHIC_COMMA
    + IDEOGRAPHIC_FULL_STOP
    + FULLWIDTH_COMMA
    + FULLWIDTH_EXCLAMATION_MARK
    + FULLWIDTH_QUESTION_MARK
    + FULLWIDTH_COLON
    + FULLWIDTH_SEMICOLON
)

# Separators a writer may put after a time stamp such as "09:20 -" or "09:20:".
TIME_SEPARATORS = "-:" + EN_DASH + EM_DASH + FULLWIDTH_COLON
