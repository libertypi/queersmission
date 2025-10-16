#!/usr/bin/env python3

import os
import os.path as op
import random
import sys
import tempfile
import unittest
from pathlib import Path

try:
    from ortools.algorithms.python import knapsack_solver
except ImportError:
    knapsack_solver = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from queersmission.cat import _has_sequence
from queersmission.storage import knapsack
from queersmission.utils import copy_file, humansize


class TestFileOperations(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory to isolate file system operations
        self.root = tempfile.TemporaryDirectory()
        self.src = op.join(self.root.name, "src")
        self.dst = op.join(self.root.name, "dst")
        os.makedirs(self.src, exist_ok=True)
        os.makedirs(self.dst, exist_ok=True)

    def tearDown(self):
        # Clean up the temporary directory after each test
        self.root.cleanup()

    def assertFileContent(self, file, content):
        with open(file, "r") as f:
            self.assertEqual(f.read(), content)

    @staticmethod
    def _touch(file, content: str = "Claire"):
        os.makedirs(op.dirname(file), exist_ok=True)
        with open(file, "w") as f:
            f.write(content)

    @staticmethod
    def _run_copy(src, dst_dir):
        src = op.normpath(src)
        dst_dir = op.normpath(dst_dir)
        if not op.isdir(src):
            dst_dir = op.join(dst_dir, op.splitext(op.basename(src))[0])
        os.makedirs(dst_dir, exist_ok=True)
        dst = op.join(dst_dir, op.basename(src))
        copy_file(src, dst)

    def test_raise1(self):
        src, dst = self.src, self.dst
        # dir -> file
        self._touch(f"{src}/dir/file.txt")
        self._touch(f"{dst}/dir")
        with self.assertRaises(RuntimeError):
            self._run_copy(f"{src}/dir", dst)

    def test_raise2(self):
        src, dst = self.src, self.dst
        # file -> dir
        self._touch(f"{src}/file.txt")
        # empty dst dir
        os.makedirs(f"{dst}/file/file.txt")
        with self.assertRaises(RuntimeError):
            self._run_copy(f"{src}/file.txt", dst)
        # non-empty
        self._touch(f"{dst}/file/file.txt/file.txt")
        with self.assertRaises(RuntimeError):
            self._run_copy(f"{src}/file.txt", dst)

    def test_copy_dir1(self):
        src, dst = self.src, self.dst
        # copy dir
        self._touch(f"{src}/dir/file.txt")
        self._run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file.txt"))
        self.assertTrue(op.isfile(f"{dst}/dir/file.txt"))

    def test_copy_dir2(self):
        src, dst = self.src, self.dst
        # overwrite dir
        self._touch(f"{src}/dir/file.txt", "src")
        self._touch(f"{dst}/dir/file.txt")
        self._run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file.txt"))
        self.assertFileContent(f"{dst}/dir/file.txt", "src")
        self.assertFalse(op.exists(f"{dst}/dir/dir"))

    def test_copy_dir3(self):
        src, dst = self.src, self.dst
        # merge copy
        self._touch(f"{src}/dir/file1.txt", "src")
        self._touch(f"{src}/dir/file2.txt", "src")
        self._touch(f"{dst}/dir/file1.txt")
        self._touch(f"{dst}/dir/file3.txt")

        self._run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file1.txt"))
        self.assertFileContent(f"{dst}/dir/file1.txt", "src")
        self.assertFileContent(f"{dst}/dir/file2.txt", "src")
        self.assertTrue(op.isfile(f"{dst}/dir/file3.txt"))

    def test_copy_file1(self):
        src, dst = self.src, self.dst
        # copy file
        self._touch(f"{src}/file.txt")
        self._run_copy(f"{src}/file.txt", dst)
        self.assertTrue(op.isfile(f"{src}/file.txt"))
        self.assertTrue(op.isfile(f"{dst}/file/file.txt"))

    def test_copy_file2(self):
        src, dst = self.src, self.dst
        # overwrite file
        self._touch(f"{src}/file.txt", "src")
        self._touch(f"{dst}/file/file.txt")
        self._run_copy(f"{src}/file.txt", dst)
        self.assertTrue(op.isfile(f"{src}/file.txt"))
        self.assertFileContent(f"{dst}/file/file.txt", "src")


class TestHumanSize(unittest.TestCase):
    def test_zero_int_and_float(self):
        self.assertEqual(humansize(0), "0.00 B")
        self.assertEqual(humansize(0.0), "0.00 B")

    def test_negative_values(self):
        self.assertEqual(humansize(-1), "-1.00 B")
        self.assertEqual(humansize(-1024), "-1.00 KiB")
        self.assertEqual(humansize(-1536), "-1.50 KiB")

    def test_float_input(self):
        # floats are truncated via int()
        self.assertEqual(humansize(1.9), "1.00 B")
        self.assertEqual(humansize(1536.9), "1.50 KiB")

    def test_invalid_inputs_raise(self):
        with self.assertRaises((TypeError, ValueError)):
            humansize(None)
        with self.assertRaises((TypeError, ValueError)):
            humansize("one thousand")

    def test_boundaries(self):
        self.assertEqual(humansize(1023), "1023.00 B")
        self.assertEqual(humansize(1024), "1.00 KiB")
        # Just below MiB — note rounding to two decimals
        self.assertEqual(humansize(1024 * 1024 - 1), "1024.00 KiB")
        self.assertEqual(humansize(1024 * 1024), "1.00 MiB")

    def test_very_large_caps_to_YiB(self):
        s = humansize(1 << 100)  # much larger than YiB
        self.assertTrue(s.endswith("YiB"))


class TestKnapsack(unittest.TestCase):

    max_cells = 1024**2

    @staticmethod
    def _get_random():
        n = random.randint(5, 100)
        weights = random.choices(range(500 * 1024**2, 10 * 1024**4), k=n)
        values = random.choices(range(1, 5000), k=n)
        capacity = sum(weights) // random.randint(2, 5)
        return weights, values, capacity

    @staticmethod
    def _ortools_solve(weights, values, capacity):
        solver = knapsack_solver.KnapsackSolver(
            knapsack_solver.SolverType.KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER,
            "Knapsack",
        )
        solver.init(values, [weights], [capacity])
        return solver.solve()

    def test_empty(self):
        # when weights or capacity is 0
        data = [
            ([], [], 100),
            ([1], [1], 0),
            ([1], [1], -100),
        ]
        answer = set()
        for w, v, c in data:
            self.assertSetEqual(knapsack(w, v, c, self.max_cells), answer)

    def test_full(self):
        # when capacity >= sum(weights)
        for i in range(3):
            w, v, _ = self._get_random()
            c = sum(w) + i
            answer = set(range(len(w)))
            self.assertSetEqual(knapsack(w, v, c, self.max_cells), answer)

    def test_special_weight(self):
        # weight == 0 or weight > capacity
        data = [
            ([0, 2], [1, 1], 1, {0}),
            ([1, 2, 5], [1, 1, 1], 3, {0, 1}),
        ]
        for w, v, c, answer in data:
            self.assertSetEqual(knapsack(w, v, c), answer)

    def test_sum(self):
        # sum of result's weights should <= capacity
        for _ in range(10):
            w, v, c = self._get_random()
            result = knapsack(w, v, c, self.max_cells)
            self.assertLessEqual(sum(w[i] for i in result), c)

    def test_simple(self):
        # a simple problem
        w = [21, 11, 15, 9, 34, 25, 41, 52]
        v = [22, 12, 16, 10, 35, 26, 42, 53]
        c = 100
        answer = {0, 1, 3, 4, 5}
        self.assertSetEqual(knapsack(w, v, c, self.max_cells), answer)

    @unittest.skipIf(knapsack_solver is None, "OR-Tools not available")
    def test_comparative(self):
        # compare with OR-Tools
        for _ in range(50):
            n = random.randint(10, 50)
            weights = random.choices(range(1, 500), k=n)
            values = random.choices(range(1, 500), k=n)
            capacity = sum(weights) // random.randint(2, 4)

            result = knapsack(weights, values, capacity)
            answer = self._ortools_solve(weights, values, capacity)

            self.assertLessEqual(sum(weights[i] for i in result), capacity)
            self.assertEqual(sum(values[i] for i in result), answer)


class TestHasSequence(unittest.TestCase):
    """Tests for queersmission.cat._has_sequence."""

    @staticmethod
    def P(dir_: str, stem: str, ext: str):
        # root is a POSIX-style path without extension; ext is the extension
        return (f"{dir_.rstrip('/')}/{stem}", ext)

    def test_dirs_do_not_mix(self):
        # Same numbers split across dirs => should not combine
        paths = [
            self.P("/show/s1", "E04", "mkv"),
            self.P("/show/s2", "E05", "mkv"),
            self.P("/show/s1", "E06", "mkv"),
        ]
        self.assertFalse(_has_sequence(paths))

    def test_ignores_zero_in_0_1_2(self):
        # 0 is not counted (pattern is 1–99), so 0,1,2 => False
        paths = [
            self.P("/show", "E00", "mkv"),
            self.P("/show", "E01", "mkv"),
            self.P("/show", "E02", "mkv"),
        ]
        self.assertFalse(_has_sequence(paths))

    def test_only_two_consecutive_is_false(self):
        # Only 2 consecutive numbers present (plus a non-number file) => False
        paths = [
            self.P("/show", "E01", "mp4"),
            self.P("/show", "E04", "mp4"),
            self.P("/show", "E05", "mp4"),
            self.P("/show", "teaser", "mp4"),
        ]
        self.assertFalse(_has_sequence(paths))

    def test_three_consecutive_any_order_true(self):
        # 3-in-a-row in any order => True
        paths = [
            self.P("/show", "Ep05", "mkv"),
            self.P("/show", "Ep04", "mkv"),
            self.P("/show", "Ep06", "mkv"),
        ]
        self.assertTrue(_has_sequence(paths))

    def test_mixed_noise_still_true(self):
        # Run of three mixed with other non-sequential items => True
        paths = [
            self.P("/show", "intro", "mkv"),
            self.P("/show", "E03", "mkv"),
            self.P("/show", "E01", "mkv"),
            self.P("/show", "E02", "mkv"),
            self.P("/show", "E05", "mkv"),
            self.P("/show", "extra-clip", "mkv"),
        ]
        self.assertTrue(_has_sequence(paths))

    def test_mixed_extensions_break_group(self):
        # Current impl groups by (prefix, suffix, ext), so mixed ext => False
        paths = [
            self.P("/show", "E04", "mkv"),
            self.P("/show", "E05", "mp4"),
            self.P("/show", "E06", "mkv"),
        ]
        self.assertFalse(_has_sequence(paths))

    def test_mixed_prefixes_break_group(self):
        # Different prefixes => False
        paths = [
            self.P("/show", "S01", "mkv"),
            self.P("/show", "S02", "mkv"),
            self.P("/show", "03S", "mkv"),
        ]
        self.assertFalse(_has_sequence(paths))


if __name__ == "__main__":
    unittest.main()
