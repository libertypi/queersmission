#!/usr/bin/env python3

import logging
import os
import os.path as op
import sys
import tempfile
import unittest

sys.path.append(op.realpath(f"{__file__}/../.."))
from queersmission import copy_file


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


if __name__ == "__main__":
    unittest.main()
