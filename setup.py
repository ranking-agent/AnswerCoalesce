"""Setup file for AC package."""
from setuptools import setup

setup(
    name='Answer Coalesce',
    version='2.0.2',
    author='Chris Bizon',
    author_email='bizon@renci.org',
    url='https://github.com/ranking-agent/AnswerCoalesce',
    description='Answer Coalesce - Offers coalesced answers based on an answer passed in.',
    packages=['ac'],
    include_package_data=True,
    zip_safe=False,
    license='MIT',
    python_requires='>=3.8',
)
