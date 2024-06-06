#!/usr/bin/env python3

import logging
import os
import os.path as op
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from queersmission import Knapsack, copy_file


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

    def touch(self, file, content: str = "Claire"):
        os.makedirs(op.dirname(file), exist_ok=True)
        with open(file, "w") as f:
            f.write(content)

    def assertFileContent(self, file, content):
        with open(file, "r") as f:
            self.assertEqual(f.read(), content)

    def run_copy(self, src, dst_dir):
        src = op.normpath(src)
        dst_dir = op.normpath(dst_dir)
        if not op.isdir(src):
            dst_dir = op.join(dst_dir, op.splitext(op.basename(src))[0])
        os.makedirs(dst_dir, exist_ok=True)
        dst = op.join(dst_dir, op.basename(src))
        copy_file(src, dst)

    def test_raise1(self):
        src, dst = self.src, self.dst
        logging.disable(logging.WARNING)
        # dir -> file
        self.touch(f"{src}/dir/file.txt")
        self.touch(f"{dst}/dir")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/dir", dst)
        logging.disable(logging.NOTSET)

    def test_raise2(self):
        src, dst = self.src, self.dst
        logging.disable(logging.WARNING)
        # file -> dir
        self.touch(f"{src}/file.txt")
        # empty dst dir
        os.makedirs(f"{dst}/file/file.txt")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/file.txt", dst)
        # non-empty
        self.touch(f"{dst}/file/file.txt/file.txt")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/file.txt", dst)
        logging.disable(logging.NOTSET)

    def test_copy_dir1(self):
        src, dst = self.src, self.dst
        # copy dir
        self.touch(f"{src}/dir/file.txt")
        self.run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file.txt"))
        self.assertTrue(op.isfile(f"{dst}/dir/file.txt"))

    def test_copy_dir2(self):
        src, dst = self.src, self.dst
        # overwrite dir
        self.touch(f"{src}/dir/file.txt", "src")
        self.touch(f"{dst}/dir/file.txt")
        self.run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file.txt"))
        self.assertFileContent(f"{dst}/dir/file.txt", "src")
        self.assertFalse(op.exists(f"{dst}/dir/dir"))

    def test_copy_dir3(self):
        src, dst = self.src, self.dst
        # merge copy
        self.touch(f"{src}/dir/file1.txt", "src")
        self.touch(f"{src}/dir/file2.txt", "src")
        self.touch(f"{dst}/dir/file1.txt")
        self.touch(f"{dst}/dir/file3.txt")

        self.run_copy(f"{src}/dir", dst)
        self.assertTrue(op.isfile(f"{src}/dir/file1.txt"))
        self.assertFileContent(f"{dst}/dir/file1.txt", "src")
        self.assertFileContent(f"{dst}/dir/file2.txt", "src")
        self.assertTrue(op.isfile(f"{dst}/dir/file3.txt"))

    def test_copy_file1(self):
        src, dst = self.src, self.dst
        # copy file
        self.touch(f"{src}/file.txt")
        self.run_copy(f"{src}/file.txt", dst)
        self.assertTrue(op.isfile(f"{src}/file.txt"))
        self.assertTrue(op.isfile(f"{dst}/file/file.txt"))

    def test_copy_file2(self):
        src, dst = self.src, self.dst
        # overwrite file
        self.touch(f"{src}/file.txt", "src")
        self.touch(f"{dst}/file/file.txt")
        self.run_copy(f"{src}/file.txt", dst)
        self.assertTrue(op.isfile(f"{src}/file.txt"))
        self.assertFileContent(f"{dst}/file/file.txt", "src")


class TestKnapsack(unittest.TestCase):

    _MC = 1024**2

    def _get_random(self):
        n = random.choice(range(200))
        weights = random.choices(range(1024**3, 1024**4), k=n)
        values = random.choices(range(1, 1000), k=n)
        capacity = sum(random.choices(weights, k=n // 3))
        return weights, values, capacity

    def test_low(self):
        data = [
            ([], [], 100),
            ([1], [2], 0),
            ([1], [2], -100),
        ]
        knapsack = Knapsack(self._MC)
        for w, v, c in data:
            self.assertEqual(knapsack.solve(w, v, c), set())

    def test_high(self):
        knapsack = Knapsack(self._MC)
        for i in range(3):
            w, v, _ = self._get_random()
            c = sum(w) + i
            self.assertEqual(knapsack.solve(w, v, c), set(range(len(w))))

    def test_sum(self):
        knapsack = Knapsack(self._MC)
        for _ in range(5):
            w, v, c = self._get_random()
            _sum = sum(w[i] for i in knapsack.solve(w, v, c))
            self.assertLessEqual(_sum, c)

    def test_optimal(self):
        w = [21, 11, 15, 9, 34, 25, 41, 52]
        v = [22, 12, 16, 10, 35, 26, 42, 53]
        c = 100
        answer = {0, 1, 3, 4, 5}
        self.assertEqual(Knapsack().solve(w, v, c), answer)
        self.assertEqual(Knapsack(self._MC).solve(w, v, c), answer)


if __name__ == "__main__":
    unittest.main()
