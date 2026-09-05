import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from ordering import order, sequence


def sort(names, **extra):
    return [x['name'] for x in order([{'path': '/fixture/' + name, 'name': name, **extra} for name in names])['items']]


def words(number):
    ones = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split()
    tens = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
    if number < 20:
        return ones[number]
    if number == 100:
        return 'one hundred'
    return tens[number // 10] + ('-' + ones[number % 10] if number % 10 else '')


def roman(number):
    result = ''
    for value, token in [(100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')]:
        while number >= value:
            result += token
            number -= value
    return result


class OrderingTests(unittest.TestCase):
    def test_mixed_padding_1_through_100(self):
        names = [f'{n:0{1 + n % 3}d}_1.mp3' for n in range(1, 101)]
        shuffled = names.copy()
        random.Random(17).shuffle(shuffled)
        self.assertEqual(sort(shuffled), names)

    def test_english_1_through_100(self):
        names = [f'Chapter {words(n)}.mp3' for n in range(1, 101)]
        self.assertEqual(sort(names[::-1]), names)

    def test_roman_1_through_100(self):
        names = [f'Track {roman(n)}.mp3' for n in range(1, 101)]
        self.assertEqual(sort(names[::-1]), names)

    def test_mixed_conventions_and_subparts(self):
        names = ['1.mp3', '001_1.mp3', '001_2.mp3', 'Chapter two.mp3', 'Track III.mp3', '04.mp3', '10.mp3', '100.mp3']
        self.assertEqual(sort(names[::-1]), names)

    def test_disc_track_and_common_numbers(self):
        names = ['Course 2026 Disc 1 Track 2.mp3', 'Course 2026 Disc 1 Track 10.mp3', 'Course 2026 Disc 2 Track 1.mp3']
        self.assertEqual(sort(names[::-1]), names)

    def test_iso_dates(self):
        names = ['2026-01-02 09-10.mp3', '2026-01-02 10-00.mp3', '2026-02-01 08-00.mp3']
        self.assertEqual(sort(names[::-1]), names)

    def test_ordinals_unicode_and_titles(self):
        self.assertEqual(sequence('Chapter twenty-first')[0], (21,))
        self.assertEqual(sequence('１００')[0], (100,))
        self.assertEqual(sequence('Lesson 02 - I am here')[0], (2,))
        self.assertEqual(sequence('21st')[0], (21,))

    def test_track_metadata(self):
        items = [{'path': '/z.mp3', 'track': 1, 'disc': 2}, {'path': '/b.mp3', 'track': 2, 'disc': 1}, {'path': '/a.mp3', 'track': 10, 'disc': 1}]
        result = order(items)
        self.assertEqual([i['path'] for i in result['items']], ['/b.mp3', '/a.mp3', '/z.mp3'])
        self.assertEqual(result['mode'], 'Embedded disc and track numbers')

    def test_ambiguity_is_visible(self):
        result = order([{'path': '/01 a.mp3'}, {'path': '/1 b.mp3'}, {'path': '/intro.mp3'}])
        self.assertEqual(len(result['warnings']), 2)
        self.assertTrue(result['items'][-1]['path'].endswith('intro.mp3'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
