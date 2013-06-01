# vim: fileencoding=utf-8

# Copyright (c) 2013 Mikhail Golubev
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from contextlib import contextmanager
import tempfile
import time
import logging

import os
import pot
from pot import cd, Config, DotFile
import nose
from nose.tools import ok_, eq_, nottest


logging.basicConfig(level=logging.CRITICAL)

try:
    from tempfile import TemporaryDirectory as make_temp_dir
except ImportError:
    @contextmanager
    def make_temp_dir(suffix='', prefix='tmp', dir=None):
        temp_dir = tempfile.mkdtemp(suffix, prefix, dir)
        try:
            yield temp_dir
        finally:
            # shutil.rmtree(temp_dir)
            pass

try:
    import builtins

    if not hasattr(builtins, 'callable'):
        callable = lambda x: hasattr(x, '__call__')
except ImportError:
    # python2.7 has 'callable' BIF
    pass


# os.path.getmtime() follows symlinks by default. I've got a lot of creepy bugs
# because of that before I realized what happens.
# As a workaround I use lstat to get modification time without following symlinks.
# Actually in python3.3 you can get nanoseconds precision because result of lstat there
# has st_mtime_ns field. I use delays as compatibility workaround.
def mtime(path):
    return os.lstat(path).st_mtime


def delayed(before=0, after=0):
    def decorator(f):
        def wrapper(*args, **kwargs):
            time.sleep(before)
            res = f(*args, **kwargs)
            time.sleep(after)
            return res

        return wrapper

    return decorator


@contextmanager
def temp_cwd(suffix='', prefix='tmp', dir=None):
    with make_temp_dir(suffix, prefix, dir) as tempd:
        with cd(tempd):
            yield tempd


@contextmanager
def assert_modified(path):
    path = os.path.abspath(path)
    # can't get modification time or read broken symlink
    # assume it's always modified
    if pot.broken_link(path):
        yield
        return
    old_mtime = mtime(path)
    was_file = False
    if os.path.isfile(path):
        was_file = True
        with open(path) as fd:
            old_content = fd.read()
    yield
    if old_mtime < mtime(path):
        return
        # compare file content only if system mtime resolution isn't enough
    if os.path.isfile(path) and was_file:
        with open(path) as fd:
            content = fd.read()
            assert old_content != content, 'File "{}" was not modified'.format(path)
    else:
        raise AssertionError('File "{}" was not modified'.format(path))


@contextmanager
def assert_not_modified(path):
    try:
        with assert_modified(path):
            yield
    except AssertionError:
        pass
    else:
        raise AssertionError('File "{}" was modified'.format(path))


def make_hierarchy(d):
    for key, val in d.items():
        if isinstance(val, dict):
            os.mkdir(key)
            with cd(key):
                make_hierarchy(val)
        elif callable(val):
            val(key)
        else:
            with open(key, 'w') as fd:
                fd.write(val)


@contextmanager
def updated_env(**kwargs):
    old_env = os.environ.copy()
    os.environ.update(kwargs)
    yield
    os.environ = old_env


def test_config_serialization():
    config = Config([
        DotFile(name='.vimrc', target='~/_vimrc', action='symlink'),
        DotFile(name='.bashrc', action='include'),
        DotFile(name='rc.conf', target='.config/openbox/rc.conf', action='copy')
    ])
    expected_string = """\
dotfiles:
- name: .vimrc
  target: ~/_vimrc
  action: symlink
- name: .bashrc
  target: ~/.bashrc
  action: include
- name: rc.conf
  target: .config/openbox/rc.conf
  action: copy
"""
    eq_(expected_string, config.to_yaml())


def test_init():
    with temp_cwd(prefix='pot-test'):
        make_hierarchy({
            'dotfiles': {
                '.gitconfig': '',
                '.vimrc': '',
                '.vim': {},
            }
        })
        pot.init(path='.')
        expected_config = Config(dotfiles=[DotFile('.gitconfig'), DotFile('.vimrc'), DotFile('.vim'), ])
        with open('config.yaml') as fd:
            builded_config = Config.from_yaml(fd)
        eq_(expected_config, builded_config)


def test_install():
    config = """\
dotfiles:
- name: .vimrc
  target: ~/.vimrc
  action: symlink
- name: .bashrc
  target: ~/.bashrc
  action: include
- name: .vim
  target: ../somedir/vimfiles
  action: copy
"""
    with temp_cwd(prefix='pot-test'):
        make_hierarchy({
            'pot': {
                'dotfiles': {
                    '.vim': {},
                    '.vimrc': '1\n',
                    '.bashrc': '2\n',
                    '.gitconfig': ''
                },
                'config.yaml': config
            },
            'home': {
                '.gitconfig': 'already exists\n',
                '.bashrc': ''
            },
            'somedir': {}
        })
        with assert_not_modified('home/.gitconfig'):
            with updated_env(HOME=os.path.abspath('home')):
                with cd('pot'):
                    pot.install()
            # symlink pointing to correct location created
        eq_(os.readlink('home/.vimrc'), os.path.abspath('pot/dotfiles/.vimrc'))
        # new directory created
        ok_(os.path.isdir('somedir/vimfiles'))
        # configuration included
        eq_(open('home/.bashrc').read(), '. {}\n'.format(os.path.abspath('pot/dotfiles/.bashrc')))


@nottest
def _test_existing(content, modified=False, force=False):
    with temp_cwd(prefix='pot-test'):
        make_hierarchy({
            'pot': {
                'dotfiles': {
                    'dotfile': ''
                },
                'config.yaml': 'dotfiles: [{name: dotfile}]'
            },
            'home': {
                'dotfile': content
            }
        })
        # default system mtime resolution is not sufficient
        # time.sleep(2)
        mgr = assert_modified if modified else assert_not_modified
        with mgr('home/dotfile'):
            with updated_env(HOME=os.path.abspath('home')):
                with cd('pot'):
                    pot.install(['dotfile'], force=force)


def test_existing_file():
    _test_existing('other file', modified=False, force=False)


def test_existing_dir():
    _test_existing({}, modified=False, force=False)


def test_existing_symlink():
    _test_existing(lambda x: os.symlink('../pot', x), modified=False, force=False)


def test_symlink_to_same_file():
    _test_existing(lambda x: os.symlink('../pot/dotfiles/dotfile', x), modified=True, force=False)


def test_broken_symlink():
    _test_existing(lambda x: os.symlink('not-exists', x), modified=True, force=False)


def test_force_mode():
    cases = [
        'other file',
        delayed(0.05, 0.05)(lambda x: os.mkdir(x)),
        delayed(0.05, 0.05)(lambda x: os.symlink('.', x)), # valid symlink
        lambda x: os.symlink('not-exists', x) # broken symlink
    ]
    for content in cases:
        yield _test_existing, content, True, True


if __name__ == '__main__':
    nose.core.runmodule()




