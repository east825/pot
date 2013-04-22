POT
===

Pot is a simple dotfiles manager written in Python.
It has simple command line interface that allows you to automatize some common operations with configuration files.

Directory format
----------------
::

    .pot
    ├── config.yaml
    └── dotfiles
        ├── .git
        ├── .gitignore
        ├── .gitmodules
        ├── README.md
        ├── spread.sh
        ├── .vim
        └── .vimrc

As you see all configuration stored in ``config.yaml``. It may seems you familiar if you worked with
static site genetators like `Jekyll`_ or `Obraz`_ before.

.. _Jekyll: https://github.com/mojombo/jekyll
.. _Obraz: https://bitbucket.org/vlasovskikh/obraz/overview
