import os
import stat
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from testpath import assert_isfile

from flit_core import common
from flit_core.wheel import (
    make_wheel_in, main, data_dir_arcname, _check_data_rel_path,
)

samples_dir = Path(__file__).parent / 'samples'

def test_licenses_dir(tmp_path):
    # Smoketest for https://github.com/pypa/flit/issues/399
    info = make_wheel_in(samples_dir / 'inclusion' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)


def test_source_date_epoch(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_DATE_EPOCH', '1633007882')
    info = make_wheel_in(samples_dir / 'pep621' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    # Minimum value for zip timestamps is 1980-1-1
    with ZipFile(info.file, 'r') as zf:
        assert zf.getinfo('module1a.py').date_time[:3] == (2021, 9, 30)


def test_zero_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_DATE_EPOCH', '0')
    info = make_wheel_in(samples_dir / 'pep621' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    # Minimum value for zip timestamps is 1980-1-1
    with ZipFile(info.file, 'r') as zf:
        assert zf.getinfo('module1a.py').date_time == (1980, 1, 1, 0, 0, 0)


def test_main(tmp_path):
    main(['--outdir', str(tmp_path), str(samples_dir / 'pep621')])
    wheels = list(tmp_path.glob('*.whl'))
    assert len(wheels) == 1
    # Minimum value for zip timestamps is 1980-1-1
    with ZipFile(wheels[0], 'r') as zf:
        assert 'module1a.py' in zf.namelist()


def test_data_dir(tmp_path):
    info = make_wheel_in(samples_dir / 'with_data_dir' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        assert 'module1-0.1.data/data/share/man/man1/foo.1' in zf.namelist()


def test_data_dir_layout(tmp_path):
    info = make_wheel_in(
        samples_dir / 'with_data_dir_layout' / 'pyproject.toml', tmp_path
    )
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        names = zf.namelist()
        assert 'module1-0.1.data/scripts/run.sh' in names
        assert 'module1-0.1.data/data/etc/app.conf' in names
        assert 'module1-0.1.data/data/scripts/run.sh' not in names
        assert 'module1-0.1.data/etc/app.conf' not in names

        # RECORD must include every data-directory file
        record = zf.read('module1-0.1.dist-info/RECORD').decode()
        assert 'module1-0.1.data/scripts/run.sh,sha256=' in record
        assert 'module1-0.1.data/data/etc/app.conf,sha256=' in record


@pytest.mark.skipif(sys.platform == 'win32', reason='Unix file permissions')
def test_data_dir_scripts_executable(tmp_path):
    info = make_wheel_in(
        samples_dir / 'with_data_dir_layout' / 'pyproject.toml', tmp_path
    )
    with ZipFile(info.file, 'r') as zf:
        script_mode = zf.getinfo('module1-0.1.data/scripts/run.sh').external_attr >> 16
        assert script_mode & 0o111, oct(script_mode)
        conf_mode = zf.getinfo(
            'module1-0.1.data/data/etc/app.conf').external_attr >> 16
        assert not conf_mode & 0o111, oct(conf_mode)


def test_data_dir_reproducible(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_DATE_EPOCH', '1633007882')
    ini = samples_dir / 'with_data_dir_layout' / 'pyproject.toml'
    info = make_wheel_in(ini, tmp_path)
    first = info.file.read_bytes()
    info2 = make_wheel_in(ini, tmp_path)
    assert first == info2.file.read_bytes()


def test_data_dir_arcname():
    assert data_dir_arcname('pkg-1.0', 'scripts/run.sh') \
        == os.path.join('pkg-1.0.data', 'scripts', 'run.sh')
    assert data_dir_arcname('pkg-1.0', 'etc/app.conf') \
        == os.path.join('pkg-1.0.data', 'data', 'etc', 'app.conf')
    assert data_dir_arcname('pkg-1.0', os.path.join('x', 'y')) \
        == os.path.join('pkg-1.0.data', 'data', 'x', 'y')


@pytest.mark.parametrize('rel', ['../escape', 'a/../../b', '/abs/path'])
def test_data_dir_arcname_escape(rel):
    with pytest.raises(ValueError) as exc_info:
        _check_data_rel_path(rel)
    assert rel in str(exc_info.value)


@pytest.mark.skipif(sys.platform == 'win32', reason='symlink test')
def test_data_dir_symlink_not_followed(tmp_path):
    import shutil
    src = samples_dir / 'with_data_dir_layout'
    proj = tmp_path / 'proj'
    shutil.copytree(src, proj)
    secret = tmp_path / 'secret.conf'
    secret.write_text('top secret\n')
    os.symlink(secret, proj / 'data' / 'etc' / 'link.conf')

    info = make_wheel_in(proj / 'pyproject.toml', tmp_path)
    with ZipFile(info.file, 'r') as zf:
        names = zf.namelist()
        assert 'module1-0.1.data/data/etc/link.conf' not in names
        assert b'top secret' not in b''.join(
            zf.read(n) for n in names if n.endswith('.conf'))


def test_entry_point_missing_module(tmp_path):
    with pytest.raises(ValueError, match='console_scripts.*foo|foo.*console_scripts'):
        make_wheel_in(samples_dir / 'bad_ep_module' / 'pyproject.toml', tmp_path)


def test_entry_point_duplicate(tmp_path):
    entrypoints = {'console_scripts': [
        ('foo', 'module1:main'), ('foo', 'module1:other'),
    ]}
    with pytest.raises(ValueError, match='console_scripts.*foo|foo.*console_scripts'):
        common.validate_entry_points(entrypoints, tmp_path)


def test_license_files(tmp_path):
    info = make_wheel_in(samples_dir / 'pep621_license_files' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        assert 'module1-0.1.dist-info/licenses/LICENSE' in zf.namelist()
        assert 'module1-0.1.dist-info/licenses/module/vendor/LICENSE_VENDOR' in zf.namelist()


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not have Unix file permissions')
def test_wheel_file_permissions(tmp_path):
    # mkstemp(), which is used to create the wheel before it's renamed to
    # its final name, creates files with mode 0600. The built wheel file
    # itself should not be left that restrictive. Regression test for
    # https://github.com/pypa/flit/issues/804
    info = make_wheel_in(samples_dir / 'pep621' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    mode = stat.S_IMODE(os.stat(info.file).st_mode)
    assert mode & 0o777 == 0o644, oct(mode)
