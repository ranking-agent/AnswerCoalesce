"""Setup file for AC package."""
from setuptools import setup

setup(
    name='Answer Coalesce',
    version='1.0.0',
    author='Phil Owen',
    author_email='powen@renci.org',
    url='https://github.com/TranslatorIIPrototypes/AnswerCoalesce',
    description='Answer Coalesce - Offers coalesced answers based on the answer passed in.',
    packages=['ac'],
    include_package_data=True,
    zip_safe=False,
    license='MIT',
    python_requires='>=3.8',
)
