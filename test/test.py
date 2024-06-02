#!/usr/bin/env python3

import logging
import os
import os.path as op
import sys
import tempfile
import unittest

sys.path.append(op.realpath(f"{__file__}/../.."))
import queersmission
from queersmission import copy_file, move_file

queersmission.logger.setLevel(logging.ERROR)


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

    def _run(self, src, dst, func):
        src = op.normpath(src)
        dst = op.normpath(dst)
        if not op.isdir(src):
            dst = op.join(dst, op.splitext(op.basename(src))[0])
        os.makedirs(dst, exist_ok=True)
        dst = op.join(dst, op.basename(src))
        func(src, dst)

    def run_copy(self, src, dst):
        self._run(src, dst, copy_file)

    def run_move(self, src, dst):
        self._run(src, dst, move_file)

    def test_raise1(self):
        src, dst = self.src, self.dst
        # dir -> file
        self.touch(f"{src}/dir/file.txt")
        self.touch(f"{dst}/dir")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/dir", dst)
        with self.assertRaises(OSError):
            self.run_move(f"{src}/dir", dst)

    def test_raise2(self):
        src, dst = self.src, self.dst
        # file -> dir
        self.touch(f"{src}/file.txt")
        # empty dst dir
        os.makedirs(f"{dst}/file/file.txt")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/file.txt", dst)
        with self.assertRaises(OSError):
            self.run_move(f"{src}/file.txt", dst)
        # non-empty
        self.touch(f"{dst}/file/file.txt/file.txt")
        with self.assertRaises(OSError):
            self.run_copy(f"{src}/file.txt", dst)
        with self.assertRaises(OSError):
            self.run_move(f"{src}/file.txt", dst)

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

    def test_move_dir1(self):
        src, dst = self.src, self.dst
        # move dir
        self.touch(f"{src}/dir/file.txt")
        self.run_move(f"{src}/dir", dst)
        self.assertFalse(op.exists(f"{src}/dir"))
        self.assertTrue(op.isfile(f"{dst}/dir/file.txt"))

    def test_move_dir2(self):
        src, dst = self.src, self.dst
        # overwrite move
        self.touch(f"{src}/dir/file.txt", "src")
        self.touch(f"{dst}/dir/file.txt")
        self.run_move(f"{src}/dir", dst)
        self.assertFalse(op.exists(f"{src}/dir"))
        self.assertFileContent(f"{dst}/dir/file.txt", "src")
        self.assertFalse(op.exists(f"{dst}/dir/dir"))

    def test_move_dir3(self):
        src, dst = self.src, self.dst
        # merge move
        self.touch(f"{src}/dir/file1.txt", "src")
        self.touch(f"{src}/dir/file2.txt", "src")
        self.touch(f"{dst}/dir/file1.txt")
        self.touch(f"{dst}/dir/file3.txt")

        self.run_move(f"{src}/dir", dst)
        self.assertFalse(op.exists(f"{src}/dir"))
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

    def test_move_file1(self):
        src, dst = self.src, self.dst
        # move file
        self.touch(f"{src}/file.txt")
        self.run_move(f"{src}/file.txt", dst)
        self.assertFalse(op.exists(f"{src}/file.txt"))
        self.assertTrue(op.isfile(f"{dst}/file/file.txt"))

    def test_move_file2(self):
        src, dst = self.src, self.dst
        # overwrite file
        self.touch(f"{src}/file.txt", "src")
        self.touch(f"{dst}/file/file.txt")
        self.run_move(f"{src}/file.txt", dst)
        self.assertFalse(op.exists(f"{src}/file.txt"))
        self.assertFileContent(f"{dst}/file/file.txt", "src")


if __name__ == "__main__":
    unittest.main()
