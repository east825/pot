# vim: fileencoding=utf-8

"""
Mantis is simple command-line utility that helps you to manage your precious dotfiles.
"""

from __future__ import print_function

import argparse
import shutil
import yaml
import glob
import os
from StringIO import StringIO
from pprint import pprint
import logging
import re


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
console = logging.StreamHandler()
console.setLevel(logging.DEBUG)
console.setFormatter(fmt=logging.Formatter('%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(console)
logger.propagate = False

DEFAULT_INCLUSION_FORMAT = '. {src}'

class DotFile(object):
    """Represents single dotfile stored in repo.

    name - name of the dotfile in repository
    target - name of the file in system
    action - action for placing dotfile in system. Can be one of symlink/copy/include.
    """
    def __init__(self, name, target=None, action='symlink'):
        self.name = name
        self.target = os.path.join('~', name) if target is None else target
        self.action = action

    def __str__(self):
        # attrs = ' '.join('{}={}'.format(k, v) for k, v in self.__dict__.items())
        return "<DotFile: name={name!r} target={target!r} action={action!r}>".format(**self.__dict__)

class Config(object):
    def __init__(self, dotfiles, **kwargs):
        self.dotfiles = dotfiles
        self.__dict__.update(kwargs)

    def __str__(self):
        attrs = dict(self.__dict__)
        dotfiles = attrs.pop('dotfiles')
        return '<Config: {} len(dotfiles)={}>'.format(
            ' '.join('{}={}'.format(k, v) for k, v in attrs.items()),
            len(dotfiles))

    @classmethod
    def from_yaml(cls, stream):
        config = yaml.load(stream)
        dotfiles = config.pop('dotfiles')
        dotfiles = [DotFile(**df) for df in dotfiles]
        return cls(dotfiles, **config)

    def to_yaml(self, stream=None):
        if stream is None:
            stringbuf= StringIO()
            self.to_yaml(stringbuf)
            return stringbuf.getvalue()
        else:
            attrs = dict(self.__dict__)
            dotfiles = attrs.pop('dotfiles')
            dotfiles = dict(dotfiles=[d.__dict__ for d in self.dotfiles])
            yaml.dump(attrs, stream, default_flow_style=False)
            yaml.dump(dotfiles, stream, default_flow_style=False)


def initialize_storage(args):
    dotfiles_pattern = os.path.join(args.location, 'dotfiles', '.**')
    # for name in os.listdir(os.path.join(args.location, 'dotfiles')):
    #     print(name)
    dotfiles = [DotFile(name=os.path.basename(f)) for f in glob.iglob(dotfiles_pattern)]
    config = Config(dotfiles, foo='bar')
    logger.debug('New config:\n%s', config)
    with open(os.path.join(args.location, 'config.yaml'), 'wb') as fd:
        print(config.to_yaml(stream=fd))


def install_dotfiles(args):
    with open(os.path.join(args.location, 'config.yaml')) as fd:
        config =  Config.from_yaml(fd)
    for dotfile in config.dotfiles:
        action = dotfile.action
        src = os.path.abspath(os.path.join('dotfiles', dotfile.name))
        dst = os.path.expanduser(dotfile.target)
        if action == 'symlink':
            print('Symlinking {} -> {}'.format(src, dst))
            # os.symlink(src, dst)
        elif action == 'copy':
            print('Copying {} -> {}'.format(src, dst))
            # shutil.copy(src, dst)
        elif action == 'include':
            print('Checking for previous inclusion...', end=' ')
            inclusion_smt = DEFAULT_INCLUSION_FORMAT.format(src=src)
            pattern = re.escape(inclusion_smt)
            pattern = r'^\s*{}\s*$'.format(pattern)
            logger.debug('Inclusion pattern %s', pattern)
            pattern = re.compile(pattern, re.MULTILINE)
            with open(dst, 'a+') as target:
                if pattern.search(target.read()):
                    print('Found')
                else:
                    print('Not found')
                    print('Appending {smt!r} to {target}'.format(smt=inclusion_smt, target=dst))
                    target.write(inclusion_smt + '\n')

def main():
    parser = argparse.ArgumentParser(prog='mantis', description=__doc__)
    parser.add_argument('-v', action='count', dest='verbosity')
    parser.add_argument('-f', '--force', action='store_true')
    subparsers = parser.add_subparsers()

    # new storage initialization command
    init_command = subparsers.add_parser('init')
    init_command.add_argument('location', nargs='?', default='.')
    init_command.set_defaults(func=initialize_storage)

    # dotfile installation command
    install_command = subparsers.add_parser('install')
    install_command.add_argument('-c', '--config', type=argparse.FileType('rb'))
    install_command.add_argument('location', nargs='?', default='.')
    install_command.set_defaults(func=install_dotfiles)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
