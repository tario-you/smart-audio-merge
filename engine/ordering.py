"""Conservative sequence detection for audio filenames."""
import re
import unicodedata
from pathlib import Path

ONES = dict(zip(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),
    range(20)))
TENS = dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(), range(20, 100, 10)))
ORDINALS = dict(zip(
    'first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth'.split(),
    range(1, 20)))
ORDINALS.update(dict(zip('twentieth thirtieth fortieth fiftieth sixtieth seventieth eightieth ninetieth hundredth'.split(), range(20, 101, 10))))
LABELS = {'track', 'chapter', 'part', 'disc', 'disk', 'cd', 'volume', 'vol', 'episode', 'ep', 'section', 'recording', 'audio'}
ROMAN = re.compile(r'^(?=.)C?(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$', re.I)


def roman_value(token):
    if not ROMAN.fullmatch(token):
        return None
    values = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100}
    nums = [values[c] for c in token.lower()]
    value = sum(-n if i + 1 < len(nums) and n < nums[i + 1] else n for i, n in enumerate(nums))
    return value if 1 <= value <= 100 else None


def normalized(stem):
    return unicodedata.normalize('NFKC', stem).casefold()


def sequence(stem):
    tokens = re.findall(r'\d+(?:st|nd|rd|th)?|[^\W\d_]+', normalized(stem))
    found, kinds = [], set()
    i = 0
    while i < len(tokens):
        token = tokens[i]
        digit = re.fullmatch(r'(\d+)(?:st|nd|rd|th)?', token)
        contextual = i == 0 or tokens[i - 1] in LABELS or len(tokens) == 1
        if digit:
            found.append(int(digit[1]))
            kinds.add('numbers')
        elif contextual and (token in ONES or token in TENS or token in ORDINALS or token == 'hundred'):
            value = ONES.get(token, TENS.get(token, ORDINALS.get(token, 100)))
            if token in TENS and i + 1 < len(tokens) and tokens[i + 1] in {**ONES, **ORDINALS}:
                nxt = {**ONES, **ORDINALS}[tokens[i + 1]]
                if 0 < nxt < 10:
                    value += nxt
                    i += 1
            elif token == 'one' and i + 1 < len(tokens) and tokens[i + 1] == 'hundred':
                value = 100
                i += 1
            found.append(value)
            kinds.add('written numbers')
        elif contextual and (value := roman_value(token)) is not None:
            found.append(value)
            kinds.add('Roman numerals')
        i += 1
    return tuple(found), kinds


def natural(stem):
    return tuple((0, int(x)) if x.isdecimal() else (1, x) for x in re.split(r'(\d+)', normalized(stem)) if x)


def order(items):
    """Use filename sequences, then complete track tags, then natural names."""
    parsed = [sequence(Path(item['path']).stem) for item in items]
    numbered = [bool(s) for s, _ in parsed]
    tags = [item.get('track') for item in items]
    warnings = []
    if all(numbered):
        keys = [s for s, _ in parsed]
        mode = 'Filename sequence'
        kinds = sorted(set().union(*(k for _, k in parsed)))
        detail = 'Recognized ' + ', '.join(kinds) + '. Leading zeros are ignored.'
    elif all(tag is not None for tag in tags) and len(set(tags)) > 1:
        keys = [(item.get('disc') or 1, item['track']) for item in items]
        mode = 'Embedded disc and track numbers'
        detail = 'Used the track numbers stored inside the audio files.'
    else:
        keys = [(0, *s) if s else (1,) for s, _ in parsed]
        mode = 'Filename sequence' if any(numbered) else 'Natural filename order'
        detail = 'Numbered files come first. Review the order before merging.'
        if not any(numbered):
            detail = 'No complete numbering was found. Review the order before merging.'
        warnings.append('Some filenames have no sequence number.' if any(numbered) else 'Chronology could not be inferred from numbering or track tags.')
    if len(set(keys)) < len(keys) and (any(numbered) or mode.startswith('Embedded')):
        warnings.append('Some sequence numbers repeat. Check those files in the list.')
    indices = sorted(range(len(items)), key=lambda i: (keys[i], natural(Path(items[i]['path']).stem), items[i]['path']))
    result = []
    for i in indices:
        item = dict(items[i])
        item['sequence'] = '.'.join(map(str, parsed[i][0])) if parsed[i][0] else ''
        result.append(item)
    return {'items': result, 'mode': mode, 'detail': detail, 'warnings': warnings}
