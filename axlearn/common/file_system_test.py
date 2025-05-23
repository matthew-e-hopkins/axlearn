# Copyright © 2024 Apple Inc.

"""Tests fs utils."""
# pylint: disable=protected-access

import os
from unittest import mock

import pytest
import tensorflow as tf
from absl.testing import parameterized

from axlearn.common import file_system as fs
from axlearn.common.test_utils import TestWithTemporaryCWD


def _make_paths(paths: list[str]):
    for path in paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(path)


class UtilsTest(parameterized.TestCase):
    """Tests utils."""

    def test_wrap_exception(self):
        class CustomException(Exception):
            pass

        def fn():
            raise ValueError("test")

        with (
            self.assertRaisesRegex(CustomException, "test"),
            fs._wrap_exception(ValueError, CustomException),
        ):
            fn()

    def test_wrap_tf_errors(self):
        @fs._wrap_tf_errors
        def fn():
            raise tf.errors.NotFoundError("node_def", None, "test")

        with self.assertRaisesRegex(fs.NotFoundError, "test"):
            fn()


class LocalTest(TestWithTemporaryCWD):
    """Tests against local fs."""

    def test_isdir(self):
        dummy_file = os.path.join(self._temp_root.name, "test_file")
        _make_paths([dummy_file])
        self.assertTrue(fs.isdir(self._temp_root.name))
        self.assertFalse(fs.isdir(dummy_file))

    def test_listdir(self):
        with self.assertRaisesRegex(fs.NotFoundError, "directory"):
            fs.listdir(os.path.join(self._temp_root.name, "fake"))

        self.assertEqual([], fs.listdir(self._temp_root.name))

        dummy_file = os.path.join(self._temp_root.name, "test_file")
        _make_paths([dummy_file])
        self.assertCountEqual([os.path.basename(dummy_file)], fs.listdir(self._temp_root.name))

    def test_glob(self):
        _make_paths(
            [
                os.path.join(self._temp_root.name, "test_file"),
                os.path.join(self._temp_root.name, "test_dir", "other_file"),
                os.path.join(self._temp_root.name, "other_file"),
            ]
        )
        self.assertCountEqual(
            [
                os.path.join(self._temp_root.name, "test_file"),
                os.path.join(self._temp_root.name, "other_file"),
            ],
            fs.glob(os.path.join(self._temp_root.name, "*_file")),
        )
        self.assertCountEqual(
            [
                os.path.join(self._temp_root.name, "test_dir", "other_file"),
            ],
            fs.glob(os.path.join(self._temp_root.name, "test_dir/*_file")),
        )
        # Globbing multiple patterns.
        self.assertCountEqual(
            [
                os.path.join(self._temp_root.name, "test_file"),
                os.path.join(self._temp_root.name, "test_dir"),
                os.path.join(self._temp_root.name, "other_file"),
            ],
            fs.glob(
                [
                    os.path.join(self._temp_root.name, "test_*"),
                    os.path.join(self._temp_root.name, "*_file"),
                ]
            ),
        )
        # Globbing a non-existent path is different from listdir.
        self.assertEqual([], fs.glob(os.path.join(self._temp_root.name, "fake_dir")))
        self.assertEqual([], fs.glob(os.path.join(self._temp_root.name, "fake_dir/*_file")))

    def test_exists(self):
        dummy_file = os.path.join(self._temp_root.name, "test_file")
        self.assertFalse(fs.exists(dummy_file))
        _make_paths([dummy_file])
        self.assertTrue(fs.exists(dummy_file))

    def test_remove(self):
        dummy_file = os.path.join(self._temp_root.name, "test_file")
        with self.assertRaises(fs.NotFoundError):
            fs.remove(dummy_file)
        _make_paths([dummy_file])
        fs.remove(dummy_file)
        with self.assertRaises(fs.NotFoundError):
            fs.remove(dummy_file)

    def test_copy(self):
        src = os.path.join(self._temp_root.name, "src_file")
        dst = os.path.join(self._temp_root.name, "dst_file")

        with self.assertRaises(fs.NotFoundError):
            fs.copy(src, dst)

        _make_paths([src])
        fs.copy(src, dst)

        with fs.open(src) as sf, fs.open(dst) as df:
            self.assertEqual(sf.read(), df.read())

        src2 = os.path.join(self._temp_root.name, "src_file2")
        _make_paths([src2])

        with self.assertRaises(fs.OpError):
            fs.copy(src2, dst, overwrite=False)
        fs.copy(src2, dst, overwrite=True)

        with fs.open(src2) as sf, fs.open(dst) as df:
            self.assertEqual(sf.read(), df.read())

    def test_open(self):
        src = os.path.join(self._temp_root.name, "src_file")
        _make_paths([src])
        with fs.open(src) as f:
            self.assertIn("src_file", f.read())

    def test_readfile(self):
        src = os.path.join(self._temp_root.name, "src_file")
        with self.assertRaises(fs.NotFoundError):
            fs.readfile(src)
        _make_paths([src])
        self.assertEqual(src, fs.readfile(src))

    def test_makedirs(self):
        test_dir = os.path.join(self._temp_root.name, "src_dir")
        self.assertFalse(fs.exists(test_dir))
        fs.makedirs(test_dir)
        self.assertTrue(fs.isdir(test_dir))

        test_file = os.path.join(self._temp_root.name, "src_file")
        _make_paths([test_file])
        with self.assertRaisesRegex(fs.OpError, "src_file"):
            fs.makedirs(test_file)

    def test_rmtree(self):
        paths = [
            os.path.join(self._temp_root.name, "dir", "nested_dir", "nested_file"),
            os.path.join(self._temp_root.name, "dir", "test_file"),
            os.path.join(self._temp_root.name, "top_file"),
        ]
        base_dir = os.path.join(self._temp_root.name, "dir")
        self.assertFalse(fs.exists(base_dir))

        with self.assertRaises(fs.NotFoundError):
            fs.rmtree(base_dir)
        _make_paths(paths)
        self.assertTrue(fs.isdir(base_dir))
        fs.rmtree(base_dir)

        self.assertFalse(fs.exists(base_dir))
        self.assertTrue(fs.exists(os.path.join(self._temp_root.name, "top_file")))


