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

sys.path.append(str(Path(__file__).resolve().parents[1]))

from queersmission.storage import knapsack
from queersmission.utils import copy_file


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
        with self.assertRaises(OSError):
            self._run_copy(f"{src}/dir", dst)

    def test_raise2(self):
        src, dst = self.src, self.dst
        # file -> dir
        self._touch(f"{src}/file.txt")
        # empty dst dir
        os.makedirs(f"{dst}/file/file.txt")
        with self.assertRaises(OSError):
            self._run_copy(f"{src}/file.txt", dst)
        # non-empty
        self._touch(f"{dst}/file/file.txt/file.txt")
        with self.assertRaises(OSError):
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


class TestKnapsack(unittest.TestCase):

    max_cells = 1024**2

    @staticmethod
    def _get_random():
        n = random.randint(10, 300)
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
        # weights or capacity is 0
        data = [
            ([], [], 100),
            ([1], [2], 0),
            ([1], [2], -100),
        ]
        answer = set()
        for w, v, c in data:
            self.assertSetEqual(knapsack(w, v, c, self.max_cells), answer)

    def test_full(self):
        # capacity >= sum(weights)
        for i in range(3):
            w, v, _ = self._get_random()
            c = sum(w) + i
            answer = set(range(len(w)))
            self.assertSetEqual(knapsack(w, v, c, self.max_cells), answer)

    def test_sum(self):
        # sum of result's weights should <= capacity
        for _ in range(3):
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


if __name__ == "__main__":
    unittest.main()
