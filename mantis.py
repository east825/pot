# vim: fileencoding=utf-8

"""
Mantis is simple command-line utility that helps you to manage your precious dotfiles.
"""

from __future__ import print_function

import argparse
import yaml
import glob
import os
from pprint import pprint

class DotFile(object):
    """Represents dotfile stored in repo.
    name - name of the dotfile in repository
    target - name of the file in system
    action - action for placing dotfile in system. Can be either 'symlink' or 'copy'.
    """
    def __init__(self, name, target=None, action='symlink'):
        self.name = name
        self.target = name if target is None else target
        self.action = action

    def __str__(self):
        # attrs = ' '.join('{}={}'.format(k, v) for k, v in self.__dict__.items())
        return "<DotFile: name='{name}' target='{target}' action={action}>".format(**self.__dict__)


class Config(object):
    def __init__(self, dotfiles, **kwargs):
        self.dotfiles = dotfiles
        self.__dict__.update(kwargs)


def initialize_storage(args):
    dotfiles_pattern = os.path.join(args.location, 'dotfiles', '.**')
    # for name in os.listdir(os.path.join(args.location, 'dotfiles')):
    #     print(name)
    dotfiles = [DotFile(name=os.path.basename(f)) for f in glob.iglob(dotfiles_pattern)]
    with open(os.path.join(args.location, 'config.yaml'), 'wb') as config:
        yaml.dump([df.__dict__ for df in dotfiles], config)


def install_dotfiles(args):
    pass


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