class GsTest(TestWithTemporaryCWD):
    """Tests against gs."""

    def test_glob_mocked(self):
        try:
            # pylint: disable-next=import-outside-toplevel
            from google.api_core.exceptions import GoogleAPIError, NotFound
        except (ImportError, ModuleNotFoundError) as e:
            pytest.skip(reason=f"Missing dependencies: {e}")

        self.assertIsInstance(GoogleAPIError("test"), Exception)
        self.assertIsInstance(NotFound("test"), Exception)

        # Test a case where we fail to init the client.
        with (
            mock.patch("tensorflow.io.gfile.glob", return_value="mocked_tfio"),
            mock.patch(f"{fs.__name__}._gs_client", side_effect=RuntimeError()),
        ):
            self.assertEqual("mocked_tfio", fs.glob("gs://dummy/path"))

        # Test a happy case with `client.list_blobs`.
        bucket_name = "test-bucket"
        _make_paths(
            [
                os.path.join(self._temp_root.name, "dummy/file1"),
                os.path.join(self._temp_root.name, "dummy/file2"),
            ]
        )

        def list_blobs(bucket_or_name, match_glob):
            self.assertEqual(bucket_name, bucket_or_name)
            blobs = []
            for path in fs.glob(os.path.join(self._temp_root.name, match_glob)):
                blob = mock.Mock()
                blob.name = path.replace(self._temp_root.name, "").lstrip("/")
                blobs.append(blob)
            return blobs

        mock_client = mock.Mock()
        mock_client.list_blobs.side_effect = list_blobs

        with mock.patch(f"{fs.__name__}._gs_client", return_value=mock_client):
            self.assertCountEqual(
                ["gs://test-bucket/dummy/file2", "gs://test-bucket/dummy/file1"],
                fs.glob(f"gs://{bucket_name}/dummy/file*"),
            )
            self.assertCountEqual(
                ["gs://test-bucket/dummy/file1"],
                fs.glob(f"gs://{bucket_name}/dummy/file1"),
            )

        # Test a case where `client.list_blobs` raises.
        def raise_api_error(*args, **kwargs):
            raise GoogleAPIError("test")

        mock_client = mock.Mock()
        mock_client.list_blobs.side_effect = raise_api_error

        with (
            self.assertRaises(fs.OpError),
            mock.patch(f"{fs.__name__}._gs_client", return_value=mock_client),
        ):
            fs.glob(f"gs://{bucket_name}/dummy")

        # Test a case where `client.list_blobs` raises NotFound.
        def raise_not_found(*args, **kwargs):
            raise NotFound("test")

        mock_client = mock.Mock()
        mock_client.list_blobs.side_effect = raise_not_found

        with (
            self.assertRaises(fs.NotFoundError),
            mock.patch(f"{fs.__name__}._gs_client", return_value=mock_client),
        ):
            fs.glob(f"gs://{bucket_name}/dummy")

    def test_rmtree_mocked(self):
        dummy_folder = {
            "tmp/foo/",
            "tmp/foo/index",
            "tmp/foo/bar/",
            "tmp/foo/bar/x/",
            "tmp/foo/bar/x/x.txt",
            "tmp/foo/bar/y/",
            "tmp/foo/bar/y/y.txt",
            "tmp/foo/baz/",
            "tmp/foo/baz/z/",
            "tmp/foo/baz/z/z.txt",
        }

        def tf_rmtree_mock(path):
            self.assertEndsWith(path.rstrip("/"), "tmp/foo")
            objects = [x for x in dummy_folder if not x.endswith("/")]
            for x in objects:
                dummy_folder.remove(x)

        def create_mock_folder(name_value):
            m = mock.Mock()
            m.name = name_value
            return m

        mock_client = mock.Mock()
        mock_client.list_folders.side_effect = lambda request: [
            create_mock_folder(folder_name) for folder_name in dummy_folder
        ]
        mock_client.delete_folder.side_effect = lambda req: dummy_folder.remove(req.name)
        mock_client.common_project_path.return_value = "projects/_"

        with (
            mock.patch("tensorflow.io.gfile.rmtree", side_effect=tf_rmtree_mock),
            mock.patch(f"{fs.__name__}._is_hierarchical_namespace_enabled", return_value=True),
            mock.patch(f"{fs.__name__}._gs_control_client", return_value=mock_client),
        ):
            fs.rmtree("gs://dummy/tmp/foo")
            self.assertEmpty(dummy_folder)

    @pytest.mark.gs_login
    def test_glob(self):
        self.assertCountEqual(
            fs.glob("gs://axlearn-public/testdata/gcp_test/tmp"),
            tf.io.gfile.glob("gs://axlearn-public/testdata/gcp_test/tmp"),
        )
