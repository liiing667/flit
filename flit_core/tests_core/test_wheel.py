import os
import shutil
import stat
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest
from testpath import assert_isfile

from flit_core.wheel import make_wheel_in, main, _check_data_rel_path

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
        # scripts/ maps to .data/scripts, everything else to .data/data
        assert 'module1-0.1.data/scripts/run.sh' in zf.namelist()
        assert 'module1-0.1.data/data/etc/app.conf' in zf.namelist()


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows does not have Unix file permissions')
def test_data_dir_scripts_executable(tmp_path):
    info = make_wheel_in(samples_dir / 'with_data_dir' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        mode = zf.getinfo('module1-0.1.data/scripts/run.sh').external_attr >> 16
        assert mode & 0o111
        mode = zf.getinfo('module1-0.1.data/data/etc/app.conf').external_attr >> 16
        assert not mode & 0o111


def test_data_dir_in_record(tmp_path):
    info = make_wheel_in(samples_dir / 'with_data_dir' / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        record = zf.read('module1-0.1.dist-info/RECORD').decode('utf-8')
    recorded = [line.split(',')[0] for line in record.splitlines()]
    assert 'module1-0.1.data/scripts/run.sh' in recorded
    assert 'module1-0.1.data/data/etc/app.conf' in recorded
    assert 'module1-0.1.data/data/share/man/man1/foo.1' in recorded


def test_data_dir_reproducible(tmp_path, monkeypatch):
    monkeypatch.setenv('SOURCE_DATE_EPOCH', '1633007882')
    out1 = tmp_path / 'out1'
    out2 = tmp_path / 'out2'
    out1.mkdir()
    out2.mkdir()
    info1 = make_wheel_in(samples_dir / 'with_data_dir' / 'pyproject.toml', out1)
    info2 = make_wheel_in(samples_dir / 'with_data_dir' / 'pyproject.toml', out2)
    assert info1.file.read_bytes() == info2.file.read_bytes()


def test_check_data_rel_path():
    assert _check_data_rel_path(os.path.join('etc', 'app.conf')) == \
        os.path.join('etc', 'app.conf')
    with pytest.raises(ValueError, match=r'\.\.'):
        _check_data_rel_path(os.path.join('..', 'escape.txt'))
    with pytest.raises(ValueError, match='escape.txt'):
        _check_data_rel_path(os.path.join('sub', '..', '..', 'escape.txt'))
    with pytest.raises(ValueError, match='abs.txt'):
        _check_data_rel_path(os.path.join(os.sep, 'abs.txt'))


@pytest.mark.skipif(sys.platform == 'win32', reason='Uses symlinks')
def test_data_dir_symlinks_not_followed(tmp_path):
    project = tmp_path / 'with_data_dir'
    shutil.copytree(samples_dir / 'with_data_dir', project)
    # A symlink pointing outside the data directory must not be followed
    os.symlink('/etc/passwd', project / 'data' / 'etc' / 'passwd_link')
    os.symlink(str(project / 'data' / 'etc'), project / 'data' / 'etc_link')
    info = make_wheel_in(project / 'pyproject.toml', tmp_path)
    assert_isfile(info.file)
    with ZipFile(info.file, 'r') as zf:
        names = zf.namelist()
    assert not any('passwd_link' in n for n in names)
    assert not any('etc_link' in n for n in names)


def _write_script_project(dir_path, extra_toml=''):
    dir_path.joinpath('module1.py').write_text("def main():\n    pass\n")
    dir_path.joinpath('pyproject.toml').write_text(
        "[build-system]\n"
        'requires = ["flit_core >=3.2,<4"]\n'
        'build-backend = "flit_core.buildapi"\n'
        "\n"
        "[project]\n"
        'name = "module1"\n'
        'version = "0.1"\n'
        'description = "A test project"\n'
        + extra_toml
    )


def test_entry_point_missing_module(tmp_path):
    _write_script_project(tmp_path, (
        "\n[project.scripts]\n"
        'foo = "nonexistent_module:main"\n'
    ))
    with pytest.raises(ValueError) as excinfo:
        make_wheel_in(tmp_path / 'pyproject.toml', tmp_path)
    assert 'console_scripts' in str(excinfo.value)
    assert 'foo' in str(excinfo.value)


def test_entry_point_duplicate_name(tmp_path):
    _write_script_project(tmp_path, (
        "\n[project.scripts]\n"
        'foo = "module1:main"\n'
        "\n[project.gui-scripts]\n"
        'foo = "module1:main"\n'
    ))
    with pytest.raises(ValueError) as excinfo:
        make_wheel_in(tmp_path / 'pyproject.toml', tmp_path)
    assert 'foo' in str(excinfo.value)
    assert 'console_scripts' in str(excinfo.value)
    assert 'gui_scripts' in str(excinfo.value)


def test_entry_point_malformed(tmp_path):
    _write_script_project(tmp_path, (
        "\n[project.scripts]\n"
        'foo = "module1"\n'
    ))
    with pytest.raises(ValueError) as excinfo:
        make_wheel_in(tmp_path / 'pyproject.toml', tmp_path)
    assert 'console_scripts' in str(excinfo.value)
    assert 'foo' in str(excinfo.value)


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
