from setuptools import setup

setup(
    name='pot',
    version='0.1',
    py_modules=['pot'],
    install_requires=[
        'PyYAML'
    ],
    entry_points={
        'console_scripts': [
            'pot = pot:main'
        ]
    },
    url='github.com/east825/pot',
    license='MIT',
    author='Mikhail Golubev',
    author_email='qsolo825@gmail.com',
    description='Simple console manager for your precious dotfiles'
)
